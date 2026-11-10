import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id
from app.models.product import ProductCreate, ProductUpdate
from app.services.pricing import price_span, total_stock
from app.services.waitlist_service import notify_restocked_safely, restocked_size_keys

router = APIRouter(prefix="/products", tags=["products"])


# ── Facets ───────────────────────────────────────────────────────────────────
# One definition drives both the catalogue filter and the `/facets` response, so
# a filter can never offer a value the catalogue does not actually hold. `field`
# is the Mongo path; a `sizes.` path lives on the variants, everything else on
# the product. `param` is the query-string name the storefront sends.
FACETS: list[dict] = [
    {"param": "plant_type", "label": "Type of Plants", "field": "plant_spec.plant_type"},
    {"param": "sunlight", "label": "Sunlight Requirement", "field": "plant_spec.sunlight"},
    {"param": "watering", "label": "Watering Requirement", "field": "plant_spec.watering"},
    {"param": "difficulty", "label": "Care Level", "field": "plant_spec.difficulty_level"},
    {"param": "growth_rate", "label": "Growth Pattern", "field": "plant_spec.growth_rate"},
    {"param": "season", "label": "Growing Season", "field": "plant_spec.season"},
    {"param": "flower_color", "label": "Flower Type", "field": "plant_spec.flower_color"},
    {"param": "soil_type", "label": "Soil Type", "field": "plant_spec.soil_type"},
    {"param": "pot_type", "label": "Growing Container Type", "field": "sizes.pot_type"},
    {"param": "pot_size", "label": "Pot Size", "field": "sizes.pot_size"},
]
FACET_BY_PARAM = {f["param"]: f for f in FACETS}

IN_STOCK_QUERY = {"$or": [
    {"sizes.stock": {"$gt": 0}},
    {"sizes": {"$in": [None, []]}, "stock": {"$gt": 0}},
]}

# Yes/no facets, rendered as a checkbox each rather than a value list.
FLAG_FACETS: list[dict] = [
    {"param": "air_purifying", "label": "Air purifying", "field": "plant_spec.air_purifying"},
    {"param": "pet_safe", "label": "Pet safe", "field": "plant_spec.pet_safe"},
    {"param": "flowering", "label": "Flowering", "field": "plant_spec.flowering"},
    {"param": "fragrant", "label": "Fragrant", "field": "plant_spec.fragrant"},
    {"param": "medicinal", "label": "Medicinal", "field": "plant_spec.medicinal"},
    {"param": "is_bestseller", "label": "Bestsellers", "field": "is_bestseller"},
    {"param": "is_new_arrival", "label": "New arrivals", "field": "is_new_arrival"},
]


def _total_stock(doc: dict) -> int:
    return total_stock(doc)


def _decorate(doc: dict) -> dict:
    d = serialize(doc)
    # ensure sizes are always a list of dicts
    d["sizes"] = [s for s in (d.get("sizes") or []) if isinstance(s, dict)]
    d.update(price_span(d))  # final_price + price_from/to + price_varies
    stock = total_stock(d)
    d["total_stock"] = stock
    d["in_stock"] = stock > 0
    d["low_stock"] = 0 < stock <= (d.get("low_stock_threshold") or 5)
    return d


async def _category_ids_with_children(db, category_id: str) -> list[str]:
    ids = [category_id]
    children = await db.categories.find({"parent_id": category_id}).to_list(length=200)
    ids += [str(c["_id"]) for c in children]
    return ids


async def _category_match(db, category_id: str) -> dict:
    """Match a category by either its home field or the extra shelves, so a
    plant filed under Indoor Plants still shows on the Bedroom page it was
    added to from the admin panel."""
    ids = await _category_ids_with_children(db, category_id)
    return {"$or": [{"category_id": {"$in": ids}}, {"extra_category_ids": {"$in": ids}}]}


@router.get("")
async def list_products(
    category_id: str | None = None,
    q: str | None = Query(default=None),
    brand: str | None = None,
    # Facet filters accept the value repeated, so a shopper can tick several
    # boxes in one group (?sunlight=Low Light&sunlight=Full Sun).
    plant_type: list[str] | None = Query(default=None),
    sunlight: list[str] | None = Query(default=None),
    watering: list[str] | None = Query(default=None),
    difficulty: list[str] | None = Query(default=None),
    growth_rate: list[str] | None = Query(default=None),
    season: list[str] | None = Query(default=None),
    flower_color: list[str] | None = Query(default=None),
    soil_type: list[str] | None = Query(default=None),
    pot_type: list[str] | None = Query(default=None),
    pot_size: list[str] | None = Query(default=None),
    in_stock: bool | None = None,
    fragrant: bool | None = None,
    medicinal: bool | None = None,
    pet_safe: bool | None = None,
    air_purifying: bool | None = None,
    flowering: bool | None = None,
    is_bestseller: bool | None = None,
    is_new_arrival: bool | None = None,
    is_featured: bool | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort_by: str | None = None,
    limit: int = Query(default=20, le=200),
    skip: int = 0,
    admin: bool = False,
):
    locals_values = {
        "plant_type": plant_type, "sunlight": sunlight, "watering": watering,
        "difficulty": difficulty, "growth_rate": growth_rate, "season": season,
        "flower_color": flower_color, "soil_type": soil_type,
        "pot_type": pot_type, "pot_size": pot_size,
    }
    db = get_db()
    query: dict = {}
    if not admin:
        query["is_active"] = True
    if category_id:
        # kept under $and so it cannot collide with the top-level $or that the
        # in-stock filter sets
        query["$and"] = query.get("$and", []) + [await _category_match(db, category_id)]
    if q:
        query["$text"] = {"$search": q}
    if brand:
        query["brand"] = brand
    for spec in FACETS:
        chosen = locals_values.get(spec["param"])
        if chosen:
            query[spec["field"]] = {"$in": chosen}
    if in_stock is not None:
        query.update(IN_STOCK_QUERY if in_stock else {"$nor": [IN_STOCK_QUERY]})
    if fragrant is not None:
        query["plant_spec.fragrant"] = fragrant
    if medicinal is not None:
        query["plant_spec.medicinal"] = medicinal
    if pet_safe is not None:
        query["plant_spec.pet_safe"] = pet_safe
    if air_purifying is not None:
        query["plant_spec.air_purifying"] = air_purifying
    if flowering is not None:
        query["plant_spec.flowering"] = flowering
    if is_bestseller is not None:
        query["is_bestseller"] = is_bestseller
    if is_new_arrival is not None:
        query["is_new_arrival"] = is_new_arrival
    if is_featured is not None:
        query["is_featured"] = is_featured
    if min_price is not None:
        query["price"] = query.get("price", {})
        query["price"]["$gte"] = min_price
    if max_price is not None:
        query["price"] = query.get("price", {})
        query["price"]["$lte"] = max_price

    # Sorting
    sort_field, sort_dir = "created_at", -1
    if sort_by == "price_asc":
        sort_field, sort_dir = "price", 1
    elif sort_by == "price_desc":
        sort_field, sort_dir = "price", -1
    elif sort_by == "rating":
        sort_field, sort_dir = "rating", -1
    elif sort_by == "popularity":
        sort_field, sort_dir = "sold_count", -1
    elif sort_by == "newest":
        sort_field, sort_dir = "created_at", -1

    cursor = db.products.find(query).skip(skip).limit(limit).sort(sort_field, sort_dir)
    docs = await cursor.to_list(length=limit)
    return [_decorate(d) for d in docs]


