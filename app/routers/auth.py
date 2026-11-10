import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import requests
from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.config import settings as app_settings
from app.core.security import (
    create_access_token,
    create_signup_token,
    decode_signup_token,
    hash_password,
    verify_password,
)
from app.db.mongodb import get_db
from app.deps import get_current_user
from app.models.common import serialize, to_object_id
from app.models.user import (
    AuthResponse,
    OtpRequest,
    OtpVerify,
    ProfileUpdate,
    SignupComplete,
    UserLogin,
    UserPublic,
)
from app.services import email_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _public(doc: dict) -> UserPublic:
    created_at_val = doc.get("created_at")
    created_str = str(created_at_val) if created_at_val else None
    return UserPublic(
        id=str(doc["id"]) if "id" in doc else str(doc["_id"]),
        name=doc.get("name", ""),
        email=doc.get("email", ""),
        phone=doc.get("phone"),
        avatar=doc.get("avatar"),
        role=doc.get("role", "user"),
        # No stored flag on the original owner account => treat as super admin.
        is_super=bool(doc.get("is_super", doc.get("role") == "admin")),
        # None => unrestricted (owner / admins created before this feature).
        permissions=doc.get("permissions"),
        addresses=doc.get("addresses") or [],
        cart=doc.get("cart") or [],
        created_at=created_str,
    )


def _otp_hash(code: str, email: str) -> str:
    """Keyed hash so codes aren't stored in plaintext at rest."""
    return hashlib.sha256(
        f"{code}:{email}:{app_settings.JWT_SECRET}".encode()
    ).hexdigest()


@router.post("/otp/request")
async def request_otp(body: OtpRequest):
    """Step 1 of signup: email a 6-digit verification code (rate-limited)."""
    db = get_db()
    email = body.email.lower()
    existing_user = await db.users.find_one({"email": email})
    if existing_user:
        if existing_user.get("provider") == "google" or not existing_user.get("password"):
            raise HTTPException(status_code=409, detail="You already have an account created with Google. Please click 'Continue with Google' below to log in!")
        raise HTTPException(status_code=409, detail="Email is already registered. Please click 'Sign in' below to log in with your password.")

    now = datetime.now(timezone.utc)
    existing = await db.otps.find_one({"_id": email})
    if existing:
        last = existing.get("last_sent_at")
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last:
            elapsed = (now - last).total_seconds()
            if elapsed < app_settings.OTP_RESEND_COOLDOWN_SECONDS:
                wait = int(app_settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed)
                raise HTTPException(status_code=429, detail=f"Please wait {wait}s before requesting another code.")

    code = f"{secrets.randbelow(1000000):06d}"
    await db.otps.update_one(
        {"_id": email},
        {"$set": {
            "code_hash": _otp_hash(code, email),
            "expires_at": now + timedelta(minutes=app_settings.OTP_TTL_MINUTES),
            "attempts": 0,
            "last_sent_at": now,
        }},
        upsert=True,
    )

    sent = email_service.send_otp_email(email, code, app_settings.OTP_TTL_MINUTES)
    if not sent and app_settings.RESEND_API_KEY:
        raise HTTPException(status_code=502, detail="Could not send the verification email. Please try again.")
    if not sent:
        print(f"[otp] {email} -> {code} (email disabled; dev only)")
    return {"ok": True, "message": f"We sent a 6-digit code to {email}.",
            "resend_in": app_settings.OTP_RESEND_COOLDOWN_SECONDS}


