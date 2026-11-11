from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.category import CategoryCreate, CategoryUpdate
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/categories", tags=["categories"])


class CategoryOrderBody(BaseModel):
    ids: list[str]


async def _product_sets_by_category(db) -> dict[str, set[str]]:
    """Map each category id to the unique product ids assigned to it directly or via extra shelves."""
    sets: dict[str, set[str]] = {}
    docs = await db.products.find(
        {}, {"category_id": 1, "extra_category_ids": 1}
    ).to_list(length=5000)
    for prod in docs:
        pid = str(prod["_id"])
        cid = prod.get("category_id")
        if isinstance(cid, str) and cid:
            sets.setdefault(cid, set()).add(pid)
        for extra in prod.get("extra_category_ids") or []:
            if isinstance(extra, str) and extra:
                sets.setdefault(extra, set()).add(pid)
    return sets


async def _next_order(db, parent_id: str | None) -> int:
    siblings = await db.categories.find({"parent_id": parent_id}, {"order": 1}).to_list(length=500)
    if parent_id is None:
        # Keep regular shop categories ahead of room-only trees anchored around order >= 90.
        orders = [c.get("order", 0) or 0 for c in siblings if (c.get("order") or 0) < 90]
        return max(orders, default=9) + 1
    orders = [c.get("order", 0) or 0 for c in siblings]
    return max(orders, default=0) + 1


@router.get("")
async def list_categories(parent_id: str | None = Query(default=None)):
    """List categories. parent_id=null query omitted -> top-level; pass an id for sub-categories."""
    db = get_db()
    query: dict = {}
    if parent_id is not None:
        query["parent_id"] = parent_id
    docs = await db.categories.find(query).sort([("order", 1), ("name", 1)]).to_list(length=500)
    return [serialize(d) for d in docs]


@router.get("/tree")
async def category_tree(include_counts: bool = Query(default=False)):
    """Return top-level categories each with their sub-categories nested."""
    db = get_db()
    docs = await db.categories.find().sort([("order", 1), ("name", 1)]).to_list(length=1000)
    items = [serialize(d) for d in docs]
    prod_sets = await _product_sets_by_category(db) if include_counts else {}

    top = [c for c in items if not c.get("parent_id")]
    for parent in top:
        children = [c for c in items if c.get("parent_id") == parent["id"]]
        if include_counts:
            combined = set(prod_sets.get(parent["id"], ()))
            for child in children:
                child_set = prod_sets.get(child["id"], set())
                child["direct_product_count"] = len(child_set)
                child["product_count"] = len(child_set)
                combined |= child_set
            parent["direct_product_count"] = len(prod_sets.get(parent["id"], ()))
            parent["product_count"] = len(combined)
        parent["children"] = children
    return top


@router.post("", dependencies=[Depends(require_admin)])
async def create_category(body: CategoryCreate):
    db = get_db()
    if await db.categories.find_one({"slug": body.slug}):
        raise HTTPException(status_code=409, detail="Slug already exists")
    doc = body.model_dump()
    if not doc.get("order"):
        doc["order"] = await _next_order(db, doc.get("parent_id"))
    res = await db.categories.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.put("/order", dependencies=[Depends(require_admin)])
async def reorder_categories(body: CategoryOrderBody):
    db = get_db()
    for idx, cid in enumerate(body.ids):
        await db.categories.update_one(
            {"_id": to_object_id(cid)},
            {"$set": {"order": 10 + idx}},
        )
    return {"ok": True}


@router.patch("/{category_id}", dependencies=[Depends(require_admin)])
async def update_category(category_id: str, body: CategoryUpdate):
    db = get_db()
    oid = to_object_id(category_id)
    update = body.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if "slug" in update and update["slug"]:
        conflict = await db.categories.find_one(
            {"slug": update["slug"], "_id": {"$ne": oid}}
        )
        if conflict:
            raise HTTPException(status_code=409, detail="Slug already exists")
    res = await db.categories.find_one_and_update(
        {"_id": oid}, {"$set": update}, return_document=True
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
    # Clean up sub-categories belonging to the deleted parent so none remain orphaned.
    await db.categories.delete_many({"parent_id": category_id})
    return {"deleted": True}
