import re
from fastapi import APIRouter, Depends, HTTPException
from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize
from app.models.certification import CertificationCreate

router = APIRouter(prefix="/certifications", tags=["certifications"])

@router.get("")
async def list_certifications():
    db = get_db()
    cursor = db.certifications.find().sort("name", 1)
    docs = await cursor.to_list(length=1000)
    return [serialize(d) for d in docs]

@router.post("", dependencies=[Depends(require_admin)])
async def create_certification(body: CertificationCreate):
    db = get_db()
    if await db.certifications.find_one({"slug": body.slug}):
        raise HTTPException(status_code=400, detail="Certification already exists")
    
    doc = body.model_dump()
    res = await db.certifications.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)
