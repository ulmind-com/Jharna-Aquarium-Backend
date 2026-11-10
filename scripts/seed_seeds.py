"""Stock the Seeds department — the catalogue the "Seeds" nav link opens.

Builds the Seeds category and its five sub-categories, then upserts every
packet in `_seed_catalogue` with the photograph `fetch_seed_photos` resolved
for it. Copy, sowing window, germination and harvest windows are the packet's
own; nothing here is placeholder text.

Idempotent: a packet already in the catalogue has only the fields this script
owns refreshed, so pricing or stock edited in the admin panel survives a
re-run. Nothing is deleted.

Run:  .venv/bin/python -m scripts.seed_seeds
"""

import asyncio
from datetime import datetime, timezone

from app.db.mongodb import connect_to_mongo, get_db
from app.models.product import ProductCreate
from scripts._seed_catalogue import GROUPS, SEEDS
from scripts._seed_photos import PHOTOS

PARENT = {"name": "Seeds", "slug": "seeds", "blurb": "Vegetable, flower, herb and fruit seed for the home garden.",
          "image": "/images/category-seeds.png"}

GROUP_BLURB = {
    "vegetable": "Kitchen-garden vegetables, from salad leaves to gourds.",
    "flower": "Bedding and cutting flowers raised from a single packet.",
    "herb": "Culinary and medicinal herbs for the kitchen windowsill.",
    "fruit": "Melons, berries and fruit trees grown on from seed.",
    "microgreen": "Trays and jars of shoots, ready inside a fortnight.",
}

# One photograph per sub-category tile, borrowed from a packet inside it.
GROUP_PHOTO = {
    "vegetable": "Tomato", "flower": "Tagetes erecta", "herb": "Basil",
    "fruit": "Watermelon", "microgreen": "Wheatgrass",
}

CARE = {
    "vegetable": [
        "Sow into a loose, well-drained bed or a pot at least 8 inches deep.",
        "Keep the surface damp — never soaked — until the seedlings are through.",
        "Thin to one strong seedling per station rather than growing them crowded.",
        "Feed a liquid organic fertiliser every fortnight once flowering starts.",
    ],
    "flower": [
        "Press the seed in lightly; most flower seed needs light to germinate.",
        "Water with a fine rose so the seed is not washed out of place.",
        "Move seedlings into full sun as soon as the first true leaves open.",
        "Deadhead spent blooms and the plant will keep flowering for weeks longer.",
    ],
    "herb": [
        "Sow thinly into a free-draining mix — herbs resent a waterlogged pot.",
        "Give at least four hours of direct sun for the oils to build up.",
        "Pinch the growing tip early so the plant bushes out instead of bolting.",
        "Harvest in the morning, taking no more than a third of the plant at once.",
    ],
    "fruit": [
        "Soak the seed overnight in warm water before sowing to soften the coat.",
        "Sow into a deep pot — these put down a tap root before they put on top growth.",
        "Keep warm and lightly moist; germination is slower than with vegetables.",
        "Pot on once before planting out so the root ball is established.",
    ],
    "microgreen": [
        "Spread the seed densely over an inch of damp coco peat in a flat tray.",
        "Cover for the first two days so the seed roots in the dark, then uncover.",
        "Mist twice a day — a microgreen tray must never dry out.",
        "Cut just above the soil line with scissors and use the same day.",
    ],
}

PLANT_TYPE = {"microgreen": "Indoor", "herb": "Indoor/Outdoor"}
DIFFICULTY = {"fruit": "Moderate", "microgreen": "Easy"}
HARDER = {"Rosemary Seeds", "Parsley Seeds", "Celery Seeds", "Gerbera Seeds", "Carnation Seeds",
          "Strawberry Seeds", "Lupin Seeds", "Larkspur Seeds"}
BESTSELLERS = {
    "Tomato Seeds (Hybrid)", "Green Chilli Seeds", "Okra Seeds (Lady Finger)", "Coriander Seeds (Dhania)",
    "Spinach Seeds (Palak)", "Marigold Seeds (African)", "Sunflower Seeds (Dwarf)", "Tulsi Seeds (Holy Basil)",
    "Sweet Basil Seeds", "Wheatgrass Seeds (Microgreens)", "Zinnia Seeds (Mixed)", "Fenugreek Seeds (Methi)",
}
FEATURED = {"Tomato Seeds (Hybrid)", "Marigold Seeds (African)", "Sweet Basil Seeds", "Watermelon Seeds",
            "Broccoli Microgreens Seeds"}


