from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException

from app.db.mongodb import get_db
from app.deps import get_current_user, require_admin
from app.models.common import to_object_id

router = APIRouter(prefix="/users", tags=["users"])

# Order statuses that count as a real (paid/confirmed) order for a customer's
# lifetime stats — abandoned online orders (status "placed") are excluded.
_REAL_ORDER = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"]

_ONLINE_WINDOW = timedelta(minutes=5)
_IST = ZoneInfo("Asia/Kolkata")


@router.get("/admin/count", dependencies=[Depends(require_admin)])
async def admin_user_count():
    """Admin dashboard: total signed-up customers, how many are active right
    now, and how many signed up today (IST calendar day) — all excluding
    admin/staff accounts.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    today_ist_start = datetime.now(_IST).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_ist_start.astimezone(timezone.utc)

    count = await db.users.count_documents({"role": {"$ne": "admin"}})
    online_now = await db.users.count_documents({
        "role": {"$ne": "admin"},
        "last_active_at": {"$gte": now - _ONLINE_WINDOW},
    })
    new_today = await db.users.count_documents({
        "role": {"$ne": "admin"},
        "created_at": {"$gte": today_start_utc},
    })
    return {"count": count, "online_now": online_now, "new_today": new_today}


@router.get("/admin/online", dependencies=[Depends(require_admin)])
async def admin_online_users():
    """Admin dashboard: who is online right now (same 5-minute heartbeat
    window as /admin/count's `online_now` number), most-recently-active first.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    docs = await db.users.find(
        {"role": {"$ne": "admin"}, "last_active_at": {"$gte": now - _ONLINE_WINDOW}},
        {"name": 1, "email": 1, "avatar": 1, "last_active_at": 1},
    ).sort("last_active_at", -1).to_list(length=500)
    return [
        {
            "id": str(d["_id"]),
            "name": d.get("name") or "Unknown customer",
            "email": d.get("email", ""),
            "avatar": d.get("avatar"),
            "last_active_at": d.get("last_active_at"),
        }
        for d in docs
    ]


@router.get("/admin/list", dependencies=[Depends(require_admin)])
async def list_users(q: str | None = None, limit: int = 100):
    """Admin: search users (by name/email) to target a notification."""
    db = get_db()
    query: dict = {}
    if q:
        query = {"$or": [
            {"name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
        ]}
    docs = await db.users.find(
        query, {"name": 1, "email": 1, "role": 1}
    ).sort("created_at", -1).to_list(length=min(max(limit, 1), 500))
    return [
        {"id": str(d["_id"]), "name": d.get("name", ""), "email": d.get("email", ""), "role": d.get("role", "user")}
        for d in docs
    ]


@router.get("/admin/all", dependencies=[Depends(require_admin)])
async def admin_all_users(q: str | None = None, limit: int = 500):
    """Admin Users page: every customer with their full details, order stats
    and current Cash-on-Delivery status. Password is never returned."""
    db = get_db()
    query: dict = {}
    if q:
        query = {"$or": [
            {"name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
        ]}
    docs = await db.users.find(
        query, {"password": 0}
    ).sort("created_at", -1).to_list(length=min(max(limit, 1), 2000))

    # One aggregation for everyone's lifetime order stats & recent orders.
    ids = [str(d["_id"]) for d in docs]
    stats: dict = {}
    orders_map: dict = {}
    if ids:
        pipeline = [
            {"$match": {"user_id": {"$in": ids}, "status": {"$in": _REAL_ORDER}}},
            {"$group": {"_id": "$user_id", "orders": {"$sum": 1}, "spent": {"$sum": "$amount"}}},
        ]
        async for r in db.orders.aggregate(pipeline):
            stats[r["_id"]] = {"orders": r["orders"], "spent": round(r.get("spent") or 0, 2)}

        # Also fetch latest orders for each user
        recent_cur = await db.orders.find({"user_id": {"$in": ids}}).sort("created_at", -1).to_list(length=1000)
        for ord_doc in recent_cur:
            uid_key = ord_doc["user_id"]
            if uid_key not in orders_map:
                orders_map[uid_key] = []
            if len(orders_map[uid_key]) < 5:
                orders_map[uid_key].append({
                    "id": str(ord_doc["_id"]),
                    "status": ord_doc.get("status", "placed"),
                    "amount": round(ord_doc.get("amount") or 0, 2),
                    "created_at": str(ord_doc.get("created_at") or ""),
                    "items_count": len(ord_doc.get("items") or []),
                })

    out = []
    for d in docs:
        uid = str(d["_id"])
        st = stats.get(uid, {"orders": 0, "spent": 0})
        out.append({
            "id": uid,
            "name": d.get("name", ""),
            "email": d.get("email", ""),
            "phone": d.get("phone"),
            "role": d.get("role", "user"),
            "avatar": d.get("avatar"),
            "provider": d.get("provider", "email"),
            "created_at": d.get("created_at"),
            "cod_blocked": bool(d.get("cod_blocked", False)),
            "fcm_tokens": len(d.get("fcm_tokens") or []),
            "addresses": d.get("addresses") or [],
            "cart_count": len(d.get("cart") or []),
            "cart_items": d.get("cart") or [],
            "recent_orders": orders_map.get(uid, []),
            "orders_count": st["orders"],
            "total_spent": st["spent"],
        })
    return out


@router.patch("/admin/{user_id}/cod", dependencies=[Depends(require_admin)])
async def set_user_cod(user_id: str, blocked: bool = Body(..., embed=True)):
    """Admin: turn Cash on Delivery off (or back on) for a single customer."""
    db = get_db()
    res = await db.users.find_one_and_update(
        {"_id": to_object_id(user_id)},
        {"$set": {"cod_blocked": bool(blocked)}},
        return_document=True,
    )
    if not res:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user_id, "cod_blocked": bool(blocked)}


@router.post("/fcm-token")
async def register_fcm_token(
    token: str = Body(..., embed=True), user: dict = Depends(get_current_user)
):
    db = get_db()
    await db.users.update_one(
        {"_id": to_object_id(user["id"])}, {"$addToSet": {"fcm_tokens": token}}
    )
    return {"ok": True}


@router.delete("/fcm-token")
async def remove_fcm_token(
    token: str = Body(..., embed=True), user: dict = Depends(get_current_user)
):
    db = get_db()
    await db.users.update_one(
        {"_id": to_object_id(user["id"])}, {"$pull": {"fcm_tokens": token}}
    )
    return {"ok": True}
