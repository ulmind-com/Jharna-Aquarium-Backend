import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def test():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "royal_wool")
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    brands = await db.products.distinct("brand")
    print(brands)
    client.close()

asyncio.run(test())
