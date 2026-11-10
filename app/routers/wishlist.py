from fastapi import APIRouter, Depends, HTTPException

from app.db.mongodb import get_db
from app.deps import get_current_user
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


def _with_discount(doc: dict) -> dict:
    price = doc.get("price") or 0
    mrp = doc.get("mrp")
    doc["discount_pct"] = round((mrp - price) / mrp * 100) if mrp and mrp > price else 0
    return doc


@router.get("")
async def get_wishlist(user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.wishlists.find_one({"user_id": user["id"]})
    ids = (doc or {}).get("product_ids", [])
    if not ids:
        return {"ids": [], "products": []}
    obj_ids = [to_object_id(i) for i in ids if len(i) == 24]
    products = await db.products.find({"_id": {"$in": obj_ids}}).to_list(length=200)
    return {
        "ids": ids,
        "products": [_with_discount(serialize(p)) for p in products],
    }


@router.get("/ids")
async def get_wishlist_ids(user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.wishlists.find_one({"user_id": user["id"]})
    return {"ids": (doc or {}).get("product_ids", [])}


@router.post("/{product_id}")
async def add_wishlist(product_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    if not await db.products.find_one({"_id": to_object_id(product_id)}):
        raise HTTPException(status_code=404, detail="Product not found")
    await db.wishlists.update_one(
        {"user_id": user["id"]},
        {"$addToSet": {"product_ids": product_id}},
        upsert=True,
    )
    return {"added": True, "product_id": product_id}


@router.delete("/{product_id}")
async def remove_wishlist(product_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    await db.wishlists.update_one(
        {"user_id": user["id"]}, {"$pull": {"product_ids": product_id}}
    )
    return {"removed": True, "product_id": product_id}
