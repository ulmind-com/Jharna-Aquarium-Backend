"""Seed the Google reviews that were captured with their photos.

The Business Profile API returns text/rating/author for every review but not the
photos attached to them, so these three (harvested from the public listing) keep
their image sets. `sync_reviews` preserves photos on existing documents, so the
next API sync fills in the other reviews without wiping these.

Run:  python scripts/seed_google_reviews.py
"""

import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

REVIEWS = [
    {
        "review_id": "seed-sumit-banerjee",
        "author": "Sumit Banerjee",
        "author_photo": None,
        "rating": 4,
        "text": (
            "Very good quality wools and very warm and gentle behaviour is there, I would "
            "suggest all of you If you have time, definitely come here, I promise you won't "
            "be disappointed."
        ),
        "created_at": "2026-05-06T00:00:00Z",
        "updated_at": "2026-05-06T00:00:00Z",
        "owner_reply": "Thank you Sir For your Valuable feedback 🙏😇",
        "source": "google",
        "photos": [
            "/assets/reviews/sumit-1.jpg",
            "/assets/reviews/sumit-2.jpg",
            "/assets/reviews/sumit-3.jpg",
            "/assets/reviews/sumit-4.jpg",
        ],
    },
    {
        "review_id": "seed-nafisa-nasim",
        "author": "Nafisa Nasim",
        "author_photo": None,
        "rating": 5,
        "text": "Highly recommended for yarns, best offers and absolutely amazing service",
        "created_at": "2026-03-06T00:00:00Z",
        "updated_at": "2026-03-06T00:00:00Z",
        "owner_reply": None,
        "source": "google",
        "photos": [
            "/assets/reviews/nafisa-1.jpg",
            "/assets/reviews/nafisa-2.jpg",
            "/assets/reviews/nafisa-3.jpg",
        ],
    },
    {
        "review_id": "seed-bidisha-kundu",
        "author": "Bidisha Kundu",
        "author_photo": None,
        "rating": 5,
        "text": (
            "Lots of variety available and the owner is very friendly as I am a beginner at "
            "crochetting he helped me pick the items I shall need Really happy with the "
            "experience. Definitely gonna purchase again."
        ),
        "created_at": "2025-08-06T00:00:00Z",
        "updated_at": "2025-08-06T00:00:00Z",
        "owner_reply": "Thank you mam for your valuable feedback 😇🙏",
        "source": "google",
        "photos": [
            "/assets/reviews/bidisha-1.jpg",
            "/assets/reviews/bidisha-2.jpg",
            "/assets/reviews/bidisha-3.jpg",
            "/assets/reviews/bidisha-4.jpg",
        ],
    },
]


async def main() -> None:
    client = AsyncIOMotorClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("MONGO_DB", "royal_wool")]
    for doc in REVIEWS:
        await db.google_reviews.update_one(
            {"review_id": doc["review_id"]}, {"$set": doc}, upsert=True
        )
        print(f"seeded {doc['author']} ({len(doc['photos'])} photos)")
    print("total in collection:", await db.google_reviews.count_documents({}))
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
