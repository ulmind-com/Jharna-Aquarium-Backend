"""
Product recommendations — retrieve-then-rerank (production pattern).

1. A heuristic engine retrieves a candidate pool:
   - content-based similarity (category, brand, price band, sizes/colours),
   - item-to-item collaborative signal via order co-occurrence,
   - popularity prior for cold-start / tie-breaking.
2. A Groq LLM re-ranks the candidates for the shopper's real context
   (recent purchases, wishlist, current cart, viewed product). The LLM can only
   reorder real candidate ids, results are cached briefly, and any failure falls
   back to the heuristic order — so it is always fast and never breaks.

Endpoints:
- GET /recommendations/home              → personalised for the user, else popular.
- GET /recommendations/similar/{id}      → similar products (product page).
- GET /recommendations/cart?product_ids= → "You may like" for the current cart.
"""

from fastapi import APIRouter, Depends, Query

from app.db.mongodb import get_db
from app.deps import get_optional_user
from app.models.common import to_object_id
from app.routers.products import _decorate
from app.services import recommender

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# How many candidates the heuristic hands to the LLM (kept small for latency).
_POOL = 30


# ── Heuristic candidate generation ───────────────────────────────────────────

def _pop_score(p: dict) -> float:
    return (
        (p.get("sold_count") or 0) * 1.0
        + (p.get("rating") or 0) * 8.0
        + (p.get("review_count") or 0) * 0.5
    )


def _variant_name(value) -> str | None:
    """A size is a variant dict here, but older rows stored a bare string."""
    if isinstance(value, dict):
        name = value.get("name")
        return str(name) if name else None
    return str(value) if value else None


def _content_sim(a: dict, b: dict) -> float:
    score = 0.0
    if a.get("category_id") and a.get("category_id") == b.get("category_id"):
        score += 5.0
    if a.get("brand") and a.get("brand") == b.get("brand"):
        score += 3.0
    pa, pb = a.get("final_price") or 0, b.get("final_price") or 0
    if pa and pb:
        score += (min(pa, pb) / max(pa, pb)) * 2.0
    # Sizes are variant documents on this catalogue, so they can't go straight
    # into a set — compare them by name, the way colours just below do.
    sa = {_variant_name(v) for v in (a.get("sizes") or [])}
    sb = {_variant_name(v) for v in (b.get("sizes") or [])}
    if sa & sb - {None}:
        score += 1.0
    ca = {c.get("name") for c in (a.get("colors") or []) if isinstance(c, dict)}
    cb = {c.get("name") for c in (b.get("colors") or []) if isinstance(c, dict)}
    if ca & cb:
        score += 0.5
    return score


def _avail(p: dict) -> float:
    return 0.0 if p.get("in_stock") else -1000.0


async def _active_products(db, limit: int = 800) -> list[dict]:
    docs = await db.products.find({"is_active": True}).limit(limit).to_list(length=limit)
    return [_decorate(d) for d in docs]


def _popular(products: list[dict], limit: int, exclude: set[str]) -> list[dict]:
    ranked = sorted(
        (p for p in products if p["id"] not in exclude),
        key=lambda p: _avail(p) + _pop_score(p),
        reverse=True,
    )
    return ranked[:limit]


