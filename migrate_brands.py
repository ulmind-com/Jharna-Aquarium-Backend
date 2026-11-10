import asyncio
import os
import re
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import time

load_dotenv()

def generate_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    return re.sub(r'[\s-]+', '-', slug).strip('-')

async def run():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "royal_wool")
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    
    product_brands = await db.products.distinct("brand")
    inserted = 0
    for b in product_brands:
        if b and str(b).strip():
            slug = generate_slug(str(b))
            existing = await db.brands.find_one({"slug": slug})
            if not existing:
                await db.brands.insert_one({"name": str(b).strip(), "slug": slug, "logo": None})
                inserted += 1
                
    print(f"Migrated {inserted} brands to the brands collection.")
    client.close()

asyncio.run(run())
