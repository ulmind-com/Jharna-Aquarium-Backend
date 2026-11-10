import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.mongodb import get_db
from app.deps import get_current_user, get_optional_user, require_admin
from app.models.common import serialize, to_object_id
from app.services.pricing import coupon_discount

router = APIRouter(prefix="/coupons", tags=["coupons"])

# A customer is on their first order until they have an order that reached at
# least "confirmed" (paid online or COD). Used to gate first-order-only coupons.
_FIRST_ORDER_DONE = ["confirmed", "shipped", "out_for_delivery", "delivered"]


async def is_first_order(db, user_id: str | None) -> bool:
    if not user_id:
        return False
    n = await db.orders.count_documents(
        {"user_id": user_id, "status": {"$in": _FIRST_ORDER_DONE}}
    )
    return n == 0


class CouponIn(BaseModel):
    code: str
    type: str = "percent"          # "percent" | "flat"
    value: float = Field(ge=0)
    min_order: float = 0
    max_discount: float = 0        # 0 = no cap (percent only)
    active: bool = True
    first_order_only: bool = False  # usable only on the customer's first order
    free_shipping: bool = False     # grants free shipping regardless of distance
    usage_limit: int = 0            # 0 = unlimited total uses
    limit_per_user: int = 0         # 0 = unlimited per user
    valid_from: str | None = None   # ISO datetime — coupon starts showing/working
    valid_until: str | None = None  # ISO datetime — auto-expires after this
    description: str = ""


def _parse(dt: str | None):
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt)
    except ValueError:
        return None


