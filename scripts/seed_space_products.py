"""Fill the four "Shop by Space" rooms with real catalogue plants.

The room pages were falling back to the storefront's placeholder grid because
no product pointed at them. This files each plant under the rooms it actually
suits, through `extra_category_ids`, so its home category (Indoor / Outdoor)
is left alone and one plant can serve two rooms — Snake Plant belongs in the
bedroom and on a desk alike.

Idempotent: the room ids are rewritten on every run, so re-running after an
edit in the admin panel re-states this mapping and nothing is duplicated.
Admin can add or remove rooms per product from the product editor afterwards.

Run:  .venv/bin/python scripts/seed_space_products.py
"""

import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

# Product titles per room slug. Titles are matched case-insensitively and a
# title missing from the catalogue is simply reported, never created.
ROOM_PLANTS: dict[str, list[str]] = {
    "living-room": [
        "Monstera Deliciosa", "Monstera Adansonii Plant", "Areca Palm", "Rubber Plant",
        "Fiddle Leaf Fig", "Kentia Palm", "Bamboo Palm", "Dracaena Marginata",
        "Schefflera (Umbrella Plant)", "Calathea", "Alocasia (Elephant Ear)",
        "Ficus Benjamina", "Anthurium Red Plant", "Peace Lily Plant", "Bromeliad",
        "Dieffenbachia (Dumb Cane)", "Begonia Rex", "Staghorn Fern",
    ],
    "bedroom": [
        "Snake Plant", "Snake Plant (Sansevieria)", "Peace Lily", "Aloe Vera",
        "Aloe Vera Plant", "Spider Plant", "Chlorophytum Spider Plant",
        "Aglaonema (Chinese Evergreen)", "Boston Fern", "English Ivy",
        "Maranta (Prayer Plant)", "Orchid (Phalaenopsis)", "Hoya (Wax Plant)",
        "Bird's Nest Fern", "Philodendron", "Asparagus Fern",
    ],
    "balcony": [
        "Hibiscus", "Rose", "Jasmine", "Jasmine Mogra Plant", "Bougainvillea",
        "Marigold", "Petunia", "Moss Rose (Portulaca)", "Adenium (Desert Rose)",
        "Plumeria (Frangipani)", "Croton", "Periwinkle (Vinca)", "Canna Lily",
        "Chrysanthemum", "Lavender", "Bird of Paradise", "Cycas Palm (Sago Palm)",
        "Sunflower", "Oleander", "Gardenia", "Hydrangea",
    ],
    "office": [
        "ZZ Plant", "ZZ Plant (Zamioculcas)", "Money Plant (Pothos)",
        "Money Plant Golden", "Money Plant Variegated", "Lucky Bamboo",
        "Lucky Bamboo 2 Layer", "Cast Iron Plant", "Peperomia",
        "Peperomia Green Creeper Plant", "Echeveria Succulent",
        "Haworthia Zebra Plant", "Pilea (Chinese Money Plant)",
        "Air Plant (Tillandsia)", "Jade Plant", "Jade Mini Plant",
        "Fittonia (Nerve Plant)", "Fittonia Green Plant (Nerve Plant)",
        "Syngonium (Arrowhead Plant)", "Syngonium Pink Plant", "Kalanchoe",
        "Oxalis (Purple Shamrock)",
    ],
}


async def main() -> None:
    db = AsyncIOMotorClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))[
        os.getenv("MONGO_DB", "nursery_ecommerce")
    ]

    rooms = {}
    for slug in ROOM_PLANTS:
        cat = await db.categories.find_one({"slug": slug})
        if not cat:
            raise SystemExit(f"category '{slug}' missing — run scripts/seed_spaces.py first")
        rooms[slug] = str(cat["_id"])
    room_ids = set(rooms.values())

    # title -> the room ids it should carry
    wanted: dict[str, set[str]] = {}
    missing: list[str] = []
    for slug, titles in ROOM_PLANTS.items():
        for title in titles:
            wanted.setdefault(title.lower(), set()).add(rooms[slug])

    updated = 0
    for title_lc, ids in wanted.items():
        docs = await db.products.find({"title": {"$regex": f"^{_escape(title_lc)}$", "$options": "i"}}).to_list(10)
        if not docs:
            missing.append(title_lc)
            continue
        for doc in docs:
            # keep any non-room shelf the admin panel may have set
            keep = {i for i in (doc.get("extra_category_ids") or []) if i not in room_ids}
            await db.products.update_one(
                {"_id": doc["_id"]}, {"$set": {"extra_category_ids": sorted(keep | ids)}}
            )
            updated += 1

    print(f"updated {updated} product(s)")
    for slug, cid in rooms.items():
        count = await db.products.count_documents(
            {"$or": [{"category_id": cid}, {"extra_category_ids": cid}]}
        )
        print(f"  {slug:<12} {count} product(s)")
    if missing:
        print("\nnot found in catalogue (skipped): " + ", ".join(sorted(missing)))


def _escape(value: str) -> str:
    import re
    return re.escape(value)


if __name__ == "__main__":
    asyncio.run(main())
