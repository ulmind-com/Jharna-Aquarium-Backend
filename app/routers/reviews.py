from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.mongodb import get_db
from app.deps import get_current_user, get_optional_user, require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/reviews", tags=["reviews"])

# What a customer can say they liked about the product (left demo screen).
ALLOWED_TAGS = ["Quality", "Material", "Fit", "Design"]


class ReviewIn(BaseModel):
    product_id: str
    rating: float = Field(ge=1, le=5)
    title: str = ""
    text: str = ""
    photos: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class VoteIn(BaseModel):
    helpful: bool


async def _has_delivered(db, user_id: str, product_id: str) -> bool:
    order = await db.orders.find_one(
        {"user_id": user_id, "status": "delivered", "items.product_id": product_id}
    )
    return order is not None


async def _recompute(db, product_id: str) -> dict:
    reviews = await db.reviews.find({"product_id": product_id, "is_hidden": {"$ne": True}}).to_list(length=5000)
    count = len(reviews)
    avg = round(sum(r["rating"] for r in reviews) / count, 1) if count else 0
    await db.products.update_one(
        {"_id": to_object_id(product_id)},
        {"$set": {"rating": avg, "review_count": count}},
    )
    return {"rating": avg, "review_count": count}


def _public(doc: dict, viewer_id: str | None = None) -> dict:
    """Serialize a review for public consumption (hide voter identities).

    If viewer_id is given, expose that viewer's own vote as `my_vote` so the
    client can render the filled thumb after a reload.
    """
    helpful_by = doc.get("helpful_by", []) or []
    unhelpful_by = doc.get("unhelpful_by", []) or []
    out = serialize(doc)
    out.pop("helpful_by", None)
    out.pop("unhelpful_by", None)
    out.setdefault("title", "")
    out.setdefault("photos", [])
    out.setdefault("tags", [])
    out.setdefault("helpful_count", 0)
    out.setdefault("helpful_count", 0)
    out.setdefault("unhelpful_count", 0)
    out.setdefault("is_hidden", False)
    out["my_vote"] = (
        "up" if viewer_id and viewer_id in helpful_by
        else "down" if viewer_id and viewer_id in unhelpful_by
        else None
    )
    return out


@router.get("")
async def list_reviews(
    product_id: str,
    rating: int | None = None,
    viewer: dict | None = Depends(get_optional_user),
):
    db = get_db()
    query: dict = {"product_id": product_id, "is_hidden": {"$ne": True}}
    if rating in (1, 2, 3, 4, 5):
        # Ratings are stored as whole stars; bucket defensively.
        query["rating"] = {"$gte": rating, "$lt": rating + 1}
    docs = (
        await db.reviews.find(query)
        .sort("created_at", -1)
        .to_list(length=200)
    )
    viewer_id = viewer["id"] if viewer else None
    return [_public(d, viewer_id) for d in docs]


@router.get("/highlights")
async def review_highlights(limit: int = 30):
    db = get_db()
    docs = await db.reviews.find({"rating": {"$gte": 4}, "is_hidden": {"$ne": True}}).sort("created_at", -1).to_list(length=limit)
    return [_public(d) for d in docs]


@router.get("/summary")
async def review_summary(product_id: str):
    db = get_db()
    docs = await db.reviews.find({"product_id": product_id, "is_hidden": {"$ne": True}}).to_list(length=5000)
    count = len(docs)
    avg = round(sum(d["rating"] for d in docs) / count, 1) if count else 0
    breakdown = {str(s): 0 for s in range(1, 6)}
    for d in docs:
        star = max(1, min(5, int(round(d["rating"]))))
        breakdown[str(star)] += 1
    return {"count": count, "average": avg, "breakdown": breakdown}


