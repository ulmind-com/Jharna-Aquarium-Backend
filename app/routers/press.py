"""The "As featured in" logo strip on the home page."""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/press", tags=["press"])

CONFIG_ID = "press"


class PressConfig(BaseModel):
    active: bool = True
    title: str = "As featured in"


class LogoIn(BaseModel):
    name: str
    image: str
    url: str = ""
    order: int = 0
    active: bool = True


class LogoUpdate(BaseModel):
    name: str | None = None
    image: str | None = None
    url: str | None = None
    order: int | None = None
    active: bool | None = None


async def _config(db) -> dict:
    doc = await db.site_config.find_one({"_id": CONFIG_ID})
    if not doc:
        return PressConfig().model_dump()
    doc.pop("_id", None)
    return {**PressConfig().model_dump(), **serialize(doc)}


@router.get("")
async def public_press():
    db = get_db()
    docs = await db.press_logos.find({"active": True}).sort("order", 1).to_list(length=100)
    return {"section": await _config(db), "items": [serialize(d) for d in docs]}


@router.get("/admin", dependencies=[Depends(require_admin)])
async def admin_press():
    db = get_db()
    docs = await db.press_logos.find({}).sort("order", 1).to_list(length=100)
    return {"section": await _config(db), "items": [serialize(d) for d in docs]}


@router.put("/section", dependencies=[Depends(require_admin)])
async def save_section(body: PressConfig):
    db = get_db()
    patch = body.model_dump()
    patch["updated_at"] = datetime.now(timezone.utc)
    await db.site_config.update_one({"_id": CONFIG_ID}, {"$set": patch}, upsert=True)
    return await _config(db)


@router.post("", dependencies=[Depends(require_admin)])
async def create_logo(body: LogoIn):
    db = get_db()
    doc = body.model_dump()
    if not doc["image"]:
        raise HTTPException(status_code=400, detail="Logo image required")
    if not doc.get("order"):
        last = await db.press_logos.find({}).sort("order", -1).to_list(length=1)
        doc["order"] = (last[0].get("order", 0) + 1) if last else 0
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.press_logos.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/{logo_id}", dependencies=[Depends(require_admin)])
async def update_logo(logo_id: str, body: LogoUpdate):
    db = get_db()
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.press_logos.find_one_and_update(
        {"_id": to_object_id(logo_id)}, {"$set": patch}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Logo not found")
    return serialize(res)


@router.put("/order", dependencies=[Depends(require_admin)])
async def reorder_logos(ids: list[str] = Body(..., embed=True)):
    db = get_db()
    for i, lid in enumerate(ids):
        await db.press_logos.update_one({"_id": to_object_id(lid)}, {"$set": {"order": i}})
    return {"ok": True, "count": len(ids)}


@router.delete("/{logo_id}", dependencies=[Depends(require_admin)])
async def delete_logo(logo_id: str):
    db = get_db()
    res = await db.press_logos.delete_one({"_id": to_object_id(logo_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Logo not found")
    return {"deleted": True}
