"""
Super-admin WebAuthn (fingerprint / Face ID / passkey) sign-in.

Lets the super admin (owner) register a passkey while signed in with their
password, then sign in to the admin panel with the biometric alone — no more
typing the password every time. Credentials are stored server-side against the
super-admin's user document, so a passkey the OS syncs (same Google / Apple
account on a laptop and a phone) works on every synced device, and discoverable
(resident) credentials enable usernameless login.

Scope: this is super-admin only, by construction.
  - register endpoints require a super-admin password session (require_super_admin).
  - login/verify issues a token only when the passkey's owner is role "admin"
    AND is_super — a normal admin or customer can never obtain one.

Additive and isolated: this router does not touch /auth/login, /auth/me, or any
other existing endpoint. Mounted under /admin/webauthn.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Depends, Body

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)

from app.core.config import settings
from app.core.security import create_access_token
from app.db.mongodb import get_db
from app.deps import require_super_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/admin/webauthn", tags=["admin-webauthn"])

CHALLENGE_TTL_SECONDS = 300


def _now():
    return datetime.now(timezone.utc)


def _resolve_origin(request: Request):
    """Return (origin, rp_id) for an allowlisted Origin, else 400."""
    origin = request.headers.get("origin")
    allow = settings.webauthn_origin_list
    if not origin or origin not in allow:
        raise HTTPException(status_code=400, detail="Origin not allowed for passkey sign-in")
    rp_id = urlparse(origin).hostname
    if not rp_id:
        raise HTTPException(status_code=400, detail="Invalid origin")
    return origin, rp_id


async def _user_handle(db, admin: dict) -> bytes:
    """Stable per-admin WebAuthn user handle (created lazily)."""
    handle = admin.get("webauthn_user_handle")
    if not handle:
        handle = bytes_to_base64url(os.urandom(16))
        await db.users.update_one({"_id": to_object_id(admin["id"])}, {"$set": {"webauthn_user_handle": handle}})
    return base64url_to_bytes(handle)


def _public_user(doc: dict) -> dict:
    """Same shape the password login hands the admin panel (auth._public)."""
    from app.routers.auth import _public
    return _public(doc).model_dump()


# ─────────────── REGISTER (signed-in super admin adds a passkey) ───────────────
@router.post("/register/options")
async def register_options(request: Request, admin: dict = Depends(require_super_admin)):
    origin, rp_id = _resolve_origin(request)
    db = get_db()
    existing = [c async for c in db.admin_webauthn_credentials.find({"user_id": admin["id"]})]
    opts = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_name=admin["email"],
        user_id=await _user_handle(db, admin),
        user_display_name=admin.get("name") or admin["email"],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["_id"])) for c in existing
        ],
    )
    await db.users.update_one(
        {"_id": to_object_id(admin["id"])},
        {"$set": {
            "webauthn_reg_challenge": bytes_to_base64url(opts.challenge),
            "webauthn_reg_rp_id": rp_id,
            "webauthn_reg_origin": origin,
            "webauthn_reg_exp": _now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        }},
    )
    return json.loads(options_to_json(opts))


@router.post("/register/verify")
async def register_verify(
    request: Request,
    admin: dict = Depends(require_super_admin),
    body: dict = Body(...),
):
    db = get_db()
    fresh = await db.users.find_one({"_id": to_object_id(admin["id"])})
    challenge = fresh.get("webauthn_reg_challenge") if fresh else None
    exp = fresh.get("webauthn_reg_exp") if fresh else None
    if not challenge or not exp:
        raise HTTPException(status_code=400, detail="Passkey setup expired. Try again.")
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if _now() > exp:
        raise HTTPException(status_code=400, detail="Passkey setup expired. Try again.")
    response = body.get("response") or body
    label = (body.get("label") or "").strip() or "This device"
    try:
        verification = verify_registration_response(
            credential=json.dumps(response),
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=fresh.get("webauthn_reg_rp_id"),
            expected_origin=fresh.get("webauthn_reg_origin"),
            require_user_verification=True,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not verify passkey: {e}")

    cred_id = bytes_to_base64url(verification.credential_id)
    transports = []
    try:
        transports = (response.get("response") or {}).get("transports") or response.get("transports") or []
    except Exception:
        transports = []
    await db.admin_webauthn_credentials.update_one(
        {"_id": cred_id},
        {"$set": {
            "_id": cred_id,
            "user_id": admin["id"],
            "email": admin["email"],
            "public_key": bytes_to_base64url(verification.credential_public_key),
            "sign_count": verification.sign_count,
            "transports": transports,
            "label": label,
            "rp_id": fresh.get("webauthn_reg_rp_id"),
            "created_at": _now(),
        }},
        upsert=True,
    )
    await db.users.update_one(
        {"_id": to_object_id(admin["id"])},
        {"$unset": {"webauthn_reg_challenge": "", "webauthn_reg_exp": "", "webauthn_reg_rp_id": "", "webauthn_reg_origin": ""}},
    )
    return {"message": "Passkey added.", "credential_id": cred_id, "label": label}


# ─────────────── LOGIN (usernameless passkey sign-in) ───────────────
@router.post("/login/options")
async def login_options(request: Request):
    origin, rp_id = _resolve_origin(request)
    db = get_db()
    opts = generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = bytes_to_base64url(os.urandom(16))
    await db.admin_webauthn_challenges.update_one(
        {"_id": challenge_id},
        {"$set": {
            "_id": challenge_id,
            "challenge": bytes_to_base64url(opts.challenge),
            "rp_id": rp_id,
            "origin": origin,
            "exp": _now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        }},
        upsert=True,
    )
    return {"challenge_id": challenge_id, "options": json.loads(options_to_json(opts))}


@router.post("/login/verify")
async def login_verify(request: Request, body: dict = Body(...)):
    db = get_db()
    challenge_id = body.get("challenge_id")
    response = body.get("response")
    if not challenge_id or not response:
        raise HTTPException(status_code=400, detail="Missing passkey response")

    ch = await db.admin_webauthn_challenges.find_one({"_id": challenge_id})
    if not ch:
        raise HTTPException(status_code=400, detail="Passkey session expired. Try again.")
    exp = ch["exp"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if _now() > exp:
        await db.admin_webauthn_challenges.delete_one({"_id": challenge_id})
        raise HTTPException(status_code=400, detail="Passkey session expired. Try again.")

    cred_id = response.get("id")
    cred = await db.admin_webauthn_credentials.find_one({"_id": cred_id})
    if not cred:
        raise HTTPException(status_code=401, detail="This passkey is not registered.")

    admin = await db.users.find_one({"_id": to_object_id(cred["user_id"])})
    # Super-admin only: role "admin" AND is_super (missing => owner => super).
    if not admin or admin.get("role") != "admin" or admin.get("is_super", True) is False:
        raise HTTPException(status_code=403, detail="Super-admin account not found for this passkey.")

    try:
        verification = verify_authentication_response(
            credential=json.dumps(response),
            expected_challenge=base64url_to_bytes(ch["challenge"]),
            expected_rp_id=ch["rp_id"],
            expected_origin=ch["origin"],
            credential_public_key=base64url_to_bytes(cred["public_key"]),
            credential_current_sign_count=cred.get("sign_count", 0),
            require_user_verification=True,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Passkey verification failed: {e}")

    await db.admin_webauthn_credentials.update_one(
        {"_id": cred_id},
        {"$set": {"sign_count": verification.new_sign_count, "last_used_at": _now()}},
    )
    await db.admin_webauthn_challenges.delete_one({"_id": challenge_id})

    user = serialize(admin)
    token = create_access_token(user["id"], "admin")
    now = _now()
    await db.users.update_one({"_id": admin["_id"]}, {"$set": {"last_login": now}})
    await db.admin_activity.insert_one({
        "admin_id": user["id"],
        "admin_email": user.get("email"),
        "admin_name": user.get("name"),
        "method": "LOGIN",
        "path": "/admin/webauthn/login/verify",
        "action": "Logged in (passkey)",
        "status": 200,
        "at": now,
    })
    return {"access_token": token, "user": _public_user(user)}


# ─────────────── MANAGE (list / remove passkeys) ───────────────
@router.get("/credentials")
async def list_credentials(admin: dict = Depends(require_super_admin)):
    db = get_db()
    out = []
    async for c in db.admin_webauthn_credentials.find({"user_id": admin["id"]}):
        out.append({
            "id": c["_id"],
            "label": c.get("label", "Device"),
            "created_at": str(c.get("created_at", "")),
            "last_used_at": str(c.get("last_used_at", "")),
        })
    return {"credentials": out, "count": len(out)}


@router.delete("/credentials/{credential_id}")
async def delete_credential(credential_id: str, admin: dict = Depends(require_super_admin)):
    db = get_db()
    res = await db.admin_webauthn_credentials.delete_one({"_id": credential_id, "user_id": admin["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Passkey not found")
    return {"message": "Passkey removed."}
