from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import get_current_user
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


class WishlistSyncBody(BaseModel):
    product_ids: list[str] = []


def _with_discount(doc: dict) -> dict:
    price = doc.get("price") or 0
    mrp = doc.get("mrp")
    doc["discount_pct"] = round((mrp - price) / mrp * 100) if mrp and mrp > price else 0
    return doc


def _effective_pricing(doc: dict) -> tuple[float, float]:
    """Return effective unit price and MRP matching storefront variant defaults."""
    sizes = doc.get("sizes") or []
    variant = next((s for s in sizes if (s.get("stock") or 0) > 0), sizes[0] if sizes else None)
    price = float((variant or {}).get("price") or doc.get("price") or 0)
    raw_mrp = (variant or {}).get("mrp") if variant else doc.get("mrp")
    mrp = float(raw_mrp if raw_mrp is not None else price)
    return price, max(mrp, price)


async def _sync_product_wishlist_count(db, product_id: str) -> int:
    """Recompute and persist how many shoppers currently wishlist a product."""
    count = await db.wishlists.count_documents({"product_ids": product_id})
    if ObjectId.is_valid(product_id):
        await db.products.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {"wishlist_count": count}},
        )
    return count


async def _build_wishlist_payload(db, ids: list[str]) -> dict:
    valid_oids = [to_object_id(i) for i in ids if ObjectId.is_valid(i)]
    if not valid_oids:
        return {"ids": [], "products": [], "count": 0, "total_amount": 0, "total_mrp": 0}
    raw_products = await db.products.find({"_id": {"$in": valid_oids}}).to_list(length=200)
    by_id = {str(p["_id"]): _with_discount(serialize(p)) for p in raw_products}
    ordered_ids = [i for i in ids if i in by_id]
    ordered_products = [by_id[i] for i in ordered_ids]

    total_amount = 0.0
    total_mrp = 0.0
    for prod in ordered_products:
        price, mrp = _effective_pricing(prod)
        total_amount += price
        total_mrp += mrp

    return {
        "ids": ordered_ids,
        "products": ordered_products,
        "count": len(ordered_products),
        "total_amount": round(total_amount, 2),
        "total_mrp": round(total_mrp, 2),
    }


@router.get("")
async def get_wishlist(user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.wishlists.find_one({"user_id": user["id"]})
    ids = (doc or {}).get("product_ids", [])
    return await _build_wishlist_payload(db, ids)


@router.get("/ids")
async def get_wishlist_ids(user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.wishlists.find_one({"user_id": user["id"]})
    return {"ids": (doc or {}).get("product_ids", [])}


@router.post("/sync")
async def sync_wishlist(body: WishlistSyncBody, user: dict = Depends(get_current_user)):
    """Merge guest-saved product IDs into the signed-in user's wishlist."""
    db = get_db()
    candidate_ids = [pid for pid in dict.fromkeys(body.product_ids) if ObjectId.is_valid(pid)]
    if candidate_ids:
        existing_docs = await db.products.find(
            {"_id": {"$in": [ObjectId(pid) for pid in candidate_ids]}},
            {"_id": 1},
        ).to_list(length=200)
        valid_ids = [str(d["_id"]) for d in existing_docs]
        if valid_ids:
            await db.wishlists.update_one(
                {"user_id": user["id"]},
                {"$addToSet": {"product_ids": {"$each": valid_ids}}},
                upsert=True,
            )
            for pid in valid_ids:
                await _sync_product_wishlist_count(db, pid)
    doc = await db.wishlists.find_one({"user_id": user["id"]})
    return await _build_wishlist_payload(db, (doc or {}).get("product_ids", []))


@router.post("/{product_id}")
async def add_wishlist(product_id: str, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    db = get_db()
    if not await db.products.find_one({"_id": to_object_id(product_id)}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Product not found")
    await db.wishlists.update_one(
        {"user_id": user["id"]},
        {"$addToSet": {"product_ids": product_id}},
        upsert=True,
    )
    wishlist_count = await _sync_product_wishlist_count(db, product_id)
    return {"added": True, "product_id": product_id, "wishlist_count": wishlist_count}


@router.delete("/{product_id}")
async def remove_wishlist(product_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    await db.wishlists.update_one(
        {"user_id": user["id"]}, {"$pull": {"product_ids": product_id}}
    )
    wishlist_count = await _sync_product_wishlist_count(db, product_id)
    return {"removed": True, "product_id": product_id, "wishlist_count": wishlist_count}