def _rank(products, seeds, exclude, copurchase, limit):
    copurchase = copurchase or {}
    scored: list[tuple[float, dict]] = []
    for p in products:
        if p["id"] in exclude:
            continue
        content = max((_content_sim(p, s) for s in seeds), default=0.0)
        co = copurchase.get(p["id"], 0) * 4.0
        s = co + content + _pop_score(p) * 0.02 + _avail(p)
        if s > -900:
            scored.append((s, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = [p for s, p in scored if s > 0][:limit]
    if len(out) < limit:
        have = {p["id"] for p in out} | exclude
        out += _popular(products, limit - len(out), have)
    return out[:limit]


# ── Category names + context for the LLM ─────────────────────────────────────

async def _cat_names(db, ids: set[str]) -> dict[str, str]:
    valid = [i for i in ids if i and len(i) == 24]
    if not valid:
        return {}
    docs = await db.categories.find(
        {"_id": {"$in": [to_object_id(i) for i in valid]}}
    ).to_list(length=500)
    return {str(d["_id"]): d.get("name", "") for d in docs}


def _attach(products: list[dict], names: dict[str, str]) -> None:
    for p in products:
        p["category_name"] = names.get(p.get("category_id"), "")


def _brief(p: dict) -> str:
    return (
        f"- {p.get('title')} "
        f"({p.get('brand') or 'n/a'}, {p.get('category_name') or 'n/a'}, "
        f"₹{p.get('final_price') or p.get('price') or 0})"
    )


def _finalize(candidates: list[dict], ordered_ids: list[str] | None, limit: int) -> list[dict]:
    if ordered_ids:
        by = {c["id"]: c for c in candidates}
        picked = [by[i] for i in ordered_ids if i in by]
        if picked:
            return picked[:limit]
    return candidates[:limit]


# ── Endpoints ────────────────────────────────────────────────────────────────

async def compute_home(db, user: dict | None, limit: int) -> list[dict]:
    """Personalised home recommendations (reused by the home-layout builder)."""
    products = await _active_products(db)
    by_id = {p["id"]: p for p in products}

    seed_ids: set[str] = set()
    if user:
        orders = await db.orders.find({"user_id": user["id"]}).to_list(length=500)
        for o in orders:
            for it in o.get("items", []):
                if it.get("product_id"):
                    seed_ids.add(it["product_id"])
        wl = await db.wishlists.find_one({"user_id": user["id"]})
        for pid in (wl or {}).get("product_ids", []):
            seed_ids.add(pid)

    seeds = [by_id[i] for i in seed_ids if i in by_id]
    if seeds:
        candidates = _rank(products, seeds, exclude=seed_ids, copurchase=None, limit=_POOL)
    else:
        candidates = _popular(products, _POOL, exclude=set())

    names = await _cat_names(db, {p.get("category_id") for p in candidates + seeds})
    _attach(candidates, names)
    _attach(seeds, names)

    if seeds:
        context = (
            "The shopper has previously bought or wishlisted:\n"
            + "\n".join(_brief(s) for s in seeds[:12])
            + "\nRecommend items that match their taste, style and budget."
        )
    else:
        context = "New shopper with no history yet — recommend popular, broadly-appealing picks."

    cache_key = f"home:{user['id']}" if user else "home:anon"
    ordered = await recommender.rerank(context, candidates, limit, cache_key)
    return _finalize(candidates, ordered, limit)


@router.get("/home")
async def home_recommendations(
    limit: int = Query(12, ge=1, le=30),
    user: dict | None = Depends(get_optional_user),
):
    return await compute_home(get_db(), user, limit)


@router.get("/similar/{product_id}")
async def similar_products(product_id: str, limit: int = Query(12, ge=1, le=30)):
    db = get_db()
    seed_doc = await db.products.find_one({"_id": to_object_id(product_id)})
    products = await _active_products(db)
    if not seed_doc:
        return _popular(products, limit, exclude={product_id})

    seed = _decorate(seed_doc)
    candidates = _rank(products, [seed], exclude={product_id}, copurchase=None, limit=_POOL)

    names = await _cat_names(db, {p.get("category_id") for p in candidates + [seed]})
    _attach(candidates, names)
    _attach([seed], names)

    context = (
        "The shopper is viewing this product:\n"
        + _brief(seed)
        + "\nRecommend the most similar alternatives (style, category, price band)."
    )
    ordered = await recommender.rerank(context, candidates, limit, cache_key=f"similar:{product_id}")
    return _finalize(candidates, ordered, limit)


@router.get("/cart")
async def cart_recommendations(
    product_ids: str = Query("", description="comma-separated product ids in the cart"),
    limit: int = Query(10, ge=1, le=30),
):
    db = get_db()
    ids = [x.strip() for x in product_ids.split(",") if x.strip()]
    products = await _active_products(db)
    by_id = {p["id"]: p for p in products}
    seeds = [by_id[i] for i in ids if i in by_id]
    exclude = set(ids)

    if not seeds:
        return _popular(products, limit, exclude=exclude)

    # "Customers who bought these also bought…" via order co-occurrence.
    copurchase: dict[str, int] = {}
    orders = await db.orders.find({"items.product_id": {"$in": ids}}).to_list(length=1000)
    for o in orders:
        prod_ids = {it.get("product_id") for it in o.get("items", [])}
        if not (prod_ids & exclude):
            continue
        for pid in prod_ids:
            if pid and pid not in exclude:
                copurchase[pid] = copurchase.get(pid, 0) + 1

    candidates = _rank(products, seeds, exclude=exclude, copurchase=copurchase, limit=_POOL)

    names = await _cat_names(db, {p.get("category_id") for p in candidates + seeds})
    _attach(candidates, names)
    _attach(seeds, names)

    context = (
        "The shopper currently has these items in their cart:\n"
        + "\n".join(_brief(s) for s in seeds[:12])
        + "\nRecommend complementary items that pair well and they may add to the order."
    )
    cache_key = "cart:" + "-".join(sorted(ids))
    ordered = await recommender.rerank(context, candidates, limit, cache_key)
    return _finalize(candidates, ordered, limit)
