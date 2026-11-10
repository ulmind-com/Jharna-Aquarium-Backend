from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from app.db.mongodb import get_db
from app.deps import get_current_user, require_admin
from app.models.common import serialize, to_object_id
from app.models.waitlist import WaitlistCreate
from app.services.pricing import price_span, total_stock, variant_stock
from app.services.waitlist_service import notify_restocked

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.post("")
async def join_waitlist(body: WaitlistCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    # Check if product exists
    prod = await db.products.find_one({"_id": to_object_id(body.product_id)})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if already requested
    existing = await db.waitlist.find_one({
        "user_id": user["id"],
        "product_id": body.product_id,
        "status": "pending"
    })
    
    if existing:
        return {"success": True, "message": "Already on waitlist"}

    doc = {
        "user_id": user["id"],
        "product_id": body.product_id,
        "size_name": body.size_name,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    res = await db.waitlist.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.get("/admin/summary", dependencies=[Depends(require_admin)])
async def waitlist_summary():
    """Admin: which products are out of stock and who is waiting for each,
    oldest request first so the admin can see who has waited the longest.
    """
    db = get_db()
    # Oldest-first, so each product's grouped list is already in queue order.
    waitlists = await db.waitlist.find({"status": "pending"}).sort("created_at", 1).to_list(length=5000)

    if not waitlists:
        return []

    grouped: dict[str, list[dict]] = defaultdict(list)
    for w in waitlists:
        grouped[w["product_id"]].append(w)

    product_ids = list(grouped.keys())
    products = await db.products.find({"_id": {"$in": [to_object_id(pid) for pid in product_ids]}}).to_list(length=1000)

    user_ids = {w["user_id"] for w in waitlists if w.get("user_id")}
    users: dict[str, dict] = {}
    if user_ids:
        object_ids = []
        for uid in user_ids:
            try:
                object_ids.append(to_object_id(uid))
            except Exception:
                continue
        if object_ids:
            async for u in db.users.find({"_id": {"$in": object_ids}}, {"name": 1, "email": 1, "phone": 1}):
                users[str(u["_id"])] = u

    result = []
    for p in products:
        p_id = str(p["_id"])
        d = serialize(p)
        d.update(price_span(d))  # final_price etc. — same computed fields the product list uses
        d["total_stock"] = total_stock(d)

        entries = grouped[p_id]
        waiting = []
        for w in entries:
            u = users.get(w.get("user_id"), {})
            # The exact size this customer is waiting for may still be at 0
            # even when the product's aggregate stock (shown above) is > 0 —
            # surface the real number so that's never mistaken for a stuck entry.
            waiting.append({
                "user_id": w.get("user_id"),
                "name": u.get("name") or "Unknown customer",
                "email": u.get("email") or "",
                "phone": u.get("phone") or "",
                "size_name": w.get("size_name"),
                "size_stock": variant_stock(p, w.get("size_name")),
                "waiting_since": w.get("created_at"),
            })

        result.append({
            "product": d,
            "count": len(entries),
            "waiting": waiting,
        })

    return sorted(result, key=lambda x: x["count"], reverse=True)


@router.post("/admin/{product_id}/resolve", dependencies=[Depends(require_admin)])
async def resolve_waitlist(product_id: str):
    """Manual override: force-email every pending waiter for this product
    right now, regardless of current stock. Restocking a product normally
    notifies everyone automatically the moment its stock is saved (see
    `waitlist_service.notify_restocked`, called from `PATCH /products/{id}`)
    — this exists only as a fallback for an admin who wants to notify anyway
    (e.g. the automatic check somehow missed a size).
    """
    db = get_db()
    pending = await db.waitlist.find(
        {"product_id": product_id, "status": "pending"}
    ).to_list(length=2000)
    if not pending:
        return {"success": True, "resolved_count": 0}

    prod = await db.products.find_one({"_id": to_object_id(product_id)})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    keys = {w.get("size_name") for w in pending}
    sent = await notify_restocked(db, prod, keys)
    return {"success": True, "resolved_count": sent}
