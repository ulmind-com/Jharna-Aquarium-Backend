import re
from fastapi import APIRouter, Depends, HTTPException
from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id
from app.models.brand import BrandCreate

router = APIRouter(prefix="/brands", tags=["brands"])

def generate_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    return re.sub(r'[\s-]+', '-', slug).strip('-')

@router.get("")
async def list_brands():
    db = get_db()
    cursor = db.brands.find().sort("name", 1)
    docs = await cursor.to_list(length=1000)
    return [serialize(d) for d in docs]

@router.post("", dependencies=[Depends(require_admin)])
async def create_brand(body: BrandCreate):
    db = get_db()
    if await db.brands.find_one({"slug": body.slug}):
        raise HTTPException(status_code=400, detail="Brand with this slug already exists")
    
    doc = body.model_dump()
    res = await db.brands.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)
