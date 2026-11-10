"""Human-handoff support tickets.

The chat transcript itself is never persisted — it lives in the customer's
browser and is wiped the moment their order is delivered (see
`close_for_order`). What *does* need to outlive the conversation is a
"talk to a human" request, because a person in the admin panel has to answer
it. That's all this module stores: one ticket per handoff, carrying enough
context (which order, which plants, the last few lines said) for the team to
pick up the thread without the customer repeating themselves.
"""
from datetime import datetime, timezone

from app.models.common import serialize, to_object_id

COLLECTION = "support_tickets"

OPEN = "open"
CLOSED = "closed"


def _now():
    return datetime.now(timezone.utc)


def short_id(oid) -> str:
    return str(oid)[-6:].upper()


async def create_ticket(
    db,
    user: dict,
    *,
    order: dict | None = None,
    product: dict | None = None,
    topic: str = "General help",
    message: str = "",
    transcript: list[dict] | None = None,
) -> dict:
    """Open a handoff ticket. Re-uses the customer's existing open ticket for
    the same order so a double-tap doesn't spam the admin queue."""
    order_id = str(order["_id"]) if order else None
    existing = await db[COLLECTION].find_one(
        {"user_id": user["id"], "order_id": order_id, "status": OPEN}
    )

    items = [
        {
            "product_id": str(it.get("product_id") or ""),
            "title": it.get("title"),
            "image": it.get("image"),
            "qty": it.get("qty"),
            "size_variant": it.get("size_variant"),
        }
        for it in ((order or {}).get("items") or [])
    ][:6]

    if product and not items:
        items = [{
            "product_id": str(product.get("_id") or product.get("id") or ""),
            "title": product.get("title"),
            "image": (product.get("images") or [None])[0],
            "qty": 1,
        }]

    doc = {
        "user_id": user["id"],
        "user_name": user.get("name") or "Customer",
        "user_email": user.get("email"),
        "user_phone": user.get("phone"),
        "order_id": order_id,
        "order_short": short_id(order["_id"]) if order else None,
        "order_status": (order or {}).get("status"),
        "order_total": (order or {}).get("amount"),
        "product_id": str(product.get("_id") or product.get("id")) if product else None,
        "product_title": product.get("title") if product else None,
        "items": items,
        "topic": topic[:120],
        "message": (message or "")[:1000],
        "transcript": [
            {"role": m.get("role"), "content": str(m.get("content", ""))[:600]}
            for m in (transcript or [])[-8:]
        ],
        "status": OPEN,
        "updated_at": _now(),
    }

    if existing:
        await db[COLLECTION].update_one({"_id": existing["_id"]}, {"$set": doc})
        fresh = await db[COLLECTION].find_one({"_id": existing["_id"]})
        return serialize(fresh)

    doc["created_at"] = _now()
    res = await db[COLLECTION].insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


async def close_for_order(db, order_id: str, reason: str = "Order delivered") -> int:
    """Delivery (or cancellation) ends the conversation — the chat thread is
    dropped on the client and any open ticket for that order is resolved here,
    so the admin queue only ever holds live problems."""
    res = await db[COLLECTION].update_many(
        {"order_id": str(order_id), "status": OPEN},
        {"$set": {"status": CLOSED, "closed_at": _now(), "close_reason": reason, "updated_at": _now()}},
    )
    return res.modified_count


async def list_tickets(db, status: str | None = None, limit: int = 200) -> list[dict]:
    q: dict = {}
    if status in (OPEN, CLOSED):
        q["status"] = status
    docs = await db[COLLECTION].find(q).sort("updated_at", -1).to_list(length=limit)
    return [serialize(d) for d in docs]


async def counts(db) -> dict:
    return {
        "open": await db[COLLECTION].count_documents({"status": OPEN}),
        "closed": await db[COLLECTION].count_documents({"status": CLOSED}),
    }


async def set_status(db, ticket_id: str, status: str, note: str = "") -> dict | None:
    patch = {"status": status, "updated_at": _now()}
    if status == CLOSED:
        patch["closed_at"] = _now()
    if note:
        patch["admin_note"] = note[:1000]
    await db[COLLECTION].update_one({"_id": to_object_id(ticket_id)}, {"$set": patch})
    doc = await db[COLLECTION].find_one({"_id": to_object_id(ticket_id)})
    return serialize(doc) if doc else None


async def delete_ticket(db, ticket_id: str) -> bool:
    res = await db[COLLECTION].delete_one({"_id": to_object_id(ticket_id)})
    return res.deleted_count > 0
