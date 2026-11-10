from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import hash_password
from app.db.mongodb import get_db
from app.deps import require_super_admin
from app.models.common import serialize, to_object_id
from app.models.user import AdminCreate, AdminUpdate

router = APIRouter(prefix="/admins", tags=["admins"])


def _admin_public(d: dict) -> dict:
    return {
        "id": d["id"],
        "name": d.get("name"),
        "email": d.get("email"),
        "is_super": bool(d.get("is_super", True)),
        "permissions": d.get("permissions"),  # None = full access
        "created_at": str(d["created_at"]) if d.get("created_at") else None,
        "last_login": str(d["last_login"]) if d.get("last_login") else None,
    }


@router.get("", dependencies=[Depends(require_super_admin)])
async def list_admins():
    """Super admin: list every admin account."""
    db = get_db()
    docs = await db.users.find({"role": "admin"}).sort("created_at", 1).to_list(200)
    return [_admin_public(serialize(d)) for d in docs]


@router.post("", dependencies=[Depends(require_super_admin)])
async def create_admin(body: AdminCreate):
    """Super admin: create a new (non-super) admin the team can log in with."""
    db = get_db()
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="This email is already registered.")
    doc = {
        "name": body.name,
        "email": email,
        "password": hash_password(body.password),
        "role": "admin",
        "is_super": False,
        "permissions": body.permissions,
        "created_at": datetime.now(timezone.utc),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _admin_public(serialize(doc))


@router.patch("/{admin_id}")
async def update_admin(admin_id: str, body: AdminUpdate, su: dict = Depends(require_super_admin)):
    """Super admin: edit a team admin — rename, reset password, or change access."""
    target = await get_db().users.find_one({"_id": to_object_id(admin_id)})
    if not target or target.get("role") != "admin":
        raise HTTPException(status_code=404, detail="Admin not found.")
    if target.get("is_super", True):
        raise HTTPException(status_code=400, detail="A super admin cannot be edited here.")
    patch: dict = {}
    if body.name is not None:
        patch["name"] = body.name
    if body.password:
        patch["password"] = hash_password(body.password)
    if body.permissions is not None:
        patch["permissions"] = body.permissions
    if patch:
        await get_db().users.update_one({"_id": to_object_id(admin_id)}, {"$set": patch})
    updated = await get_db().users.find_one({"_id": to_object_id(admin_id)})
    return _admin_public(serialize(updated))


@router.delete("/{admin_id}")
async def revoke_admin(admin_id: str, su: dict = Depends(require_super_admin)):
    """Super admin: revoke a team admin's access (demotes to a normal user)."""
    db = get_db()
    if admin_id == su["id"]:
        raise HTTPException(status_code=400, detail="You cannot remove yourself.")
    target = await db.users.find_one({"_id": to_object_id(admin_id)})
    if not target or target.get("role") != "admin":
        raise HTTPException(status_code=404, detail="Admin not found.")
    if target.get("is_super", True):
        raise HTTPException(status_code=400, detail="A super admin cannot be removed.")
    await db.users.update_one(
        {"_id": to_object_id(admin_id)},
        {"$set": {"role": "user", "is_super": False}},
    )
    return {"ok": True}


@router.get("/activity", dependencies=[Depends(require_super_admin)])
async def activity(admin_id: str | None = None, limit: int = 300):
    """Super admin: audit trail of what each admin did after logging in."""
    db = get_db()
    query: dict = {}
    if admin_id:
        query["admin_id"] = admin_id
    docs = await db.admin_activity.find(query).sort("at", -1).to_list(min(limit, 500))
    return [
        {
            "id": str(d["_id"]),
            "admin_id": d.get("admin_id"),
            "admin_email": d.get("admin_email"),
            "admin_name": d.get("admin_name"),
            "method": d.get("method"),
            "path": d.get("path"),
            "action": d.get("action"),
            "status": d.get("status"),
            "at": str(d["at"]) if d.get("at") else None,
        }
        for d in docs
    ]
