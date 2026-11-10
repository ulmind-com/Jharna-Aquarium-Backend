"""Seed the DB with an admin user, categories/sub-categories and demo products.

Run:  cd backend && python -m scripts.seed
"""
import asyncio
from datetime import datetime, timezone

from app.core.security import hash_password
from app.db.mongodb import connect_to_mongo, get_db

ADMIN = {"name": "Admin", "email": "admin@shop.com", "password": "admin123"}


async def main():
    await connect_to_mongo()
    db = get_db()

    # Admin
    if not await db.users.find_one({"email": ADMIN["email"]}):
        await db.users.insert_one(
            {
                "name": ADMIN["name"],
                "email": ADMIN["email"],
                "phone": None,
                "password": hash_password(ADMIN["password"]),
                "role": "admin",
                "addresses": [],
                "fcm_tokens": [],
                "created_at": datetime.now(timezone.utc),
            }
        )
        print(f"Admin created -> {ADMIN['email']} / {ADMIN['password']}")

    # Categories (top-level + sub)
    async def upsert_cat(name, slug, parent_id=None, order=0):
        existing = await db.categories.find_one({"slug": slug})
        if existing:
            return existing["_id"]
        res = await db.categories.insert_one(
            {"name": name, "slug": slug, "parent_id": parent_id,
             "image": None, "order": order}
        )
        return res.inserted_id

    mens = await upsert_cat("Mens", "mens", order=0)
    womens = await upsert_cat("Womens", "womens", order=1)
    await upsert_cat("Jeans", "mens-jeans", str(mens), 0)
    await upsert_cat("Shirts", "mens-shirts", str(mens), 1)
    lehenga = await upsert_cat("Lehenga", "womens-lehenga", str(womens), 0)
    await upsert_cat("Sarees", "womens-sarees", str(womens), 1)

    # Demo products
    if await db.products.count_documents({}) == 0:
        await db.products.insert_many(
            [
                {
                    "title": "Men's sneaker", "description": "Crafted from supple, "
                    "high-quality leather.", "brand": "New Balance",
                    "category_id": str(mens), "price": 105.99, "mrp": 260.0,
                    "images": [], "colors": ["orange", "black", "blue"],
                    "sizes": ["8", "9", "10"], "variants": [],
                    "is_active": True, "rating": 4.8, "review_count": 1500,
                    "sold_count": 35000, "created_at": datetime.now(timezone.utc),
                },
                {
                    "title": "Cotton T-Shirt", "description": "Soft cotton tee.",
                    "brand": "Levi's", "category_id": str(mens), "price": 89.0,
                    "mrp": 120.0, "images": [], "colors": ["black"],
                    "sizes": ["M", "L"], "variants": [], "is_active": True,
                    "rating": 4.5, "review_count": 320, "sold_count": 900,
                    "created_at": datetime.now(timezone.utc),
                },
                {
                    "title": "Bridal Lehenga", "description": "Hand-embroidered "
                    "bridal lehenga.", "brand": "Manish Malhotra",
                    "category_id": str(lehenga), "price": 1299.0, "mrp": 2499.0,
                    "images": [], "colors": ["red", "gold"], "sizes": ["S", "M", "L"],
                    "variants": [], "is_active": True, "rating": 5.0,
                    "review_count": 210, "sold_count": 400,
                    "created_at": datetime.now(timezone.utc),
                },
            ]
        )
        print("Demo products inserted")

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