def _in_window(coupon: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    vf, vu = _parse(coupon.get("valid_from")), _parse(coupon.get("valid_until"))
    if vf and now < vf:
        return False
    if vu and now > vu:
        return False
    return True


async def get_coupon(db, code: str, user_id: str | None = None):
    """Fetch a live coupon by code.

    A first-order-only coupon resolves only for a customer who is still on their
    first order, so a returning user can't redeem it even by typing the code.
    """
    if not code:
        return None
    c = await db.coupons.find_one({"code": code.strip().upper(), "active": True})
    if not c or not _in_window(c):
        return None
    if c.get("first_order_only") and not await is_first_order(db, user_id):
        return None
        
    usage_limit = c.get("usage_limit", 0)
    if usage_limit > 0 and c.get("used_count", 0) >= usage_limit:
        return None
        
    limit_per_user = c.get("limit_per_user", 0)
    if limit_per_user > 0 and user_id:
        used_by_me = await db.orders.count_documents({
            "user_id": user_id, 
            "coupon_code": c["code"], 
            "status": {"$in": ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"]}
        })
        if used_by_me >= limit_per_user:
            return None
            
    return c


@router.get("", dependencies=[Depends(require_admin)])
async def list_coupons():
    db = get_db()
    docs = await db.coupons.find().sort("created_at", -1).to_list(length=200)
    return [serialize(d) for d in docs]


@router.get("/active")
async def active_coupons(user: dict | None = Depends(get_optional_user)):
    """Public: coupons currently within their time window (for the Offers screen).

    First-order-only coupons are hidden from returning users (and anonymous
    visitors); a first-order customer still sees them.
    """
    db = get_db()
    first = await is_first_order(db, user["id"]) if user else False
    docs = await db.coupons.find({"active": True}).sort("created_at", -1).to_list(length=200)
    return [
        serialize(d)
        for d in docs
        if _in_window(d) and (first or not d.get("first_order_only"))
    ]


@router.post("", dependencies=[Depends(require_admin)])
async def create_coupon(body: CouponIn):
    db = get_db()
    code = body.code.strip().upper()
    if await db.coupons.find_one({"code": code}):
        raise HTTPException(status_code=409, detail="Coupon code already exists")
    doc = body.model_dump()
    doc["code"] = code
    doc["created_at"] = datetime.now(timezone.utc)
    doc["used_count"] = 0
    res = await db.coupons.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/{coupon_id}", dependencies=[Depends(require_admin)])
async def update_coupon(coupon_id: str, body: dict = Body(...)):
    db = get_db()
    body.pop("id", None)
    if "code" in body and body["code"]:
        body["code"] = body["code"].strip().upper()
    res = await db.coupons.find_one_and_update(
        {"_id": to_object_id(coupon_id)}, {"$set": body}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return serialize(res)


@router.delete("/{coupon_id}", dependencies=[Depends(require_admin)])
async def delete_coupon(coupon_id: str):
    db = get_db()
    await db.coupons.delete_one({"_id": to_object_id(coupon_id)})
    return {"deleted": True}


@router.post("/applicable")
async def applicable_coupons(
    subtotal: float = Body(0, embed=True),
    user: dict = Depends(get_current_user),
):
    """Return every live coupon ranked for this cart subtotal.

    - `applicable` coupons (subtotal meets min_order) carry their computed
      `discount`, sorted best-saving first — the client auto-applies `best_code`.
    - `locked` coupons carry `needed_more` (how much more to add to unlock),
      shown greyed out (Flipkart/Amazon style).
    """
    db = get_db()
    first = await is_first_order(db, user["id"])
    docs = await db.coupons.find({"active": True}).to_list(length=500)
    offers = []
    for c in docs:
        if not _in_window(c):
            continue
        # First-order-only coupons never enter the pool for a returning user, so
        # the auto-apply never picks one they can't actually redeem.
        if c.get("first_order_only") and not first:
            continue
        min_order = c.get("min_order", 0) or 0
        applicable = subtotal >= min_order
        discount = coupon_discount(c, subtotal) if applicable else 0.0
        offers.append({
            "code": c["code"],
            "type": c.get("type", "percent"),
            "value": c.get("value", 0),
            "min_order": min_order,
            "max_discount": c.get("max_discount", 0),
            "description": c.get("description", ""),
            "first_order_only": bool(c.get("first_order_only")),
            "free_shipping": bool(c.get("free_shipping")),
            # A free-delivery coupon saves real money without moving `discount`,
            # so it counts as usable too — otherwise auto-apply would skip it.
            "applicable": applicable and (discount > 0 or bool(c.get("free_shipping"))),
            "discount": discount,
            "needed_more": round(max(0.0, min_order - subtotal), 2) if not applicable else 0.0,
        })

    # Best usable saving first; then locked ones by how close they are to unlocking.
    # Best usable saving first; a free-delivery coupon outranks nothing but the
    # locked ones, and locked offers trail by how close they are to unlocking.
    offers.sort(
        key=lambda o: (not o["applicable"], -o["discount"], not o["free_shipping"], o["needed_more"])
    )
    best = next((o["code"] for o in offers if o["applicable"]), None)
    best_discount = next((o["discount"] for o in offers if o["applicable"]), 0.0)
    return {"offers": offers, "best_code": best, "best_discount": best_discount}


@router.post("/validate")
async def validate_coupon(
    code: str = Body(..., embed=True),
    subtotal: float = Body(0, embed=True),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    coupon = await get_coupon(db, code, user["id"])
    if not coupon:
        # Distinguish a first-order-only coupon rejected for a returning user, so
        # the app can show a helpful message instead of a generic "invalid".
        raw = await db.coupons.find_one({"code": code.strip().upper(), "active": True})
        if raw and _in_window(raw) and raw.get("first_order_only"):
            return {"valid": False, "discount": 0,
                    "message": "This coupon is only valid on your first order"}
        return {"valid": False, "discount": 0, "message": "Invalid or expired coupon"}
    if subtotal < coupon.get("min_order", 0):
        return {
            "valid": False,
            "discount": 0,
            "message": f"Minimum order ₹{coupon['min_order']:.0f} required",
        }
    discount = coupon_discount(coupon, subtotal)
    msg = f"You saved ₹{discount:.0f}!" if discount > 0 else "Coupon applied!"
    if coupon.get("free_shipping"):
        msg = f"Free Shipping + ₹{discount:.0f} off!" if discount > 0 else "Free Shipping applied!"
    return {
        "valid": True,
        "discount": discount,
        "code": coupon["code"],
        "free_shipping": bool(coupon.get("free_shipping")),
        "message": msg,
    }
