"""
Advanced product search with faceted filters.
Flipkart-style: returns products + facet counts for every filter dimension
so the client can render counts like  Nike (42)  in the filter panel.

Also manages trending search terms (admin-configurable).
"""

import math
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id
from app.services.pricing import price_span, total_stock

router = APIRouter(prefix="/search", tags=["search"])

# Nice ordering for size chips (XS, S, M, ... rather than alphabetical).
_SIZE_ORDER = {s: i for i, s in enumerate(
    ["XS", "S", "M", "L", "XL", "XXL", "XXXL", "3XL", "4XL",
     "28", "30", "32", "34", "36", "38", "40", "42", "44",
     "6", "7", "8", "9", "10", "11", "12",
     "Free Size"]
)}

_TRENDING_KEY = {"_id": "trending_searches"}


def _csv(value: str | None) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()] if value else []


def _total_stock(doc: dict) -> int:
    return total_stock(doc)


def _decorate(doc: dict) -> dict:
    d = serialize(doc)
    d["colors"] = [c for c in (d.get("colors") or []) if isinstance(c, dict)]
    d.update(price_span(d))
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


def _sort_key(sort: str):
    """Return (mongo_field, direction) for the requested sort."""
    mapping = {
        "price_asc":   ("price", 1),
        "price_desc":  ("price", -1),
        "newest":      ("created_at", -1),
        "popularity":  ("sold_count", -1),
        "rating":      ("rating", -1),
        "discount":    ("discount_pct", -1),
        "relevance":   ("created_at", -1),
    }
    return mapping.get(sort, ("created_at", -1))


# ─── Trending searches (admin-configurable) ────────────────────────────────


@router.get("/trending")
async def get_trending():
    """Public: return the list of trending search terms configured by admin."""
    db = get_db()
    doc = await db.settings.find_one(_TRENDING_KEY)
    if not doc:
        return {"terms": []}
    return {"terms": doc.get("terms", [])}


@router.put("/trending", dependencies=[Depends(require_admin)])
async def set_trending(body: dict):
    """Admin: set the list of trending search terms.
    Body: { "terms": ["Summer Collection", "T-Shirts", ...] }
    """
    db = get_db()
    terms = body.get("terms", [])
    # Ensure it's a list of strings
    terms = [str(t).strip() for t in terms if str(t).strip()][:20]
    await db.settings.update_one(
        _TRENDING_KEY,
        {"$set": {"terms": terms}},
        upsert=True,
    )
    return {"terms": terms}


# ─── Search helpers ────────────────────────────────────────────────────────


async def _resolve_search_terms_and_categories(
    db, q: str
) -> tuple[list[str], set[str], set[str], list[dict]]:
    """Extract tokens, stems, find matching categories, and return:
    (stems, all_matching_cat_ids, direct_cat_ids, matching_categories_list)
    """
    clean_q = q.strip()
    if not clean_q:
        return [], set(), set(), []

    words = [w for w in re.split(r"[\s,\-_/]+", clean_q) if len(w) > 1]
    stems = set()
    for w in words:
        wl = w.lower()
        stems.add(wl)
        if wl.endswith("s") and len(wl) > 3:
            stems.add(wl[:-1])
        if wl.endswith("es") and len(wl) > 4:
            stems.add(wl[:-2])
        if wl.endswith("ing") and len(wl) > 5:
            stems.add(wl[:-3])

    # Search categories by name and slug
    cat_queries = [
        {"name": {"$regex": re.escape(clean_q), "$options": "i"}},
        {"slug": {"$regex": re.escape(clean_q), "$options": "i"}},
    ]
    for stem in stems:
        cat_queries.append({"name": {"$regex": re.escape(stem), "$options": "i"}})
        cat_queries.append({"slug": {"$regex": re.escape(stem), "$options": "i"}})

    cat_docs = await db.categories.find({"$or": cat_queries}).to_list(length=30)
    direct_cat_ids = {str(c["_id"]) for c in cat_docs}
    all_cat_ids = set(direct_cat_ids)

    for cid in list(direct_cat_ids):
        kids = await db.categories.find({"parent_id": cid}).to_list(length=100)
        for k in kids:
            all_cat_ids.add(str(k["_id"]))

    return list(stems), all_cat_ids, direct_cat_ids, [serialize(c) for c in cat_docs]


