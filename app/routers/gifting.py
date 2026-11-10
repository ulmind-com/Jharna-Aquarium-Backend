"""The "Green gifting" band under Garden Services on the home page.

One settings document — the band is a single piece of artwork plus copy, so
there is nothing to list or order.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize

router = APIRouter(prefix="/gifting", tags=["gifting"])

CONFIG_ID = "gifting"


class GiftingConfig(BaseModel):
    active: bool = True
    title: str = "Green gifting,\nmade easy."
    body: str = ""
    brands_line: str = ""
    image: str = ""
    primary_label: str = "Shop Hampers"
    primary_url: str = "/combos"
    secondary_label: str = "Bulk Order"
    secondary_url: str = "/contact"


async def _config(db) -> dict:
    doc = await db.site_config.find_one({"_id": CONFIG_ID})
    if not doc:
        return GiftingConfig().model_dump()
    doc.pop("_id", None)
    return {**GiftingConfig().model_dump(), **serialize(doc)}


@router.get("")
async def public_gifting():
    return await _config(get_db())


@router.put("", dependencies=[Depends(require_admin)])
async def save_gifting(body: GiftingConfig):
    db = get_db()
    patch = body.model_dump()
    patch["updated_at"] = datetime.now(timezone.utc)
    await db.site_config.update_one({"_id": CONFIG_ID}, {"$set": patch}, upsert=True)
    return await _config(db)
