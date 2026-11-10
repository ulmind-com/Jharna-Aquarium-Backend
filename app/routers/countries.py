import re
from fastapi import APIRouter, Depends, HTTPException
from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize
from app.models.country import CountryCreate

router = APIRouter(prefix="/countries", tags=["countries"])

@router.get("")
async def list_countries():
    db = get_db()
    cursor = db.countries.find().sort("name", 1)
    docs = await cursor.to_list(length=1000)
    return [serialize(d) for d in docs]

@router.post("", dependencies=[Depends(require_admin)])
async def create_country(body: CountryCreate):
    db = get_db()
    if await db.countries.find_one({"slug": body.slug}):
        raise HTTPException(status_code=400, detail="Country already exists")
    
    doc = body.model_dump()
    res = await db.countries.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)
