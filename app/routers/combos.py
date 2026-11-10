"""Bundle deals: "any 3 of these for ₹300".

The admin stores a pool of eligible entries in `product_ids`, each either a
bare product id (any size qualifies) or `"<id>::<size>"` for one exact
variant. The storefront needs to *show* that pool — name, photo, live price —
so the public reads below resolve it into real products and work out whether
the deal is a fixed bundle (pool == required quantity) or mix & match.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.combo import ComboIn
from app.models.common import serialize, to_object_id
from app.routers.products import _decorate

router = APIRouter(prefix="/combos", tags=["combos"])


def _variant(product: dict, size_name: str | None) -> dict | None:
    """The size the entry points at, or the first sellable one."""
    sizes = [s for s in (product.get("sizes") or []) if isinstance(s, dict)]
    if size_name:
        return next((s for s in sizes if s.get("name") == size_name), None)
    return next((s for s in sizes if (s.get("stock") or 0) > 0), sizes[0] if sizes else None)


def _entry(product: dict, size_name: str | None) -> dict | None:
    """One pickable line in a combo: a product plus the exact variant to buy."""
    variant = _variant(product, size_name)
    if size_name and variant is None:
        return None  # the admin picked a size that has since been removed
    images = (variant.get("images") if variant else None) or product.get("images") or []
    stock = (variant.get("stock") if variant else product.get("total_stock")) or 0
    return {
        "key": f"{product['id']}::{size_name}" if size_name else product["id"],
        "product_id": product["id"],
        "title": product.get("title", ""),
        "slug": product.get("slug"),
        "image": images[0] if images else None,
        "size_variant": variant.get("name") if variant else None,
        "pot_type": (variant.get("pot_type") if variant else None) or None,
        "sku": (variant.get("sku") if variant else None) or None,
        "price": (variant.get("price") if variant else None) or product.get("price") or 0,
        "mrp": (variant.get("mrp") if variant else None) or product.get("mrp"),
        "stock": stock,
        "in_stock": stock > 0,
    }


async def _resolve(db, combo: dict) -> dict:
    """Attach the resolved pool, the deal shape and the saving to one combo."""
    out = serialize(combo)
    raw = out.get("product_ids") or []

    wanted: dict[str, list[str | None]] = {}
    for token in raw:
        pid, _, size = str(token).partition("::")
        if len(pid) == 24:
            wanted.setdefault(pid, []).append(size or None)

    products: list[dict] = []
    if wanted:
        docs = await db.products.find(
            {"_id": {"$in": [to_object_id(pid) for pid in wanted]}, "is_active": True}
        ).to_list(length=200)
        by_id = {str(d["_id"]): _decorate(d) for d in docs}
        # Keep the admin's order: walk `raw`, not the Mongo result.
        for token in raw:
            pid, _, size = str(token).partition("::")
            product = by_id.get(pid)
            if not product:
                continue
            entry = _entry(product, size or None)
            if entry:
                products.append(entry)

    qty = int(out.get("qty") or 0)
    out["products"] = products
    out["pool_size"] = len(products)
    # A pool the same size as the requirement is a fixed bundle — there is
    # nothing for the customer to choose. Anything larger is mix & match.
    out["is_fixed"] = bool(products) and len(products) <= qty
    out["is_weight_based"] = out.get("weight_target") is not None

    cheapest = sorted(p["price"] for p in products)[:qty] if products else []
    out["regular_total"] = round(sum(cheapest), 2) if len(cheapest) == qty else None
    out["savings"] = (
        round(out["regular_total"] - float(out.get("price") or 0), 2)
        if out["regular_total"] and out["regular_total"] > float(out.get("price") or 0)
        else 0
    )
    return out


def _is_live(combo: dict, now: datetime) -> bool:
    """Active, and inside its window when the admin set one."""
    if not combo.get("active", True):
        return False
    start, end = combo.get("start_date"), combo.get("end_date")
    if start and now < start.replace(tzinfo=start.tzinfo or timezone.utc):
        return False
    if end and now > end.replace(tzinfo=end.tzinfo or timezone.utc):
        return False
    return True


def _validate_combo(body: ComboIn) -> None:
    """A manually-picked pool smaller than the Required Quantity can never
    trigger a bundle (num_bundles = pool // qty in _build_bill would always
    be 0) — that's never an intentional combo, so reject it outright rather
    than let an admin save something that silently never works. Doesn't
    apply to weight-matched combos: their "pool" is computed dynamically
    from live stock at checkout time, not a fixed list.
    """
    if body.weight_target is None and len(body.product_ids) < body.qty:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Select at least {body.qty} eligible item(s) to match the Required "
                f"Quantity ({body.qty}). Currently selected: {len(body.product_ids)}."
            ),
        )


@router.get("")
async def list_combos(all: bool = False):
    """Public: the live bundles with their pools resolved.

    `all=true` is the admin's view — every combo, including expired and
    switched-off ones, so the Plant Bundles table still lists them.
    """
    db = get_db()
    docs = await db.combos.find().sort("name", 1).to_list(100)
    now = datetime.now(timezone.utc)
    if not all:
        docs = [d for d in docs if _is_live(d, now)]
    return [await _resolve(db, d) for d in docs]


@router.get("/{cid}")
async def get_combo(cid: str):
    db = get_db()
    doc = await db.combos.find_one({"_id": to_object_id(cid)})
    if not doc:
        raise HTTPException(404, "Combo not found")
    return await _resolve(db, doc)

@router.post("", dependencies=[Depends(require_admin)])
async def create_combo(body: ComboIn):
    _validate_combo(body)
    db = get_db()
    res = await db.combos.insert_one(body.model_dump())
    doc = await db.combos.find_one({"_id": res.inserted_id})
    return serialize(doc)

@router.put("/{cid}", dependencies=[Depends(require_admin)])
async def update_combo(cid: str, body: ComboIn):
    _validate_combo(body)
    db = get_db()
    res = await db.combos.find_one_and_update(
        {"_id": to_object_id(cid)},
        {"$set": body.model_dump()},
        return_document=True
    )
    if not res:
        raise HTTPException(404, "Combo not found")
    return serialize(res)

@router.delete("/{cid}", dependencies=[Depends(require_admin)])
async def delete_combo(cid: str):
    db = get_db()
    res = await db.combos.delete_one({"_id": to_object_id(cid)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Combo not found")
    return {"ok": True}
