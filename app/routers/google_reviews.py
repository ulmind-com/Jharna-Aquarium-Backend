from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize
from app.services.google_business import GoogleBusinessNotConfigured, sync_reviews

router = APIRouter(prefix="/google-reviews", tags=["google-reviews"])


@router.get("")
async def list_google_reviews(
    limit: int = Query(default=24, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    with_photos: bool = Query(default=False),
):
    """Public feed of the shop's Google reviews, newest first."""
    db = get_db()
    query: dict = {"text": {"$ne": ""}}
    if with_photos:
        query["photos.0"] = {"$exists": True}
    docs = (
        await db.google_reviews.find(query)
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )
    total = await db.google_reviews.count_documents(query)
    return {"items": [serialize(d) for d in docs], "total": total}


@router.get("/summary")
async def google_review_summary():
    """Count, average and star breakdown across every synced Google review."""
    db = get_db()
    docs = await db.google_reviews.find({}, {"rating": 1}).to_list(length=5000)
    ratings = [d.get("rating", 0) for d in docs if d.get("rating")]
    breakdown = {str(s): sum(1 for r in ratings if r == s) for s in range(1, 6)}
    meta = await db.google_reviews_meta.find_one({"_id": "sync"}) or {}
    return {
        "count": len(ratings),
        "average": round(sum(ratings) / len(ratings), 2) if ratings else 0,
        "breakdown": breakdown,
        "last_synced_at": meta.get("last_synced_at"),
    }


@router.post("/sync", dependencies=[Depends(require_admin)])
async def trigger_sync():
    """Pull the latest reviews from Google Business Profile."""
    db = get_db()
    try:
        return await sync_reviews(db)
    except GoogleBusinessNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # network / auth / quota
        raise HTTPException(status_code=502, detail=f"Google sync failed: {exc}")
