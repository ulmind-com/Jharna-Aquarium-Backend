"""Second pass over the supply photographs, by eye.

Every gallery was looked at on a contact sheet. The misses were the ones an
article's lead image cannot help with — "Terracotta" leads with a sculpture,
"Self-watering container" with a cartoon, "Wicker" with a basket of apples.
Those are dropped here, and the three subjects Commons does photograph well
are replaced outright.

Run:  .venv/bin/python -m scripts.fix_supply_photos
"""

import asyncio
import urllib.parse

from app.db.mongodb import connect_to_mongo, get_db

FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/"


def file_url(name: str) -> str:
    return FILE + urllib.parse.quote(name.replace(" ", "_")) + "?width=1200"


# Replace the gallery outright — Commons has the real thing for these.
REPLACE: dict[str, list[str]] = {
    "Red Soil — 5 kg": [
        "Red soil - লাল মাটি - DSC00638.jpg",
        "Red soil - লাল মাটি - DSC00636.jpg",
        "Red soil of a ploughed field - geograph.org.uk - 6515863.jpg",
    ],
    "River Sand — 5 kg": [
        "Heap of Fine Construction Sand.jpg",
        "A heap of sharp sand.jpg",
        "A huge heap of sand - geograph.org.uk - 5046619.jpg",
    ],
    "Wooden Plant Stand": [
        "Variety of potted plants displayed on a wooden plant stand at a garden centre.jpg",
        "JapanHomes 277 Plant-pot of old plank.jpg",
    ],
}

# Drop the leading picture — the article's lead image is not the product.
DROP_FIRST = [
    "Terracotta Pot Set of 3",        # a terracotta bust
    "Self-Watering Pot — 7 inch",     # a line drawing
    "Self-Watering Spikes — Pack of 4",
    "Woven Basket Planter",           # a basket of apples
    "Gardening Gloves",               # a museum case of evening gloves
    "Pressure Sprayer — 2 Litre",     # a tractor-mounted boom sprayer
    "Ceramic Pot Saucer — Set of 3",  # a porcelain teacup and saucer
    "NPK 19:19:19 — 900 g",           # a field being top-dressed
]


async def main() -> None:
    await connect_to_mongo()
    db = get_db()

    for title, files in REPLACE.items():
        urls = [file_url(f) for f in files]
        res = await db.products.update_one({"title": title}, {"$set": {"images": urls}})
        print(f"  replaced {len(urls)} photo(s) on {title}" if res.matched_count else f"  ! {title} not found")

    for title in DROP_FIRST:
        doc = await db.products.find_one({"title": title}, {"images": 1})
        if not doc:
            print(f"  ! {title} not found")
            continue
        images = (doc.get("images") or [])[1:]
        await db.products.update_one({"_id": doc["_id"]}, {"$set": {"images": images}})
        print(f"  {len(images)} photo(s) left on {title}")

    empty = await db.products.count_documents({"images": {"$size": 0}})
    print(f"\n{empty} product(s) now have no photograph — upload one from the admin panel.")


if __name__ == "__main__":
    asyncio.run(main())
