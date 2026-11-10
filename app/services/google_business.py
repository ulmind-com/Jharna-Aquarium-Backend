"""Google Business Profile review sync.

Pulls every review for the shop's Google location and upserts them into the
`google_reviews` collection, so the storefront can show all of them (not the
5 the public Places API caps at).

Auth is an offline OAuth refresh token for a Google account that manages the
location — see docs/google-business-reviews.md for how to mint one.

Note: the Business Profile API returns the reviewer, star rating, comment and
the owner's reply. It does NOT return photos attached to a review; any photos
already stored on a review are preserved on sync.
"""

import os
from datetime import datetime, timezone
from typing import Any

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
# Reviews still live on the v4 endpoint; the newer APIs do not serve them.
REVIEWS_URL = "https://mybusiness.googleapis.com/v4/accounts/{account}/locations/{location}/reviews"

STAR_WORDS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


class GoogleBusinessNotConfigured(RuntimeError):
    """Raised when the OAuth credentials for the sync are missing."""


def _config() -> dict[str, str]:
    cfg = {
        "client_id": os.getenv("GOOGLE_GBP_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_GBP_CLIENT_SECRET", ""),
        "refresh_token": os.getenv("GOOGLE_GBP_REFRESH_TOKEN", ""),
        "account": os.getenv("GOOGLE_GBP_ACCOUNT_ID", ""),
        "location": os.getenv("GOOGLE_GBP_LOCATION_ID", ""),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise GoogleBusinessNotConfigured(
            "Missing env vars: " + ", ".join(f"GOOGLE_GBP_{k.upper()}" for k in missing)
        )
    return cfg


def _access_token(cfg: dict[str, str]) -> str:
    res = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "refresh_token": cfg["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    res.raise_for_status()
    return res.json()["access_token"]


def fetch_reviews() -> list[dict[str, Any]]:
    """Every review on the location, following pagination to the end."""
    cfg = _config()
    token = _access_token(cfg)
    url = REVIEWS_URL.format(account=cfg["account"], location=cfg["location"])
    headers = {"Authorization": f"Bearer {token}"}

    out: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"pageSize": 50, "orderBy": "updateTime desc"}
        if page_token:
            params["pageToken"] = page_token
        res = requests.get(url, headers=headers, params=params, timeout=30)
        res.raise_for_status()
        body = res.json()
        out.extend(body.get("reviews", []))
        page_token = body.get("nextPageToken")
        if not page_token:
            return out


def normalise(review: dict[str, Any]) -> dict[str, Any]:
    """Google's review shape -> the document we store."""
    reviewer = review.get("reviewer") or {}
    reply = review.get("reviewReply") or {}
    rating = review.get("starRating")
    return {
        "review_id": review.get("reviewId") or review.get("name", ""),
        "author": reviewer.get("displayName") or "Google user",
        "author_photo": reviewer.get("profilePhotoUrl"),
        "rating": STAR_WORDS.get(str(rating).upper(), 0),
        "text": (review.get("comment") or "").strip(),
        "created_at": review.get("createTime"),
        "updated_at": review.get("updateTime"),
        "owner_reply": (reply.get("comment") or "").strip() or None,
        "source": "google",
    }


async def sync_reviews(db) -> dict[str, int]:
    """Pull from Google and upsert. Existing photos on a review are kept."""
    reviews = [normalise(r) for r in fetch_reviews()]
    created = updated = 0
    for doc in reviews:
        if not doc["review_id"]:
            continue
        existing = await db.google_reviews.find_one({"review_id": doc["review_id"]})
        if existing:
            await db.google_reviews.update_one({"_id": existing["_id"]}, {"$set": doc})
            updated += 1
        else:
            await db.google_reviews.insert_one({**doc, "photos": []})
            created += 1

    await db.google_reviews_meta.update_one(
        {"_id": "sync"},
        {"$set": {"last_synced_at": datetime.now(timezone.utc).isoformat(), "total": len(reviews)}},
        upsert=True,
    )
    return {"fetched": len(reviews), "created": created, "updated": updated}