def _score_product(p: dict, clean_q: str, stems: list[str], matching_cat_ids: set[str]) -> float:
    """Calculate contextual search relevance score for ranking products."""
    score = 0.0
    title_l = (p.get("title") or "").lower()
    q_l = clean_q.lower()

    # Exact title match
    if title_l == q_l:
        score += 1000.0
    elif title_l.startswith(q_l):
        score += 600.0
    elif q_l in title_l:
        score += 400.0

    # Keyword / stem matches in title
    for stem in stems:
        if re.search(r"\b" + re.escape(stem) + r"\b", title_l):
            score += 150.0
        elif stem in title_l:
            score += 75.0

    # Primary or secondary category matches
    cid = str(p.get("category_id") or "")
    if cid in matching_cat_ids:
        score += 130.0

    extras = [str(x) for x in (p.get("extra_category_ids") or [])]
    if any(x in matching_cat_ids for x in extras):
        score += 90.0

    # Tags match
    tags = [str(t).lower() for t in (p.get("tags") or [])]
    for stem in stems:
        if any(stem == t for t in tags):
            score += 100.0
        elif any(stem in t for t in tags):
            score += 50.0

    # Descriptions
    short_desc = (p.get("short_description") or "").lower()
    if q_l in short_desc:
        score += 40.0
    for stem in stems:
        if stem in short_desc:
            score += 20.0

    desc = (p.get("description") or "").lower()
    if q_l in desc:
        score += 15.0

    # Quality and availability signals
    if p.get("is_bestseller"):
        score += 10.0
    if p.get("in_stock"):
        score += 5.0
    score += (p.get("rating") or 0) * 2.0

    return score


# ─── Autocomplete Suggestions Endpoint ───────────────────────────────────


@router.get("/suggest")
async def search_suggestions(q: str = Query(default="", min_length=1)):
    """Fast live suggestions returning matching categories and products with

    name, price, image thumbnail, and category label.
    """
    db = get_db()
    clean_q = q.strip()
    if not clean_q:
        return {"products": [], "categories": [], "total_matches": 0}

    stems, matching_cat_ids, direct_cat_ids, matching_cats = (
        await _resolve_search_terms_and_categories(db, clean_q)
    )

    all_cats = await db.categories.find().to_list(length=300)
    cat_name_map = {str(c["_id"]): c.get("name", "") for c in all_cats}

    or_conds: list[dict] = [
        {"title": {"$regex": re.escape(clean_q), "$options": "i"}},
        {"short_description": {"$regex": re.escape(clean_q), "$options": "i"}},
        {"tags": {"$regex": re.escape(clean_q), "$options": "i"}},
    ]
    for stem in stems:
        or_conds.append({"title": {"$regex": re.escape(stem), "$options": "i"}})
        or_conds.append({"tags": {"$regex": re.escape(stem), "$options": "i"}})

    if matching_cat_ids:
        or_conds.append({"category_id": {"$in": list(matching_cat_ids)}})
        or_conds.append({"extra_category_ids": {"$in": list(matching_cat_ids)}})

    # Exclude generic store brand unless search is specific
    store_common_words = {"jharna", "aquarium", "nursery"}
    if not any(w in store_common_words for w in stems):
        or_conds.append({"brand": {"$regex": re.escape(clean_q), "$options": "i"}})

    docs = await db.products.find({"is_active": True, "$or": or_conds}).limit(80).to_list(length=80)
    products = [_decorate(d) for d in docs]

    for p in products:
        p["_score"] = _score_product(p, clean_q, stems, matching_cat_ids)
    products.sort(key=lambda p: p["_score"], reverse=True)

    formatted_products = []
    for p in products[:8]:
        images = p.get("images") or []
        image = images[0] if images else p.get("image")
        cid = str(p.get("category_id") or "")
        formatted_products.append({
            "id": p.get("id"),
            "title": p.get("title"),
            "slug": p.get("slug") or p.get("id"),
            "price": p.get("price"),
            "mrp": p.get("mrp"),
            "final_price": p.get("final_price") or p.get("price"),
            "off_pct": p.get("off_pct") or 0,
            "image": image,
            "category_id": cid,
            "category_name": cat_name_map.get(cid, ""),
            "in_stock": p.get("in_stock", True),
        })

    formatted_cats = []
    for c in matching_cats[:4]:
        formatted_cats.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "slug": c.get("slug"),
            "image": c.get("image"),
        })

    return {
        "products": formatted_products,
        "categories": formatted_cats,
        "total_matches": len(products),
    }


