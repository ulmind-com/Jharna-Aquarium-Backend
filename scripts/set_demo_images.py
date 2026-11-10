"""Attach product-style images (white bg) to the seeded demo products.

Run: cd backend && python -m scripts.set_demo_images
"""
import asyncio

from app.db.mongodb import connect_to_mongo, get_db

IMAGES = {
    "Men's sneaker": [
        "https://cdn.dummyjson.com/products/images/mens-shoes/Nike%20Air%20Jordan%201%20Red%20And%20Black/1.png",
        "https://cdn.dummyjson.com/products/images/mens-shoes/Nike%20Air%20Jordan%201%20Red%20And%20Black/2.png",
        "https://cdn.dummyjson.com/products/images/mens-shoes/Nike%20Air%20Jordan%201%20Red%20And%20Black/3.png",
    ],
    "Cotton T-Shirt": [
        "https://cdn.dummyjson.com/products/images/mens-shirts/Blue%20&%20Black%20Check%20Shirt/1.png",
        "https://cdn.dummyjson.com/products/images/mens-shirts/Blue%20&%20Black%20Check%20Shirt/2.png",
    ],
    "Bridal Lehenga": [
        "https://cdn.dummyjson.com/products/images/womens-dresses/Red%20Long%20Maxi%20Dress/1.png",
        "https://cdn.dummyjson.com/products/images/womens-dresses/Red%20Long%20Maxi%20Dress/2.png",
    ],
}


async def main():
    await connect_to_mongo()
    db = get_db()
    for title, imgs in IMAGES.items():
        res = await db.products.update_one({"title": title}, {"$set": {"images": imgs}})
        print(f"{title}: {'updated' if res.modified_count else 'no change / not found'}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
