"""Create the "Shop by Space" category tree used by the home page tiles.

Idempotent and non-destructive: the parent and its four sub-categories are
upserted by slug (ids stay stable, so product links survive), and no other
category is touched. Images are left unset — the storefront falls back to its
own /places artwork until admin uploads a picture.

Run:  python scripts/seed_spaces.py
"""

import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

PARENT = {
    "name": "Shop by Space",
    "slug": "shop-by-space",
    "blurb": "Plants picked for the room they live in.",
}

SPACES = [
    {"name": "Living Room", "slug": "living-room", "blurb": "Statement greens for the room guests see first.", "icon": "🛋️"},
    {"name": "Bedroom", "slug": "bedroom", "blurb": "Calm, air-purifying plants for restful corners.", "icon": "🛏️"},
    {"name": "Balcony", "slug": "balcony", "blurb": "Sun-loving picks that thrive outdoors.", "icon": "🌤️"},
    {"name": "Office", "slug": "office", "blurb": "Low-maintenance desk companions.", "icon": "💻"},
]


async def upsert(db, doc: dict) -> str:
    existing = await db.categories.find_one({"slug": doc["slug"]})
    if existing:
        await db.categories.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    res = await db.categories.insert_one({**doc, "image": None, "image_scale": None})
    return str(res.inserted_id)


async def main() -> None:
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "nursery_ecommerce")
    db = AsyncIOMotorClient(uri)[db_name]
    print(f"database: {db_name}")

    parent_id = await upsert(db, {**PARENT, "parent_id": None, "order": 90})
    print(f"  parent: {PARENT['name']} -> {parent_id}")

    for order, space in enumerate(SPACES, start=1):
        space_id = await upsert(db, {**space, "parent_id": parent_id, "order": order})
        count = await db.products.count_documents({"category_id": space_id})
        print(f"    {order}. {space['name']} ({space['slug']}) -> {space_id} — {count} product(s)")

    print("\nDone. Assign products to these sub-categories from the admin panel.")


if __name__ == "__main__":
    asyncio.run(main())