# ─── Product search with filters ──────────────────────────────────────────


@router.get("")
async def search_products(
    q: str | None = Query(default=None),
    category_id: str | None = None,
    brands: str | None = None,
    sizes: str | None = None,
    colors: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    min_rating: float | None = None,
    min_discount: int | None = None,
    in_stock: bool | None = None,
    sort: str = "relevance",
    skip: int = 0,
    limit: int = Query(default=20, le=100),
):
    db = get_db()

    # --- Build the base query -----------------------------------------------
    query: dict = {"is_active": True}
    clean_q = q.strip() if q else ""
    stems: list[str] = []
    matching_cat_ids: set[str] = set()
    matching_cats: list[dict] = []

    if clean_q:
        stems, matching_cat_ids, _, matching_cats = await _resolve_search_terms_and_categories(db, clean_q)

        or_conds: list[dict] = [
            {"title": {"$regex": re.escape(clean_q), "$options": "i"}},
            {"short_description": {"$regex": re.escape(clean_q), "$options": "i"}},
            {"description": {"$regex": re.escape(clean_q), "$options": "i"}},
            {"tags": {"$regex": re.escape(clean_q), "$options": "i"}},
        ]
        for stem in stems:
            or_conds.append({"title": {"$regex": re.escape(stem), "$options": "i"}})
            or_conds.append({"tags": {"$regex": re.escape(stem), "$options": "i"}})

        if matching_cat_ids:
            or_conds.append({"category_id": {"$in": list(matching_cat_ids)}})
            or_conds.append({"extra_category_ids": {"$in": list(matching_cat_ids)}})

        store_common_words = {"jharna", "aquarium", "nursery"}
        if not any(w in store_common_words for w in stems):
            or_conds.append({"brand": {"$regex": re.escape(clean_q), "$options": "i"}})

        query["$or"] = or_conds

    if category_id:
        cat_ids = await _category_ids_with_children(db, category_id)
        query["category_id"] = {"$in": cat_ids}

    brand_list = _csv(brands)
    if brand_list:
        query["brand"] = {"$in": [re.compile(f"^{re.escape(b)}$", re.IGNORECASE) for b in brand_list]}

    size_list = _csv(sizes)
    if size_list:
        query["sizes"] = {"$in": size_list}

    color_list = _csv(colors)
    if color_list:
        query["colors.name"] = {"$in": [re.compile(f"^{re.escape(c)}$", re.IGNORECASE) for c in color_list]}

    if price_min is not None:
        query.setdefault("price", {})["$gte"] = price_min
    if price_max is not None:
        query.setdefault("price", {})["$lte"] = price_max

    if min_rating is not None:
        query["rating"] = {"$gte": min_rating}

    # --- Fetch products -----------------------------------------------------
    if sort == "relevance" and clean_q:
        # Fetch candidate set and rank by relevance score
        cursor = db.products.find(query).limit(200)
        docs = await cursor.to_list(length=200)
        products = [_decorate(d) for d in docs]

        if in_stock:
            products = [p for p in products if p["in_stock"]]
        if min_discount is not None and min_discount > 0:
            products = [p for p in products if (p.get("off_pct") or 0) >= min_discount]

        for p in products:
            p["_score"] = _score_product(p, clean_q, stems, matching_cat_ids)
        products.sort(key=lambda p: p["_score"], reverse=True)

        total = len(products)
        products = products[skip : skip + limit]
    else:
        sort_field, sort_dir = _sort_key(sort)
        cursor = db.products.find(query).sort(sort_field, sort_dir).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        products = [_decorate(d) for d in docs]

        if in_stock:
            products = [p for p in products if p["in_stock"]]
        if min_discount is not None and min_discount > 0:
            products = [p for p in products if (p.get("off_pct") or 0) >= min_discount]

        total = await db.products.count_documents(query)

    # --- Build facets from ALL matching products
    facet_query: dict = {"is_active": True}
    if clean_q and "$or" in query:
        facet_query["$or"] = query["$or"]
    if category_id:
        facet_query["category_id"] = query.get("category_id", {"$in": [category_id]})

    facet_cursor = db.products.find(facet_query).limit(500)
    facet_docs = await facet_cursor.to_list(length=500)
    facet_items = [_decorate(d) for d in facet_docs]

    cat_ids_set = set()
    for p in facet_items:
        cid = p.get("category_id")
        if cid:
            cat_ids_set.add(cid)

    cat_name_map = {}
    if cat_ids_set:
        cat_docs = await db.categories.find(
            {"_id": {"$in": [to_object_id(cid) for cid in cat_ids_set if len(cid) == 24]}}
        ).to_list(length=200)
        for cd in cat_docs:
            cat_name_map[str(cd["_id"])] = cd.get("name", "")

    facets = _build_facets(facet_items, cat_name_map)

    return {
        "products": products,
        "items": products,
        "categories": matching_cats[:4],
        "total": total,
        "facets": facets,
    }


