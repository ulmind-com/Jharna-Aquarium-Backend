"""Physical retail stores shown by the storefront's "Find Your Nearest Store".

The section is grouped by city: the admin types the city on each store and
gives it a `city_order`, which is what decides the order of the city tabs
(lowest first). Within a city the stores follow their own `order`.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/stores", tags=["stores"])

SORT = [("city_order", 1), ("city", 1), ("order", 1)]


class StoreIn(BaseModel):
    name: str
    city: str
    image: str = ""
    address: str = ""
    map_url: str = ""
    phone: str = ""
    hours: str = ""
    city_order: int = 0
    order: int = 0
    active: bool = True


class StoreUpdate(BaseModel):
    name: str | None = None
    city: str | None = None
    image: str | None = None
    address: str | None = None
    map_url: str | None = None
    phone: str | None = None
    hours: str | None = None
    city_order: int | None = None
    order: int | None = None
    active: bool | None = None


@router.get("")
async def public_stores():
    """Active stores, already sorted so the storefront can group them as-is."""
    db = get_db()
    docs = await db.stores.find({"active": True}).sort(SORT).to_list(length=500)
    return [serialize(d) for d in docs]


@router.get("/admin", dependencies=[Depends(require_admin)])
async def admin_stores():
    """Everything, including stores switched off."""
    db = get_db()
    docs = await db.stores.find({}).sort(SORT).to_list(length=500)
    return [serialize(d) for d in docs]


@router.post("", dependencies=[Depends(require_admin)])
async def create_store(body: StoreIn):
    db = get_db()
    doc = body.model_dump()
    doc["city"] = doc["city"].strip()
    if not doc["city"]:
        raise HTTPException(status_code=400, detail="City required")
    # Append to the end of its city unless the caller placed it explicitly.
    if not doc.get("order"):
        last = await db.stores.find({"city": doc["city"]}).sort("order", -1).to_list(length=1)
        doc["order"] = (last[0].get("order", 0) + 1) if last else 0
    # New city inherits the position of an existing one so tabs stay stable.
    if not doc.get("city_order"):
        sibling = await db.stores.find_one({"city": doc["city"]})
        if sibling:
            doc["city_order"] = sibling.get("city_order", 0)
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.stores.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/{store_id}", dependencies=[Depends(require_admin)])
async def update_store(store_id: str, body: StoreUpdate):
    db = get_db()
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.stores.find_one_and_update(
        {"_id": to_object_id(store_id)}, {"$set": patch}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Store not found")
    return serialize(res)


@router.put("/city-order", dependencies=[Depends(require_admin)])
async def reorder_cities(cities: list[str] = Body(..., embed=True)):
    """Persist the city tab order: array position becomes `city_order`."""
    db = get_db()
    for i, city in enumerate(cities):
        await db.stores.update_many({"city": city}, {"$set": {"city_order": i}})
    return {"ok": True, "count": len(cities)}


@router.put("/order", dependencies=[Depends(require_admin)])
async def reorder_stores(ids: list[str] = Body(..., embed=True)):
    """Persist a reorder inside one city: array position becomes `order`."""
    db = get_db()
    for i, sid in enumerate(ids):
        await db.stores.update_one({"_id": to_object_id(sid)}, {"$set": {"order": i}})
    return {"ok": True, "count": len(ids)}


@router.delete("/{store_id}", dependencies=[Depends(require_admin)])
async def delete_store(store_id: str):
    db = get_db()
    res = await db.stores.delete_one({"_id": to_object_id(store_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Store not found")
    return {"deleted": True}
