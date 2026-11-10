from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/banners", tags=["banners"])


class BannerIn(BaseModel):
    image: str                    # banner image url (recommended 1000x420, ~2.4:1)
    title: str = ""
    subtitle: str = ""
    code: str = ""                # optional coupon code to surface on the banner
    active: bool = True
    order: int = 0


@router.get("")
async def list_banners(admin: bool = False):
    db = get_db()
    q = {} if admin else {"active": True}
    docs = await db.banners.find(q).sort("order", 1).to_list(length=50)
    return [serialize(d) for d in docs]


@router.post("", dependencies=[Depends(require_admin)])
async def create_banner(body: BannerIn):
    db = get_db()
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.banners.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/{banner_id}", dependencies=[Depends(require_admin)])
async def update_banner(banner_id: str, body: dict = Body(...)):
    db = get_db()
    body.pop("id", None)
    res = await db.banners.find_one_and_update(
        {"_id": to_object_id(banner_id)}, {"$set": body}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Banner not found")
    return serialize(res)


@router.delete("/{banner_id}", dependencies=[Depends(require_admin)])
async def delete_banner(banner_id: str):
    db = get_db()
    await db.banners.delete_one({"_id": to_object_id(banner_id)})
    return {"deleted": True}
