import asyncio
import os
import re
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# Yarn Category Data
CATEGORIES = {
    "Animal Fibers": [
        "Merino Wool", "Alpaca", "Cashmere", "Mohair", 
        "Angora", "Silk", "Shetland Wool", "Camel Hair", "Qiviut"
    ],
    "Plant Fibers": [
        "Cotton", "Linen", "Bamboo", "Hemp", "Jute", "Ramie"
    ],
    "Synthetic Fibers": [
        "Acrylic", "Nylon", "Polyester", "Microfiber", "Metallic Yarn"
    ],
    "Blends & Semi-Synthetics": [
        "Rayon", "Sock Yarn Blend", "Wool-Acrylic Blend"
    ]
}

def generate_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug).strip('-')
    return slug

async def seed_categories():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "clothing_ecommerce")
    
    print(f"Connecting to MongoDB at {mongo_uri}, database: {db_name}")
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    
    print("Clearing old categories...")
    delete_result = await db.categories.delete_many({})
    print(f"Deleted {delete_result.deleted_count} old categories.")
    
    total_inserted = 0
    order = 1
    
    for parent_name, children in CATEGORIES.items():
        parent_doc = {
            "name": parent_name,
            "slug": generate_slug(parent_name),
            "parent_id": None,
            "image": None,
            "image_scale": None,
            "order": order
        }
        order += 1
        
        insert_res = await db.categories.insert_one(parent_doc)
        parent_id_str = str(insert_res.inserted_id)
        print(f"Inserted Parent: {parent_name} (ID: {parent_id_str})")
        total_inserted += 1
        
        for child_name in children:
            child_doc = {
                "name": child_name,
                "slug": generate_slug(child_name),
                "parent_id": parent_id_str,
                "image": None,
                "image_scale": None,
                "order": order
            }
            order += 1
            await db.categories.insert_one(child_doc)
            print(f"  -> Inserted Child: {child_name}")
            total_inserted += 1
            
    print(f"\nSuccess! Inserted {total_inserted} total categories (Parents and Children).")
    client.close()

if __name__ == "__main__":
    asyncio.run(seed_categories())
