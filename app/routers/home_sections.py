"""Admin-configurable home screen.

The admin builds the home feed out of ordered *sections*. Each section has:
- type:   "recommendation" (AI/personalised) | "manual" (hand-picked products)
          | "category" (latest from a category)
- layout: "rail" (side-by-side horizontal) | "grid" (stacked 2-column)
- order:  position on the home screen (recommendation sits on top by default)

Public `/home-sections/resolved` returns the ordered, active sections with their
products already resolved — the mobile home screen just renders them.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.mongodb import get_db
from app.deps import get_optional_user, require_admin
from app.models.common import serialize, to_object_id
from app.routers.products import _category_ids_with_children, _decorate
from app.routers.recommendations import compute_home

router = APIRouter(prefix="/home-sections", tags=["home"])

SECTION_TYPES = {"recommendation", "manual", "category"}
LAYOUTS = {"rail", "grid"}

# Seeded once so "Recommended for you" is on top by default; admin can reorder it.
_DEFAULTS = [
    {"title": "Recommended for you", "type": "recommendation", "layout": "rail",
     "product_ids": [], "category_id": None, "limit": 12, "order": 0, "active": True},
]


class HomeSectionIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    type: str = "manual"
    layout: str = "rail"
    product_ids: list[str] = Field(default_factory=list)
    category_id: str | None = None
    limit: int = Field(default=10, ge=1, le=30)
    order: int = 0
    active: bool = True


class ReorderIn(BaseModel):
    ids: list[str]


def _validate(type_: str | None, layout: str | None) -> None:
    if type_ is not None and type_ not in SECTION_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(SECTION_TYPES)}")
    if layout is not None and layout not in LAYOUTS:
        raise HTTPException(status_code=400, detail=f"layout must be one of {sorted(LAYOUTS)}")


async def _ensure_defaults(db) -> None:
    if await db.home_sections.count_documents({}) == 0:
        now = datetime.now(timezone.utc)
        await db.home_sections.insert_many([{**d, "created_at": now} for d in _DEFAULTS])


async def _resolve_products(db, s: dict, user: dict | None) -> list[dict]:
    limit = int(s.get("limit") or 10)
    t = s.get("type")

    if t == "recommendation":
        return await compute_home(db, user, limit)

    if t == "manual":
        ids = s.get("product_ids") or []
        oids = [to_object_id(i) for i in ids if len(i) == 24]
        if not oids:
            return []
        docs = await db.products.find({"_id": {"$in": oids}, "is_active": True}).to_list(length=200)
        by = {str(d["_id"]): _decorate(d) for d in docs}
        return [by[i] for i in ids if i in by][:limit]  # preserve the admin's order

    if t == "category":
        cid = s.get("category_id")
        if not cid:
            return []
        cat_ids = await _category_ids_with_children(db, cid)
        docs = (
            await db.products.find({"category_id": {"$in": cat_ids}, "is_active": True})
            .sort("created_at", -1)
            .limit(limit)
            .to_list(length=limit)
        )
        return [_decorate(d) for d in docs]

    return []


# ── Public ───────────────────────────────────────────────────────────────────

@router.get("/resolved")
async def resolved_sections(user: dict | None = Depends(get_optional_user)):
    db = get_db()
    await _ensure_defaults(db)
    sections = await db.home_sections.find({"active": True}).sort("order", 1).to_list(length=200)
    out = []
    for s in sections:
        products = await _resolve_products(db, s, user)
        if not products:
            continue  # never render an empty section
        out.append({
            "id": str(s["_id"]),
            "title": s.get("title", ""),
            "type": s.get("type"),
            "layout": s.get("layout", "rail"),
            "products": products,
        })
    return out


# ── Admin ────────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(require_admin)])
async def list_sections():
    db = get_db()
    await _ensure_defaults(db)
    docs = await db.home_sections.find().sort("order", 1).to_list(length=200)
    return [serialize(d) for d in docs]


@router.post("", dependencies=[Depends(require_admin)])
async def create_section(body: HomeSectionIn):
    _validate(body.type, body.layout)
    db = get_db()
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.home_sections.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.put("/order", dependencies=[Depends(require_admin)])
async def reorder_sections(body: ReorderIn):
    db = get_db()
    for i, sid in enumerate(body.ids):
        if len(sid) == 24:
            await db.home_sections.update_one({"_id": to_object_id(sid)}, {"$set": {"order": i}})
    return {"ok": True}


@router.patch("/{section_id}", dependencies=[Depends(require_admin)])
async def update_section(section_id: str, body: dict = Body(...)):
    db = get_db()
    for k in ("id", "_id", "created_at"):
        body.pop(k, None)
    _validate(body.get("type"), body.get("layout"))
    res = await db.home_sections.find_one_and_update(
        {"_id": to_object_id(section_id)}, {"$set": body}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Section not found")
    return serialize(res)


@router.delete("/{section_id}", dependencies=[Depends(require_admin)])
async def delete_section(section_id: str):
    db = get_db()
    await db.home_sections.delete_one({"_id": to_object_id(section_id)})
    return {"deleted": True}
