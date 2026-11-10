"""Stock the departments either side of the plants: pots, soil, fertilisers,
tools, watering, pest control and decor.

Those category pages had no products behind them, so the storefront fell back
to a bundled sample grid. This fills each one from `_supplies_catalogue`, with
the photographs `fetch_supply_photos` resolved — three per product, so the
detail page has a filmstrip rather than a single still.

Idempotent: a product already in the catalogue has only the fields this script
owns refreshed, so pricing and stock edited in the admin panel survive.

Run:  .venv/bin/python -m scripts.seed_supplies
"""

import asyncio
from datetime import datetime, timezone

from app.db.mongodb import connect_to_mongo, get_db
from app.models.product import ProductCreate
from scripts._supplies_catalogue import CATEGORIES, SUPPLIES
from scripts._supply_photos import PHOTOS

# GST as it falls in India: 5% on what feeds the soil, 18% on hardware.
GST_5 = {"soil", "fertilisers", "pest-control"}

USE_TIPS = {
    "pots": ["Check the drainage hole is clear before the first watering.",
             "Stand the pot on a saucer indoors so run-off never reaches the floor.",
             "Re-pot one size up when roots start showing at the drainage hole."],
    "soil": ["Moisten the mix before filling so it settles without air pockets.",
             "Leave an inch below the rim for watering.",
             "Top up the pot each season — potting mix settles and compacts."],
    "fertilisers": ["Feed a damp pot, never a dry one, or the roots will scorch.",
                    "Follow the dose on the pack; twice as much is not twice as good.",
                    "Stop feeding through the coldest weeks, when growth pauses."],
    "garden-tools": ["Rinse and dry the blade after use so it does not pit.",
                     "A drop of oil on the pivot keeps a pruner cutting cleanly.",
                     "Store under cover — one monsoon is enough to ruin bare steel."],
    "watering-solutions": ["Water in the early morning so the leaves dry before night.",
                           "Water the soil, not the foliage, unless you are misting on purpose.",
                           "Empty and dry a sprayer before storing it away."],
    "pest-control": ["Spray at dusk — never in direct sun, and never on a wilting plant.",
                     "Treat the underside of the leaf, where most pests actually sit.",
                     "Repeat after a week to catch what hatched since the first spray."],
    "gardening-decor": ["Rinse pebbles before spreading them over damp soil.",
                        "Keep a stand out of standing water so the base lasts.",
                        "Wipe decor pieces down at the end of a dusty season."],
}


def build(row: tuple, group: str, category_id: str) -> dict:
    name, price, _term, _must, blurb = row
    images = PHOTOS.get(name, [])
    label = CATEGORIES[group][0].lower()
    gst = 2.5 if group in GST_5 else 9.0
    return ProductCreate(
        title=name,
        short_description=blurb,
        description=f"{blurb} Part of the {label} range at MyGarden — picked for a "
                    f"home garden, a balcony or a windowsill rather than a farm, and "
                    f"stocked in the sizes a household actually gets through.",
        tags=[label, "garden supplies"],
        category_id=category_id,
        mrp=round(price * 1.45 / 10) * 10 - 1,
        price=price,
        cgst=gst, sgst=gst, igst=gst * 2,
        shipping_weight=800,
        images=images,
        care_tips=USE_TIPS[group],
        warranty="7-day replacement if it arrives damaged",
        stock=60,
        rating=4.5,
        review_count=34,
        sold_count=140,
        is_active=True,
        is_new_arrival=True,
    ).model_dump()


async def upsert_category(db, doc: dict) -> str:
    existing = await db.categories.find_one({"slug": doc["slug"]})
    if existing:
        patch = {k: v for k, v in doc.items() if k != "image" or not existing.get("image")}
        await db.categories.update_one({"_id": existing["_id"]}, {"$set": patch})
        return str(existing["_id"])
    return str((await db.categories.insert_one({**doc, "image_scale": None})).inserted_id)


async def main() -> None:
    await connect_to_mongo()
    db = get_db()
    now = datetime.now(timezone.utc)

    inserted = refreshed = 0
    for order, (group, rows) in enumerate(SUPPLIES.items(), start=30):
        name, blurb, image = CATEGORIES[group]
        category_id = await upsert_category(db, {
            "name": name, "slug": group, "blurb": blurb, "image": image,
            "parent_id": None, "order": order,
        })
        for row in rows:
            doc = build(row, group, category_id)
            existing = await db.products.find_one({"title": doc["title"]})
            if existing:
                owned = {k: doc[k] for k in (
                    "description", "short_description", "tags", "category_id",
                    "care_tips", "warranty", "cgst", "sgst", "igst",
                )}
                # a photo the admin has replaced is left alone
                if not existing.get("images"):
                    owned["images"] = doc["images"]
                await db.products.update_one({"_id": existing["_id"]}, {"$set": owned})
                refreshed += 1
                continue
            doc["created_at"] = now
            await db.products.insert_one(doc)
            inserted += 1
        count = await db.products.count_documents({"category_id": category_id})
        print(f"  {name:<20} {count} product(s)")

    print(f"\nSupplies: {inserted} inserted, {refreshed} refreshed.")
    thin = [n for n, u in PHOTOS.items() if len(u) < 2]
    if thin:
        print(f"{len(thin)} product(s) have fewer than two photos: {', '.join(thin)}")
    print(f"Catalogue now {await db.products.count_documents({})} products.")


if __name__ == "__main__":
    asyncio.run(main())