@router.post("/otp/verify")
async def verify_otp(body: OtpVerify):
    """Step 2: check the code and hand back a short-lived signup token."""
    db = get_db()
    email = body.email.lower()
    doc = await db.otps.find_one({"_id": email})
    if not doc:
        raise HTTPException(status_code=400, detail="Please request a new code.")

    exp = doc.get("expires_at")
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if not exp or datetime.now(timezone.utc) > exp:
        await db.otps.delete_one({"_id": email})
        raise HTTPException(status_code=400, detail="This code has expired. Request a new one.")
    if doc.get("attempts", 0) >= app_settings.OTP_MAX_ATTEMPTS:
        await db.otps.delete_one({"_id": email})
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")
    if _otp_hash(body.code.strip(), email) != doc.get("code_hash"):
        await db.otps.update_one({"_id": email}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

    # Correct — burn the code so it can't be reused, and issue the signup token.
    await db.otps.delete_one({"_id": email})
    return {"verified": True, "signup_token": create_signup_token(email)}


@router.post("/register", response_model=AuthResponse)
async def register(body: SignupComplete):
    """Step 3: consume the signup token (verified email) + profile -> account."""
    db = get_db()
    try:
        email = decode_signup_token(body.signup_token).lower()
    except Exception:
        raise HTTPException(status_code=400, detail="Your verification expired. Please verify your email again.")

    existing_user = await db.users.find_one({"email": email})
    if existing_user:
        if existing_user.get("provider") == "google" or not existing_user.get("password"):
            raise HTTPException(status_code=409, detail="You already have an account created with Google. Please click 'Continue with Google' below to log in!")
        raise HTTPException(status_code=409, detail="Email is already registered. Please log in.")

    doc = {
        "name": body.name.strip(),
        "email": email,
        "phone": body.phone.strip(),
        "password": hash_password(body.password),
        "role": "user",
        "addresses": [],
        "fcm_tokens": [],
        "email_verified": True,
        "created_at": datetime.now(timezone.utc),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    user = serialize(doc)

    token = create_access_token(user["id"], user["role"])
    return AuthResponse(access_token=token, user=_public(user))


@router.post("/login", response_model=AuthResponse)
async def login(body: UserLogin):
    db = get_db()
    doc = await db.users.find_one({"email": body.email.lower()})
    if doc and (doc.get("provider") == "google" or not doc.get("password")):
        # User signed up via Google and has no password
        raise HTTPException(status_code=400, detail="This account uses Google Sign-In. Please click 'Continue with Google' below to log in!")
    if not doc or not verify_password(body.password, doc.get("password", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user = serialize(doc)
    token = create_access_token(user["id"], user.get("role", "user"))
    if user.get("role") == "admin":
        now = datetime.now(timezone.utc)
        await db.users.update_one({"_id": doc["_id"]}, {"$set": {"last_login": now}})
        await db.admin_activity.insert_one({
            "admin_id": user["id"],
            "admin_email": user.get("email"),
            "admin_name": user.get("name"),
            "method": "LOGIN",
            "path": "/auth/login",
            "action": "Logged in",
            "status": 200,
            "at": now,
        })
    return AuthResponse(access_token=token, user=_public(user))


@router.post("/google", response_model=AuthResponse)
async def google_auth(id_token: str = Body(..., embed=True)):
    """Sign in with a Google ID token from the app; upsert the user, issue JWT."""
    if not app_settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google sign-in is not configured")

    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token as g_id_token

    try:
        info = g_id_token.verify_oauth2_token(
            id_token, g_requests.Request(), app_settings.GOOGLE_CLIENT_ID
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    email = (info.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    db = get_db()
    doc = await db.users.find_one({"email": email})
    if not doc:
        doc = {
            "name": info.get("name") or email.split("@")[0],
            "email": email,
            "phone": None,
            "password": None,
            "role": "user",
            "provider": "google",
            "google_sub": info.get("sub"),
            "avatar": info.get("picture"),
            "addresses": [],
            "fcm_tokens": [],
            "created_at": datetime.now(timezone.utc),
        }
        res = await db.users.insert_one(doc)
        doc["_id"] = res.inserted_id
    else:
        # Link Google to an existing email-based account; backfill avatar.
        patch = {}
        if not doc.get("provider"):
            patch["provider"] = "google"
        if not doc.get("google_sub"):
            patch["google_sub"] = info.get("sub")
        if not doc.get("avatar") and info.get("picture"):
            patch["avatar"] = info.get("picture")
        if patch:
            await db.users.update_one({"_id": doc["_id"]}, {"$set": patch})
            doc.update(patch)

    user = serialize(doc)
    token = create_access_token(user["id"], user.get("role", "user"))
    return AuthResponse(access_token=token, user=_public(user))


@router.post("/firebase", response_model=AuthResponse)
async def firebase_auth(id_token: str = Body(..., embed=True)):
    """Sign in with a Firebase ID token (from signInWithPopup on the web).

    Uses firebase_admin to verify the token, then upserts the user in MongoDB
    exactly like /auth/google. This is more reliable for web-based sign-in
    because the Firebase SDK's signInWithPopup returns a Firebase ID token
    whose audience is the Firebase project, not the Google OAuth Client ID.
    """
    from app.services.fcm_service import _ensure_app

    if _ensure_app():
        # Service-account path (also what FCM uses).
        from firebase_admin import auth as fb_auth

        try:
            decoded = fb_auth.verify_id_token(id_token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid Firebase token")
    else:
        # No FIREBASE_CREDENTIALS on this deploy: verify the ID token against
        # Google's public signing certs instead. Only the (public) project id
        # is needed, so web sign-in keeps working without a service account.
        if not app_settings.FIREBASE_PROJECT_ID:
            raise HTTPException(status_code=500, detail="Firebase is not configured")

        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token as g_id_token

        try:
            decoded = g_id_token.verify_firebase_token(
                id_token, g_requests.Request(), app_settings.FIREBASE_PROJECT_ID
            )
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid Firebase token")
        if decoded.get("iss") != f"https://securetoken.google.com/{app_settings.FIREBASE_PROJECT_ID}":
            raise HTTPException(status_code=401, detail="Invalid Firebase token")

    # verify_firebase_token puts the Firebase uid in "sub"/"user_id"; the Google
    # account id lives in firebase.identities — keep the same shape either way.
    decoded.setdefault("sub", decoded.get("user_id"))

    email = (decoded.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Firebase account has no email")

    db = get_db()
    doc = await db.users.find_one({"email": email})
    if not doc:
        doc = {
            "name": decoded.get("name") or email.split("@")[0],
            "email": email,
            "phone": None,
            "password": None,
            "role": "user",
            "provider": "google",
            "google_sub": decoded.get("sub"),
            "avatar": decoded.get("picture"),
            "addresses": [],
            "fcm_tokens": [],
            "email_verified": bool(decoded.get("email_verified")),
            "created_at": datetime.now(timezone.utc),
        }
        res = await db.users.insert_one(doc)
        doc["_id"] = res.inserted_id
    else:
        patch = {}
        if not doc.get("provider"):
            patch["provider"] = "google"
        if not doc.get("google_sub"):
            patch["google_sub"] = decoded.get("sub")
        if not doc.get("avatar") and decoded.get("picture"):
            patch["avatar"] = decoded.get("picture")
        if patch:
            await db.users.update_one({"_id": doc["_id"]}, {"$set": patch})
            doc.update(patch)

    user = serialize(doc)
    token = create_access_token(user["id"], user.get("role", "user"))
    return AuthResponse(access_token=token, user=_public(user))


@router.post("/facebook", response_model=AuthResponse)
async def facebook_auth(access_token: str = Body(..., embed=True)):
    """Sign in with a Facebook access token from the app; upsert the user, issue JWT.

    Mirrors /auth/google. The token is first checked against our own app via
    debug_token (so a token minted for another app can't be replayed), then the
    profile is read from the Graph API. Facebook may withhold email — we fall
    back to a stable Facebook-scoped placeholder so the account still works."""
    if not (app_settings.FACEBOOK_APP_ID and app_settings.FACEBOOK_APP_SECRET):
        raise HTTPException(status_code=500, detail="Facebook sign-in is not configured")

    app_token = f"{app_settings.FACEBOOK_APP_ID}|{app_settings.FACEBOOK_APP_SECRET}"
    try:
        dbg = requests.get(
            "https://graph.facebook.com/debug_token",
            params={"input_token": access_token, "access_token": app_token},
            timeout=10,
        ).json()
    except Exception:
        raise HTTPException(status_code=401, detail="Could not verify Facebook token")
    data = dbg.get("data") or {}
    if not data.get("is_valid") or str(data.get("app_id")) != str(app_settings.FACEBOOK_APP_ID):
        raise HTTPException(status_code=401, detail="Invalid Facebook token")

    try:
        me_res = requests.get(
            "https://graph.facebook.com/me",
            params={"fields": "id,name,email,picture.width(200)", "access_token": access_token},
            timeout=10,
        ).json()
    except Exception:
        raise HTTPException(status_code=401, detail="Could not read Facebook profile")

    fb_id = me_res.get("id")
    if not fb_id:
        raise HTTPException(status_code=401, detail="Invalid Facebook account")
    email = (me_res.get("email") or "").lower() or f"{fb_id}@facebook.local"
    name = me_res.get("name") or "Facebook User"
    picture = (((me_res.get("picture") or {}).get("data")) or {}).get("url")

    db = get_db()
    doc = await db.users.find_one({"$or": [{"email": email}, {"facebook_id": fb_id}]})
    if not doc:
        doc = {
            "name": name,
            "email": email,
            "phone": None,
            "password": None,
            "role": "user",
            "provider": "facebook",
            "facebook_id": fb_id,
            "avatar": picture,
            "addresses": [],
            "fcm_tokens": [],
            "created_at": datetime.now(timezone.utc),
        }
        res = await db.users.insert_one(doc)
        doc["_id"] = res.inserted_id
    else:
        # Link Facebook to an existing account; backfill avatar.
        patch = {}
        if not doc.get("provider"):
            patch["provider"] = "facebook"
        if not doc.get("facebook_id"):
            patch["facebook_id"] = fb_id
        if not doc.get("avatar") and picture:
            patch["avatar"] = picture
        if patch:
            await db.users.update_one({"_id": doc["_id"]}, {"$set": patch})
            doc.update(patch)

    user = serialize(doc)
    token = create_access_token(user["id"], user.get("role", "user"))
    return AuthResponse(access_token=token, user=_public(user))


@router.get("/me", response_model=UserPublic)
async def me(user: dict = Depends(get_current_user)):
    return _public(user)


@router.post("/change-password")
async def change_password(
    current_password: str = Body(..., embed=True),
    new_password: str = Body(..., embed=True, min_length=6, max_length=128),
    user: dict = Depends(get_current_user),
):
    """Swap the password, proving the old one first.

    Social sign-ups have no password stored yet; they are allowed to set one
    without proving anything, since there is nothing to prove.
    """
    db = get_db()
    doc = await db.users.find_one({"_id": to_object_id(user["id"])})
    if not doc:
        raise HTTPException(status_code=404, detail="Account not found")

    stored = doc.get("password") or ""
    if stored and not verify_password(current_password, stored):
        raise HTTPException(status_code=400, detail="Your current password is incorrect")
    if verify_password(new_password, stored) if stored else False:
        raise HTTPException(status_code=400, detail="Pick a password you haven't used here before")

    await db.users.update_one(
        {"_id": doc["_id"]},
        {"$set": {"password": hash_password(new_password), "password_changed_at": datetime.now(timezone.utc)}},
    )
    return {"ok": True, "had_password": bool(stored)}


@router.patch("/me", response_model=UserPublic)
async def update_me(body: ProfileUpdate, user: dict = Depends(get_current_user)):
    db = get_db()
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.phone is not None:
        updates["phone"] = body.phone.strip() or None
    if body.avatar is not None:
        updates["avatar"] = body.avatar or None
    if body.addresses is not None:
        updates["addresses"] = body.addresses
    if body.cart is not None:
        updates["cart"] = body.cart
    if updates:
        await db.users.update_one({"_id": to_object_id(user["id"])}, {"$set": updates})
    doc = await db.users.find_one({"_id": to_object_id(user["id"])})
    return _public(serialize(doc))
