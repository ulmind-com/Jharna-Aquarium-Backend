"""Migrate to product/settings v2. Run: cd backend && python -m scripts.migrate_v2"""
import asyncio

from app.db.mongodb import connect_to_mongo, get_db
from app.models.settings import Settings, ShopConfig, DeliveryConfig

SHOE = "https://cdn.dummyjson.com/products/images/mens-shoes"


async def main():
    await connect_to_mongo()
    db = get_db()

    # 1) Default settings (shop location + delivery + tax)
    if not await db.settings.find_one({"_id": "config"}):
        s = Settings(
            currency="₹",
            currency_code="INR",
            tax_rate=0.05,
            shop=ShopConfig(name="Clothing Store", address="Kolkata", lat=22.5726, lng=88.3639),
            delivery=DeliveryConfig(free_radius_km=3, per_km_rate=8, base_fee=20,
                                    free_above=1500, max_service_km=40),
        )
        await db.settings.update_one({"_id": "config"}, {"$set": {"_id": "config", **s.model_dump()}}, upsert=True)
        print("settings created")

    # 2) Backfill product fields
    async for p in db.products.find():
        upd = {}
        if "discount_pct" not in p:
            upd["discount_pct"] = 0
        if "discount_on" not in p:
            upd["discount_on"] = "price"
        if "stock" not in p or not p.get("stock"):
            upd["stock"] = 25
        if "low_stock_threshold" not in p:
            upd["low_stock_threshold"] = 5
        if "colors" not in p:
            upd["colors"] = []
        if upd:
            await db.products.update_one({"_id": p["_id"]}, {"$set": upd})

    # 3) Colour variants (with per-colour images) + a demo discount on the sneaker
    sneaker = await db.products.find_one({"title": "Men's sneaker"})
    if sneaker:
        await db.products.update_one(
            {"_id": sneaker["_id"]},
            {"$set": {
                "mrp": 260.0,
                "price": 199.0,
                "discount_pct": 20,
                "discount_on": "price",   # 20% off the needed price
                "colors": [
                    {"name": "Orange", "hex": "#F26A21", "stock": 15, "images": [
                        f"{SHOE}/Nike%20Air%20Jordan%201%20Red%20And%20Black/1.png",
                        f"{SHOE}/Nike%20Air%20Jordan%201%20Red%20And%20Black/2.png",
                        f"{SHOE}/Nike%20Air%20Jordan%201%20Red%20And%20Black/3.png",
                    ]},
                    {"name": "Black", "hex": "#1C1613", "stock": 8, "images": [
                        f"{SHOE}/Puma%20Future%20Rider%20Play%20On/1.png",
                        f"{SHOE}/Puma%20Future%20Rider%20Play%20On/2.png",
                    ]},
                    {"name": "Blue", "hex": "#2F6BFF", "stock": 0, "images": [
                        f"{SHOE}/Sports%20Sneakers%20Off%20White%20Red/1.png",
                    ]},
                ],
            }},
        )
        print("sneaker variants + discount set")

    print("migrate_v2 done")


if __name__ == "__main__":
    asyncio.run(main())