def _build_facets(items: list[dict], cat_name_map: dict) -> dict:
    """Compute facet counts from a list of decorated product dicts."""
    brand_counts: dict[str, int] = {}
    size_counts: dict[str, int] = {}
    color_counts: dict[str, dict] = {}  # name -> {hex, count}
    category_counts: dict[str, int] = {}
    rating_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    discount_buckets = {10: 0, 20: 0, 30: 0, 40: 0, 50: 0, 60: 0, 70: 0}
    price_min = float("inf")
    price_max = 0.0

    for p in items:
        # Brand
        brand = p.get("brand")
        if brand:
            brand_counts[brand] = brand_counts.get(brand, 0) + 1

        # Sizes
        for s in (p.get("sizes") or []):
            sname = s.get("name", "") if isinstance(s, dict) else str(s)
            if sname:
                size_counts[sname] = size_counts.get(sname, 0) + 1

        # Colors
        for c in (p.get("colors") or []):
            if isinstance(c, dict):
                name = c.get("name", "")
                if name:
                    if name not in color_counts:
                        color_counts[name] = {"hex": c.get("hex", "#000"), "count": 0}
                    color_counts[name]["count"] += 1

        # Category
        cat_id = p.get("category_id")
        if cat_id:
            category_counts[cat_id] = category_counts.get(cat_id, 0) + 1

        # Price
        final = p.get("final_price") or p.get("price") or 0
        if final > 0:
            price_min = min(price_min, final)
            price_max = max(price_max, final)

        # Rating (cumulative: a 4.5 product counts in "4★ & above", "3★ & above", …
        # so the facet counts match the min_rating >= X query results).
        rating = p.get("rating") or 0
        for stars in [4, 3, 2, 1]:
            if rating >= stars:
                rating_counts[stars] += 1

        # Discount — use off_pct (the visible discount) to match the filter logic.
        off = p.get("off_pct") or 0
        for threshold in sorted(discount_buckets.keys()):
            if off >= threshold:
                discount_buckets[threshold] += 1

    # Sort sizes by our custom order
    sorted_sizes = sorted(
        size_counts.items(),
        key=lambda x: _SIZE_ORDER.get(x[0], 999)
    )

    # Sort brands alphabetically
    sorted_brands = sorted(brand_counts.items(), key=lambda x: x[0].lower())

    return {
        "brands": [{"name": b, "count": c} for b, c in sorted_brands],
        "sizes": [{"name": s, "count": c} for s, c in sorted_sizes],
        "colors": [
            {"name": name, "hex": info["hex"], "count": info["count"]}
            for name, info in sorted(color_counts.items(), key=lambda x: x[0].lower())
        ],
        "price_range": {
            "min": price_min if price_min != float("inf") else 0,
            "max": price_max,
        },
        "categories": [
            {"id": cid, "name": cat_name_map.get(cid, cid), "count": cnt}
            for cid, cnt in category_counts.items()
        ],
        "ratings": [
            {"stars": s, "count": rating_counts[s], "label": f"{s}★ & above"}
            for s in [4, 3, 2, 1]
            if rating_counts[s] > 0
        ],
        "discounts": [
            {"value": v, "count": discount_buckets[v], "label": f"{v}% or more"}
            for v in sorted(discount_buckets.keys())
            if discount_buckets[v] > 0
        ],
    }
