import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.db.mongodb import get_db
from app.models.common import serialize, to_object_id

bearer = HTTPBearer(auto_error=True)
optional_bearer = HTTPBearer(auto_error=False)

_HEARTBEAT_THROTTLE = timedelta(minutes=2)


def _touch_last_active(db, doc: dict) -> None:
    """Best-effort 'last seen' heartbeat for the admin dashboard's Online Now
    count. Throttled to ~once every 2 minutes per user (using the value
    already on hand from the request's own user lookup, so this needs no
    extra query) and fired without awaiting it, so a slow or failed write
    here can never delay or break the request it's piggybacking on.
    """
    now = datetime.now(timezone.utc)
    last = doc.get("last_active_at")
    if last and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last and (now - last) < _HEARTBEAT_THROTTLE:
        return

    async def _update():
        try:
            await db.users.update_one({"_id": doc["_id"]}, {"$set": {"last_active_at": now}})
        except Exception:
            pass

    asyncio.create_task(_update())


async def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
) -> dict | None:
    """Like get_current_user but returns None instead of raising when no/invalid token."""
    if not creds:
        return None
    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        return None
    user_id = payload.get("sub")
    db = get_db()
    doc = await db.users.find_one({"_id": to_object_id(user_id)})
    return serialize(doc) if doc else None


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")
    db = get_db()
    doc = await db.users.find_one({"_id": to_object_id(user_id)})
    if not doc:
        raise HTTPException(status_code=401, detail="User not found")
    _touch_last_active(db, doc)
    return serialize(doc)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_super_admin(user: dict = Depends(require_admin)) -> dict:
    # Admins created before this feature have no `is_super` field -> treated as
    # super (the original owner credential). New admins are created with is_super=False.
    if not user.get("is_super", True):
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user