def build(row: tuple, category_id: str) -> dict:
    name, article, group, price, germ, harvest, season, sun, phrase = row
    group_name = GROUPS[group][0]
    harvest_line = (
        f"ready to cut in {harvest} days"
        if group == "microgreen"
        else f"first harvest about {harvest} days after sowing"
    )
    description = (
        f"{phrase}. Sow {season.replace('-', ' to ')} in {sun.lower()}; the seed breaks ground in "
        f"{germ} days and the {harvest_line}. Packed for the current season and tested for "
        f"germination before it leaves the nursery — each packet carries sowing, spacing and "
        f"watering instructions on the back."
    )
    return ProductCreate(
        title=name,
        short_description=f"{phrase} — germinates in {germ} days.",
        description=description,
        tags=["seeds", group_name.lower(), "kitchen garden", sun.lower(),
              *(["open pollinated"] if group in ("herb", "flower") else [])],
        category_id=category_id,
        mrp=round(price * 1.6 / 10) * 10 - 1,
        price=price,
        # Seed is zero-rated under GST in India.
        cgst=0.0, sgst=0.0, igst=0.0,
        shipping_weight=50,
        images=[PHOTOS[article]],
        plant_spec={
            "plant_type": PLANT_TYPE.get(group, "Outdoor"),
            "sunlight": sun,
            "watering": "Daily" if group == "microgreen" else "Alternate Days",
            "difficulty_level": "Moderate" if name in HARDER else DIFFICULTY.get(group, "Easy"),
            "season": season,
            "soil_type": "Coco Peat Tray" if group == "microgreen" else "Well-drained",
            "growth_rate": "Fast" if group in ("microgreen", "vegetable") else "Medium",
            "flowering": group == "flower",
            "medicinal": group == "herb",
            "scientific_name": article,
            "common_names": [name.split(" Seeds")[0]],
        },
        care_tips=CARE[group],
        includes=["Seed packet", "Sowing instructions"],
        warranty="Germination tested — replaced if the packet fails to sprout",
        stock=100,
        rating=4.6 if name in BESTSELLERS else 4.4,
        review_count=96 if name in BESTSELLERS else 28,
        sold_count=520 if name in BESTSELLERS else 85,
        is_active=True,
        is_bestseller=name in BESTSELLERS,
        is_new_arrival=True,
        is_featured=name in FEATURED,
    ).model_dump()


async def upsert_category(db, doc: dict) -> str:
    existing = await db.categories.find_one({"slug": doc["slug"]})
    if existing:
        # leave an image the admin panel has set
        patch = {k: v for k, v in doc.items() if k != "image" or not existing.get("image")}
        await db.categories.update_one({"_id": existing["_id"]}, {"$set": patch})
        return str(existing["_id"])
    return str((await db.categories.insert_one({**doc, "image_scale": None})).inserted_id)


async def main() -> None:
    await connect_to_mongo()
    db = get_db()
    now = datetime.now(timezone.utc)

    parent_id = await upsert_category(db, {**PARENT, "parent_id": None, "order": 20})
    groups: dict[str, str] = {}
    for order, (key, (name, slug)) in enumerate(GROUPS.items(), start=1):
        groups[key] = await upsert_category(db, {
            "name": name, "slug": slug, "blurb": GROUP_BLURB[key],
            "image": PHOTOS[GROUP_PHOTO[key]], "parent_id": parent_id, "order": order,
        })
    print(f"Seeds category -> {parent_id} ({len(groups)} sub-categories)")

    inserted = refreshed = 0
    for row in SEEDS:
        doc = build(row, groups[row[2]])
        existing = await db.products.find_one({"title": doc["title"]})
        if existing:
            owned = {k: doc[k] for k in (
                "description", "short_description", "tags", "category_id", "images",
                "plant_spec", "care_tips", "includes", "warranty", "cgst", "sgst", "igst",
                "is_bestseller", "is_featured",
            )}
            await db.products.update_one({"_id": existing["_id"]}, {"$set": owned})
            refreshed += 1
            continue
        doc["created_at"] = now
        await db.products.insert_one(doc)
        inserted += 1

    print(f"Packets: {inserted} inserted, {refreshed} refreshed.")
    for key, cid in groups.items():
        print(f"  {GROUPS[key][0]:<18} {await db.products.count_documents({'category_id': cid})}")
    print(f"Catalogue now {await db.products.count_documents({})} products.")


if __name__ == "__main__":
    asyncio.run(main())
