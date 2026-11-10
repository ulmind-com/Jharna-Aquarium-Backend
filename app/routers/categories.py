from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.category import CategoryCreate, CategoryUpdate
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("")
async def list_categories(parent_id: str | None = Query(default=None)):
    """List categories. parent_id=null query omitted -> top-level; pass an id for sub-categories."""
    db = get_db()
    query: dict = {}
    if parent_id is not None:
        query["parent_id"] = parent_id
    docs = await db.categories.find(query).sort("order", 1).to_list(length=500)
    return [serialize(d) for d in docs]


@router.get("/tree")
async def category_tree():
    """Return top-level categories each with their sub-categories nested."""
    db = get_db()
    docs = await db.categories.find().sort("order", 1).to_list(length=1000)
    items = [serialize(d) for d in docs]
    top = [c for c in items if not c.get("parent_id")]
    for parent in top:
        parent["children"] = [c for c in items if c.get("parent_id") == parent["id"]]
    return top


@router.post("", dependencies=[Depends(require_admin)])
async def create_category(body: CategoryCreate):
    db = get_db()
    if await db.categories.find_one({"slug": body.slug}):
        raise HTTPException(status_code=409, detail="Slug already exists")
    doc = body.model_dump()
    res = await db.categories.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/{category_id}", dependencies=[Depends(require_admin)])
async def update_category(category_id: str, body: CategoryUpdate):
    db = get_db()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.categories.find_one_and_update(
        {"_id": to_object_id(category_id)}, {"$set": update}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Category not found")
    return serialize(res)


@router.delete("/{category_id}", dependencies=[Depends(require_admin)])
async def delete_category(category_id: str):
    db = get_db()
    res = await db.categories.delete_one({"_id": to_object_id(category_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"deleted": True}
