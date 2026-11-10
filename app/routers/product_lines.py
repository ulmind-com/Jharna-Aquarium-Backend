import re
from fastapi import APIRouter, Depends, HTTPException, Query
from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize
from app.models.product_line import ProductLineCreate

router = APIRouter(prefix="/product-lines", tags=["product_lines"])

def generate_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    return re.sub(r'[\s-]+', '-', slug).strip('-')

@router.get("")
async def list_product_lines(brand: str | None = Query(default=None)):
    db = get_db()
    query = {}
    if brand:
        query["brand"] = brand
        
    cursor = db.product_lines.find(query).sort("name", 1)
    docs = await cursor.to_list(length=1000)
    return [serialize(d) for d in docs]

@router.post("", dependencies=[Depends(require_admin)])
async def create_product_line(body: ProductLineCreate):
    db = get_db()
    # Check if exists with same slug under same brand
    if await db.product_lines.find_one({"slug": body.slug, "brand": body.brand}):
        raise HTTPException(status_code=400, detail="Product line with this slug already exists for this brand")
    
    doc = body.model_dump()
    res = await db.product_lines.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)
