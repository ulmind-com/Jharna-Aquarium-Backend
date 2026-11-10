"""Replace the category tree with the six client-approved yarn ranges.

Idempotent: categories are upserted by slug, so re-running keeps the same ids
(and therefore keeps product links intact). Any category outside the six is
removed, and every product pointing at a removed category is remapped onto the
closest surviving range so nothing is orphaned.

Run:  python scripts/seed_royal_categories.py
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

# Client-approved ranges, in nav order. Flat — no sub-categories.
CATEGORIES = [
    {
        "name": "Acrylic Rainbow",
        "slug": "acrylic-rainbow",
        "blurb": "One ball, seven gradients. Self-striping without changing yarn.",
    },
    {
        "name": "MultiTone Acrylic",
        "slug": "multitone-acrylic",
        "blurb": "Two shades plied together, so flat stitches read with depth.",
    },
    {
        "name": "CloudCotton",
        "slug": "cloudcotton",
        "blurb": "Matte, brushed cotton with almost no sheen — built for baby blankets.",
    },
    {
        "name": "Aroma Cotton",
        "slug": "aroma-cotton",
        "blurb": "Micro-encapsulated scent in the fibre that survives the first few washes.",
    },
    {
        "name": "TwistTone Cotton",
        "slug": "twisttone-cotton",
        "blurb": "A visible high-twist ply that gives crochet stitches a crisp edge.",
    },
    {
        "name": "Exclusive Acrylic",
        "slug": "exclusive-acrylic",
        "blurb": "Limited dye lots, numbered. When a colour is gone, it is gone.",
    },
]

# Where orphaned products land, by keyword in the product title. First match wins.
FALLBACK_SLUG = "exclusive-acrylic"
TITLE_RULES = [
    ("cotton", "cloudcotton"),
    ("acrylic", "exclusive-acrylic"),
]


async def main() -> None:
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "royal_wool")
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    print(f"database: {db_name}")

    old = await db.categories.find().to_list(length=1000)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(os.path.dirname(__file__), f"categories-backup-{stamp}.json")
    with open(backup, "w") as fh:
        json.dump([{**d, "_id": str(d["_id"])} for d in old], fh, indent=2, default=str)
    print(f"backed up {len(old)} existing categories -> {backup}")

    # 1. Upsert the six ranges, keeping ids stable across runs.
    slug_to_id: dict[str, str] = {}
    for order, cat in enumerate(CATEGORIES, start=1):
        doc = {
            "name": cat["name"],
            "slug": cat["slug"],
            "parent_id": None,
            "blurb": cat["blurb"],
            "order": order,
        }
        existing = await db.categories.find_one({"slug": cat["slug"]})
        if existing:
            await db.categories.update_one({"_id": existing["_id"]}, {"$set": doc})
            cat_id = existing["_id"]
        else:
            # image / image_scale stay unset so admin can upload artwork later.
            res = await db.categories.insert_one({**doc, "image": None, "image_scale": None})
            cat_id = res.inserted_id
        slug_to_id[cat["slug"]] = str(cat_id)
        print(f"  {order}. {cat['name']} ({cat['slug']}) -> {cat_id}")

    keep_ids = set(slug_to_id.values())

    # 2. Remap every product that pointed at a category we are about to drop.
    moved = 0
    async for product in db.products.find({}):
        current = str(product.get("category_id") or "")
        if current in keep_ids:
            continue
        title = (product.get("title") or "").lower()
        target = FALLBACK_SLUG
        for keyword, slug in TITLE_RULES:
            if keyword in title:
                target = slug
                break
        await db.products.update_one(
            {"_id": product["_id"]}, {"$set": {"category_id": slug_to_id[target]}}
        )
        moved += 1
        print(f"  product '{product.get('title')}' -> {target}")
    print(f"remapped {moved} products")

    # 3. Drop everything that is not one of the six.
    res = await db.categories.delete_many({"slug": {"$nin": [c["slug"] for c in CATEGORIES]}})
    print(f"removed {res.deleted_count} old categories")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