@router.get("/can-review")
async def can_review(product_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    already = await db.reviews.find_one({"product_id": product_id, "user_id": user["id"]})
    delivered = await _has_delivered(db, user["id"], product_id)
    return {"can": delivered and not already, "delivered": delivered, "already": bool(already)}


@router.post("")
async def add_review(body: ReviewIn, user: dict = Depends(get_current_user)):
    db = get_db()
    if not await _has_delivered(db, user["id"], body.product_id):
        raise HTTPException(status_code=403, detail="You can review only after your order is delivered")
    if await db.reviews.find_one({"product_id": body.product_id, "user_id": user["id"]}):
        raise HTTPException(status_code=409, detail="You already reviewed this product")
    tags = [t for t in body.tags if t in ALLOWED_TAGS]
    doc = {
        "product_id": body.product_id,
        "user_id": user["id"],
        "user_name": user.get("name", "User"),
        "rating": body.rating,
        "title": body.title.strip()[:120],
        "text": body.text.strip(),
        "photos": body.photos[:6],
        "tags": tags,
        "helpful_by": [],
        "unhelpful_by": [],
        "helpful_count": 0,
        "unhelpful_count": 0,
        "created_at": datetime.now(timezone.utc),
    }
    await db.reviews.insert_one(doc)
    agg = await _recompute(db, body.product_id)
    return {"ok": True, **agg}


class ReviewEdit(BaseModel):
    rating: float | None = Field(default=None, ge=1, le=5)
    title: str | None = None
    text: str | None = None
    photos: list[str] | None = None
    tags: list[str] | None = None


@router.get("/mine")
async def my_reviews(user: dict = Depends(get_current_user)):
    """Everything this customer has written, newest first, with the product
    attached so the account screen can show what was reviewed."""
    db = get_db()
    docs = await db.reviews.find({"user_id": user["id"]}).sort("created_at", -1).to_list(length=200)

    ids = []
    for d in docs:
        try:
            ids.append(to_object_id(d["product_id"]))
        except Exception:
            continue
    products = {}
    if ids:
        async for prod in db.products.find({"_id": {"$in": ids}}):
            images = prod.get("images") or []
            for size in prod.get("sizes") or []:
                if isinstance(size, dict) and size.get("images"):
                    images = size["images"]
                    break
            products[str(prod["_id"])] = {
                "id": str(prod["_id"]),
                "title": prod.get("title", ""),
                "image": images[0] if images else None,
            }

    out = []
    for d in docs:
        item = serialize(d)
        item["product"] = products.get(d["product_id"])
        out.append(item)
    return out


async def _own_review(db, review_id: str, user: dict) -> dict:
    doc = await db.reviews.find_one({"_id": to_object_id(review_id)})
    if not doc or doc.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Review not found")
    return doc


@router.patch("/{review_id}")
async def edit_my_review(review_id: str, body: ReviewEdit, user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _own_review(db, review_id, user)

    updates: dict = {}
    if body.rating is not None:
        updates["rating"] = body.rating
    if body.title is not None:
        updates["title"] = body.title.strip()[:120]
    if body.text is not None:
        updates["text"] = body.text.strip()
    if body.photos is not None:
        updates["photos"] = body.photos[:6]
    if body.tags is not None:
        updates["tags"] = [t for t in body.tags if t in ALLOWED_TAGS]
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    updates["edited_at"] = datetime.now(timezone.utc)
    await db.reviews.update_one({"_id": doc["_id"]}, {"$set": updates})
    # The rating may have moved, so the product's average has to follow.
    await _recompute(db, doc["product_id"])
    fresh = await db.reviews.find_one({"_id": doc["_id"]})
    return serialize(fresh)


@router.delete("/{review_id}")
async def delete_my_review(review_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _own_review(db, review_id, user)
    await db.reviews.delete_one({"_id": doc["_id"]})
    agg = await _recompute(db, doc["product_id"])
    return {"deleted": True, **agg}


@router.post("/{review_id}/vote")
async def vote_review(review_id: str, body: VoteIn, user: dict = Depends(get_current_user)):
    db = get_db()
    oid = to_object_id(review_id)
    doc = await db.reviews.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Review not found")
    uid = user["id"]
    helpful_by = set(doc.get("helpful_by", []))
    unhelpful_by = set(doc.get("unhelpful_by", []))
    # A user counts once; a new vote replaces their previous one.
    helpful_by.discard(uid)
    unhelpful_by.discard(uid)
    if body.helpful:
        helpful_by.add(uid)
    else:
        unhelpful_by.add(uid)
    await db.reviews.update_one(
        {"_id": oid},
        {"$set": {
            "helpful_by": list(helpful_by),
            "unhelpful_by": list(unhelpful_by),
            "helpful_count": len(helpful_by),
            "unhelpful_count": len(unhelpful_by),
        }},
    )
    return {
        "helpful_count": len(helpful_by),
        "unhelpful_count": len(unhelpful_by),
        "my_vote": "helpful" if body.helpful else "unhelpful",
    }


@router.get("/admin/all", dependencies=[Depends(require_admin)])
async def admin_all_reviews(product_id: str | None = None):
    db = get_db()
    query = {"product_id": product_id} if product_id else {}
    docs = await db.reviews.find(query).sort("created_at", -1).to_list(length=1000)
    # Attach the product title for context in the admin panel.
    titles: dict[str, str] = {}
    out = []
    for d in docs:
        pid = d.get("product_id")
        if pid and pid not in titles:
            prod = await db.products.find_one({"_id": to_object_id(pid)}) if pid else None
            titles[pid] = (prod or {}).get("title", "Unknown product")
        item = _public(d)
        item["product_title"] = titles.get(pid, "Unknown product")
        out.append(item)
    return out


class ReplyIn(BaseModel):
    text: str


@router.patch("/admin/{review_id}/reply", dependencies=[Depends(require_admin)])
async def admin_reply_review(review_id: str, body: ReplyIn):
    db = get_db()
    oid = to_object_id(review_id)
    doc = await db.reviews.find_one_and_update(
        {"_id": oid},
        {"$set": {
            "admin_reply": body.text.strip(),
            "admin_reply_at": datetime.now(timezone.utc),
        }},
        return_document=True
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"ok": True, "admin_reply": doc["admin_reply"], "admin_reply_at": doc["admin_reply_at"]}


class StatusIn(BaseModel):
    is_hidden: bool


@router.patch("/admin/{review_id}/status", dependencies=[Depends(require_admin)])
async def admin_review_status(review_id: str, body: StatusIn):
    db = get_db()
    oid = to_object_id(review_id)
    doc = await db.reviews.find_one_and_update(
        {"_id": oid},
        {"$set": {"is_hidden": body.is_hidden}},
        return_document=True
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Review not found")
    await _recompute(db, doc["product_id"])
    return {"ok": True, "is_hidden": doc["is_hidden"]}