@router.get("/facets")
async def product_facets(category_id: str | None = None):
    """The filter sidebar, derived from the catalogue rather than hard-coded.

    Every group lists only the values products actually carry, each with the
    number of products behind it, so a shopper can never pick a filter that
    returns an empty grid. A group with nothing in it is left out entirely.
    """
    db = get_db()
    base: dict = {"is_active": True}
    if category_id:
        base["$and"] = [await _category_match(db, category_id)]

    groups = []
    for spec in FACETS:
        pipeline: list[dict] = [{"$match": base}]
        if spec["field"].startswith("sizes."):
            pipeline.append({"$unwind": "$sizes"})
        # Count products, not variants — one product with three pot sizes is
        # still one result behind the "Ceramic Pot" box.
        pipeline += [
            {"$group": {"_id": f"${spec['field']}", "ids": {"$addToSet": "$_id"}}},
            {"$project": {"count": {"$size": "$ids"}}},
            {"$sort": {"count": -1, "_id": 1}},
        ]
        rows = await db.products.aggregate(pipeline).to_list(length=100)
        options = [
            {"value": r["_id"], "count": r["count"]}
            for r in rows if isinstance(r["_id"], str) and r["_id"].strip()
        ]
        if options:
            groups.append({"param": spec["param"], "label": spec["label"], "options": options})

    flags = []
    for spec in FLAG_FACETS:
        count = await db.products.count_documents({**base, spec["field"]: True})
        if count:
            flags.append({"param": spec["param"], "label": spec["label"], "count": count})

    in_stock = await db.products.count_documents({**base, **IN_STOCK_QUERY})
    total = await db.products.count_documents(base)

    prices = await db.products.aggregate([
        {"$match": base},
        {"$group": {"_id": None, "min": {"$min": "$price"}, "max": {"$max": "$price"}}},
    ]).to_list(length=1)

    return {
        "total": total,
        "availability": [
            {"value": "in_stock", "label": "In stock", "count": in_stock},
            {"value": "out_of_stock", "label": "Out of stock", "count": total - in_stock},
        ],
        "price": {
            "min": (prices[0]["min"] if prices and prices[0].get("min") is not None else 0),
            "max": (prices[0]["max"] if prices and prices[0].get("max") is not None else 0),
        },
        "groups": groups,
        "flags": flags,
    }


@router.get("/{product_id}")
async def get_product(product_id: str):
    db = get_db()
    doc = await db.products.find_one({"_id": to_object_id(product_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return _decorate(doc)


@router.post("", dependencies=[Depends(require_admin)])
async def create_product(body: ProductCreate):
    db = get_db()
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.products.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _decorate(doc)


@router.patch("/{product_id}", dependencies=[Depends(require_admin)])
async def update_product(product_id: str, body: ProductUpdate):
    db = get_db()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Only a save that actually touches stock can restock anything — skip the
    # extra lookup (and the waitlist check) for ordinary metadata edits.
    stock_touched = "sizes" in update or "stock" in update
    before = await db.products.find_one({"_id": to_object_id(product_id)}) if stock_touched else None

    res = await db.products.find_one_and_update(
        {"_id": to_object_id(product_id)}, {"$set": update}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Product not found")

    if before:
        keys = restocked_size_keys(before, res)
        if keys:
            asyncio.create_task(notify_restocked_safely(db, res, keys))

    return _decorate(res)


@router.delete("/{product_id}", dependencies=[Depends(require_admin)])
async def delete_product(product_id: str):
    db = get_db()
    res = await db.products.delete_one({"_id": to_object_id(product_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"deleted": True}


@router.get("/admin/low-stock", dependencies=[Depends(require_admin)])
async def low_stock():
    """Products at or below their low-stock threshold."""
    db = get_db()
    docs = await db.products.find().to_list(length=500)
    out = [_decorate(d) for d in docs]
    return [p for p in out if p["total_stock"] <= (p.get("low_stock_threshold") or 5)]
