"""File the plants under a Plants category, and give every plant and seed
packet a gallery instead of a single photograph.

Two things the catalogue was missing:
  * /category/plants had nothing behind it — the plants carried no category at
    all, so the page fell back to a sample grid. Each plant is filed under
    Indoor Plants or Outdoor Plants by its own plant_spec.
  * every product had exactly one image, so the detail page showed a filmstrip
    of one. Commons is asked for more photographs of the same species, and the
    extra ones are appended after the picture already in place.

Idempotent and additive: an existing first image is never replaced, and a
product that already has a gallery is left alone.

Run:  .venv/bin/python -m scripts.seed_plant_shelves
"""

import asyncio
from datetime import datetime, timezone

from app.db.mongodb import connect_to_mongo, get_db
from scripts._commons import product_gallery
from scripts._plant_species import SPECIES

PARENT = {"name": "Plants", "slug": "plants", "blurb": "Indoor greens and hardy outdoor plants, grown at our nursery.",
          "image": "/images/category-plants.png"}
SHELVES = [
    ("Indoor Plants", "indoor-plants", "Low-light survivors and statement foliage for inside the house."),
    ("Outdoor Plants", "outdoor-plants", "Sun-hardy flowering plants for a balcony, terrace or garden."),
]
WANT_IMAGES = 4


async def upsert_category(db, doc: dict) -> str:
    existing = await db.categories.find_one({"slug": doc["slug"]})
    if existing:
        patch = {k: v for k, v in doc.items() if k != "image" or not existing.get("image")}
        await db.categories.update_one({"_id": existing["_id"]}, {"$set": patch})
        return str(existing["_id"])
    return str((await db.categories.insert_one({**doc, "image_scale": None})).inserted_id)


def search_term(doc: dict) -> str | None:
    """What to ask Commons for.

    The botanical name, always — a search on the shop title answers "ZZ Plant"
    with photographs of the band, and "Money Plant" with photographs of money.
    A product the species map does not cover is left with the picture it has.
    """
    title = doc["title"]
    if title in SPECIES:
        return SPECIES[title]
    scientific = ((doc.get("plant_spec") or {}).get("scientific_name") or "").strip()
    return scientific or None


async def main() -> None:
    await connect_to_mongo()
    db = get_db()
    now = datetime.now(timezone.utc)

    # ── 1. shelves for the plants ────────────────────────────────────────────
    parent_id = await upsert_category(db, {**PARENT, "parent_id": None, "order": 10})
    shelves = {}
    for order, (name, slug, blurb) in enumerate(SHELVES, start=1):
        shelves[slug] = await upsert_category(db, {
            "name": name, "slug": slug, "blurb": blurb, "parent_id": parent_id, "order": order,
        })

    # Only products that are not already filed somewhere real get moved, so the
    # seed packets and the supplies keep the category they were seeded into.
    live_ids = {str(c["_id"]) for c in await db.categories.find({}, {"_id": 1}).to_list(500)}
    filed = 0
    async for doc in db.products.find({}, {"title": 1, "category_id": 1, "plant_spec": 1, "images": 1}):
        if doc.get("category_id") in live_ids:
            continue
        kind = ((doc.get("plant_spec") or {}).get("plant_type") or "").lower()
        slug = "outdoor-plants" if kind.startswith("outdoor") else "indoor-plants"
        await db.products.update_one({"_id": doc["_id"]}, {"$set": {"category_id": shelves[slug]}})
        filed += 1
    print(f"Plants: {filed} filed under Indoor/Outdoor Plants")

    # ── 2. galleries ─────────────────────────────────────────────────────────
    added = skipped = 0
    cache: dict[str, list[str]] = {}
    async for doc in db.products.find(
        {"category_id": {"$nin": []}}, {"title": 1, "images": 1, "plant_spec": 1}
    ):
        images = [u for u in (doc.get("images") or []) if u]
        term = search_term(doc)
        if not term:
            continue  # a pot or a tool — its photos come from seed_supplies
        if len(images) >= 2 and doc["title"] not in SPECIES:
            skipped += 1
            continue
        # A plant's gallery is rebuilt from the species name: the first run
        # searched on the shop title and brought back whatever shared it.
        if doc["title"] in SPECIES:
            images = images[:1]
        if term not in cache:
            cache[term] = product_gallery(term, [], WANT_IMAGES, pool=25)
        extra = [u for u in cache[term] if u not in images]
        if not extra:
            continue
        patch: dict = {"images": (images + extra)[:WANT_IMAGES], "updated_at": now}
        if doc["title"] in SPECIES:
            patch["plant_spec.scientific_name"] = SPECIES[doc["title"]]
        await db.products.update_one({"_id": doc["_id"]}, {"$set": patch})
        added += 1
        print(f"  {len(((images + extra)[:WANT_IMAGES]))} {doc['title']}", flush=True)

    print(f"\nGalleries: {added} filled, {skipped} already had one.")


if __name__ == "__main__":
    asyncio.run(main())
