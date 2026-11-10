import asyncio
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.core.config import settings as app_settings
from app.db.mongodb import get_db
from app.deps import get_current_user, require_admin
from app.models.common import serialize, to_object_id
from app.models.order import OrderCreate, OrderVerify, BulkStatusUpdate
from app.routers.coupons import get_coupon
from app.services import razorpay_service, support
from app.services.pricing import (
    compute_delivery,
    coupon_discount,
    get_settings,
    resolve_price,
    variant_stock,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _resolve_item_image(prod: dict, size_name: str | None) -> str | None:
    """Return the best image for a specific size variant at order-creation
    time. Tries an exact/prefix variant match first (see
    `_matched_variant_image` — this also protects a checkout whose cart was
    added to before the admin renamed a variant), falling back to the
    product's default hero image when no variant was selected or none of
    today's variants can confidently be matched to it.
    """
    matched = _matched_variant_image(prod, size_name)
    if matched:
        return matched
    return (prod.get("images") or [None])[0]


def _matched_variant_image(prod: dict, size_name: str | None) -> str | None:
    """Only returns an image when `size_name` matches a size variant on `prod`
    and that variant now has a photo of its own. Tries an exact name match
    first, then — only when that fails — a prefix match (case/space
    insensitive), because the admin has been known to rename a variant after
    orders were placed against it (e.g. "Medium" -> "Medium (6 inch)"), which
    breaks an exact match for no reason a customer would understand. The
    prefix match is only trusted when it identifies exactly one variant; if
    the old name could plausibly mean more than one of today's variants, this
    returns None rather than guess.

    Never falls back to the product's generic image — this is used to
    retroactively refresh what an already-placed order displays, so it must
    never downgrade a stored image that may already be correct.
    """
    if not size_name:
        return None
    sizes = [s for s in (prod.get("sizes") or []) if isinstance(s, dict)]

    def _image_of(s: dict) -> str | None:
        images = s.get("images") or []
        return images[0] if images else None

    for s in sizes:
        if s.get("name") == size_name:
            return _image_of(s)

    needle = size_name.strip().lower()
    if not needle:
        return None
    candidates = [s for s in sizes if (s.get("name") or "").strip().lower().startswith(needle)]
    if len(candidates) == 1:
        return _image_of(candidates[0])
    return None


def _item_variant(item: dict) -> str | None:
    """Size variant of a stored order item. Orders written before the nursery
    migration keep the old wool-era `color` key, so read both."""
    return item.get("size_variant") or item.get("color")


def _refresh_item_images(cache: dict, items: list[dict] | None) -> None:
    """Point each order item's image at its variant's CURRENT photo when one
    now exists. Only mutates the in-memory dict being sent in a response or
    rendered into a PDF/email — the stored order document is never written
    back, so this is safe to call on every read.
    """
    for it in items or []:
        prod = cache.get(it.get("product_id"))
        if not prod:
            continue
        fresh = _matched_variant_image(prod, _item_variant(it))
        if fresh:
            it["image"] = fresh


async def _product_image_cache(db, order_docs: list[dict]) -> dict[str, dict]:
    """Batch-fetch every product referenced by a set of orders, keyed by id
    string, so refreshing images for a whole order list costs one query."""
    ids = {
        it["product_id"]
        for d in order_docs
        for it in (d.get("items") or [])
        if it.get("product_id")
    }
    object_ids = []
    for pid in ids:
        try:
            object_ids.append(to_object_id(pid))
        except Exception:
            continue
    cache: dict[str, dict] = {}
    if object_ids:
        async for p in db.products.find({"_id": {"$in": object_ids}}):
            cache[str(p["_id"])] = p
    return cache


STAGES = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"]

STATUS_MSG = {
    "confirmed": "Your order is confirmed and being packed 📦",
    "shipped": "Your order has been shipped 🚚",
    "out_for_delivery": "Your order is out for delivery 🛵",
    "delivered": "Your order has been delivered ✅",
    "cancelled": "Your order was cancelled",
}


def _combo_matches(combo: dict, product_id: str, size_name: str | None) -> bool:
    """Whether one cart line qualifies for this combo.

    `combo["product_ids"]` entries mean one of two things:
    - a bare product id -> any size variant of that product is eligible (this
      is the original, and still fully supported, meaning).
    - `"<product_id>::<size_name>"` -> only that exact size variant is
      eligible (admin picked specific variants, e.g. only the Large pot).
    """
    ids = combo.get("product_ids") or []
    if str(product_id) in ids:
        return True
    if size_name and f"{product_id}::{size_name}" in ids:
        return True
    return False


async def _build_bill(db, items_in, address, coupon, user_id=None):
    settings = await get_settings(db)
    order_items = []
    lines = []  # (line_total, {cgst, sgst, igst})
    subtotal = 0.0
    total_weight_grams = 0.0
    cart_state = []

    for it in items_in:
        prod = await db.products.find_one({"_id": to_object_id(it.product_id)})
        if not prod or not prod.get("is_active", True):
            raise HTTPException(status_code=400, detail="Product unavailable")
        # Stock check happens before any payment is even initiated — this
        # function backs both the /orders/quote preview and actual order
        # creation, and create_order runs before the Razorpay checkout modal
        # ever opens, so an oversell attempt is rejected up front.
        available = variant_stock(prod, it.size_variant)
        if it.qty > available:
            label = prod.get("title", "").strip() + (f" ({it.size_variant})" if it.size_variant else "")
            raise HTTPException(
                status_code=400,
                detail=f"Only {available} left of \"{label}\" — please lower the quantity.",
            )
        # Price for the exact size variant the customer chose.
        unit = resolve_price(prod, it.size_variant)["final_price"]
        line_total = unit * it.qty
        subtotal += line_total
        total_weight_grams += float(prod.get("shipping_weight") or 0) * it.qty
        comp = {
            "cgst": float(prod.get("cgst") or 0),
            "sgst": float(prod.get("sgst") or 0),
            "igst": float(prod.get("igst") or 0),
        }
        # A product with no GST of its own falls back to the store-wide rate from
        # Settings (tax_rate is a fraction, e.g. 0.05 -> 5%): half CGST + half
        # SGST within the state, the full rate as IGST outside it.
        if not any(comp.values()):
            store_rate = float(settings.tax_rate or 0) * 100
            comp = {
                "cgst": store_rate / 2,
                "sgst": store_rate / 2,
                "igst": store_rate,
            }
        
        cart_state.append({
            "product_id": it.product_id,
            "unit": unit,
            "qty": it.qty,
            "it": it,
            "prod": prod,
            "comp": comp,
            "unbundled_qty": it.qty,
            "line_total": line_total
        })

    combo_discount = 0.0
    now = datetime.now(timezone.utc)
    combos = await db.combos.find({"active": True}).to_list(100)
    for combo in combos:
        # Time validity check
        start_date = combo.get("start_date")
        if start_date and start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if start_date and now < start_date:
            continue
            
        end_date = combo.get("end_date")
        if end_date and end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        if end_date and now > end_date:
            continue

        available_units = []
        for state in cart_state:
            is_eligible = _combo_matches(combo, state["product_id"], state["it"].size_variant)
            if is_eligible and state["unbundled_qty"] > 0:
                available_units.extend([(state["unit"], state)] * state["unbundled_qty"])
                    
        # A bundle needs a positive size and a price. Rows saved before those
        # were validated (or edited straight in the database) can have neither,
        # and an unusable bundle must not take the whole checkout down with it:
        # every quote walks this list, so one bad row would break every cart.
        try:
            bundle_size = int(combo.get("qty") or 0)
            bundle_price = float(combo.get("price"))
        except (TypeError, ValueError):
            continue
        if bundle_size <= 0 or bundle_price < 0:
            continue

        available_units.sort(key=lambda x: x[0], reverse=True)
        num_bundles = len(available_units) // bundle_size

        if num_bundles > 0:
            items_to_bundle = num_bundles * bundle_size
            regular_price_of_bundled = sum(u[0] for u in available_units[:items_to_bundle])
            bundle_price_total = num_bundles * bundle_price
            
            discount_for_this_combo = regular_price_of_bundled - bundle_price_total
            if discount_for_this_combo > 0:
                combo_discount += discount_for_this_combo
                
                # Deduct these units from unbundled_qty
                sorted_state = sorted(cart_state, key=lambda x: x["unit"], reverse=True)
                units_to_remove = items_to_bundle
                for state in sorted_state:
                    is_eligible = _combo_matches(combo, state["product_id"], state["it"].size_variant)
                    if is_eligible:
                        take = min(state["unbundled_qty"], units_to_remove)
                        state["unbundled_qty"] -= take
                        units_to_remove -= take
                        if units_to_remove == 0:
                            break

    for state in cart_state:
        lines.append((state["line_total"], state["comp"]))
        order_items.append(
            {
                "product_id": state["it"].product_id,
                "title": state["prod"].get("title") or "Item",
                "price": state["unit"],
                "qty": state["it"].qty,
                "size_variant": state["it"].size_variant,
                "pot_type": state["it"].pot_type,
                "cgst": state["comp"]["cgst"],
                "sgst": state["comp"]["sgst"],
                "igst": state["comp"]["igst"],
                "image": _resolve_item_image(state["prod"], state["it"].size_variant),
            }
        )

    coupon_doc = await get_coupon(db, coupon, user_id)
    # The coupon discount is calculated on the subtotal.
    # The final discount is coupon_discount + combo_discount
    discount = (coupon_discount(coupon_doc, subtotal) if coupon_doc else 0.0) + combo_discount

    dest_state = getattr(address, "state", "") or ""
    deliv = compute_delivery(settings, subtotal - discount, dest_state, total_weight_grams)

    free_reason = "threshold" if deliv["free"] else None
    if coupon_doc and coupon_doc.get("free_shipping"):
        deliv["fee"] = 0.0
        deliv["free"] = True
        free_reason = "coupon"

    # Same-state order -> CGST + SGST from the product; different state -> IGST.
    shop_state = (settings.shop.state or "").strip().lower()
    dest_state_lower = dest_state.strip().lower()
    interstate = bool(shop_state and dest_state_lower and shop_state != dest_state_lower)

    total_cgst = total_sgst = total_igst = 0.0
    tax_items = []
    for oi, (line_total, comp) in zip(order_items, lines):
        share = (line_total / subtotal * discount) if subtotal else 0.0
        taxable = max(0.0, line_total - share)
        if interstate:
            i_cgst = i_sgst = 0.0
            i_igst = round(taxable * comp["igst"] / 100, 2)
        else:
            i_cgst = round(taxable * comp["cgst"] / 100, 2)
            i_sgst = round(taxable * comp["sgst"] / 100, 2)
            i_igst = 0.0
        total_cgst += i_cgst
        total_sgst += i_sgst
        total_igst += i_igst
        rate = comp["igst"] if interstate else (comp["cgst"] + comp["sgst"])
        tax_items.append({
            "title": oi["title"], "qty": oi["qty"], "rate": rate,
            "cgst": i_cgst, "sgst": i_sgst, "igst": i_igst,
            "taxable": round(taxable, 2), "tax": round(i_cgst + i_sgst + i_igst, 2),
        })
    total_cgst = round(total_cgst, 2)
    total_sgst = round(total_sgst, 2)
    total_igst = round(total_igst, 2)
    total_tax = round(total_cgst + total_sgst + total_igst, 2)

    gst = {
        "total": total_tax,
        "interstate": interstate,
        "cgst": total_cgst,
        "sgst": total_sgst,
        "igst": total_igst,
        "items": tax_items,  # per-product GST breakdown
    }

    total = round((subtotal - discount) + deliv["fee"] + total_tax, 2)

    # Cash on delivery is offered per order, not per account: it needs a
    # deliverable address and a total the courier is allowed to carry.
    cod = settings.cod
    cod_available = bool(
        cod.enabled
        and deliv["deliverable"]
        and (not cod.max_order or total <= cod.max_order)
    )

    bill = {
        "subtotal": round(subtotal, 2),
        "discount": discount,
        "delivery": deliv["fee"],
        "delivery_free": deliv["free"],
        "delivery_free_reason": free_reason,
        "distance_km": deliv["distance_km"],
        "deliverable": deliv["deliverable"],
        "tax": total_tax,
        "gst": gst,
        "total": total,
        "currency": settings.currency,          # display symbol (₹)
        "currency_code": settings.currency_code,  # ISO code for Razorpay (INR)
        "coupon_applied": discount > 0,
        "cod_available": cod_available,
        # One line the checkout can show under "Shipping method" once the
        # address is known, instead of the "enter your address" placeholder.
        "message": (
            "Free delivery · dispatched within 24 hours"
            if deliv["free"]
            else f"Standard delivery · {settings.currency}{deliv['fee']:.0f}"
        ),
    }
    return order_items, bill


@router.post("/quote")
async def quote(body: OrderCreate, user: dict = Depends(get_current_user)):
    """Preview the bill (delivery/tax/total) before placing the order."""
    db = get_db()
    _, bill = await _build_bill(db, body.items, body.address, body.coupon_code, user["id"])
    return bill

async def _decrement_stock(db, order_items):
    for it in order_items:
        prod = await db.products.find_one({"_id": to_object_id(it["product_id"])})
        if not prod:
            continue
        variant = _item_variant(it)
        sizes = [sz for sz in (prod.get("sizes") or []) if isinstance(sz, dict)]
        if sizes and variant and any(sz.get("name") == variant for sz in sizes):
            for sz in sizes:
                if sz.get("name") == variant:
                    sz["stock"] = max(0, int(sz.get("stock", 0)) - it["qty"])
            await db.products.update_one({"_id": prod["_id"]}, {"$set": {"sizes": sizes}})
        else:
            await db.products.update_one({"_id": prod["_id"]}, {"$inc": {"stock": -it["qty"]}})


async def _restore_stock(db, order_items):
    """Put stock back (inverse of _decrement_stock) — used on cancellation."""
    for it in order_items:
        prod = await db.products.find_one({"_id": to_object_id(it["product_id"])})
        if not prod:
            continue
        variant = _item_variant(it)
        sizes = [sz for sz in (prod.get("sizes") or []) if isinstance(sz, dict)]
        if sizes and variant and any(sz.get("name") == variant for sz in sizes):
            for sz in sizes:
                if sz.get("name") == variant:
                    sz["stock"] = int(sz.get("stock", 0)) + it["qty"]
            await db.products.update_one({"_id": prod["_id"]}, {"$set": {"sizes": sizes}})
        else:
            await db.products.update_one({"_id": prod["_id"]}, {"$inc": {"stock": it["qty"]}})


@router.post("")
async def create_order(body: OrderCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    order_items, bill = await _build_bill(db, body.items, body.address, body.coupon_code, user["id"])
    if not bill["deliverable"]:
        raise HTTPException(status_code=400, detail="Address is outside the delivery area")
    if bill["subtotal"] <= 0:
        raise HTTPException(status_code=400, detail="Empty order")

    method = "cod" if body.payment_method == "cod" else "online"
    if method == "cod" and not bill["cod_available"]:
        raise HTTPException(
            status_code=400,
            detail="Cash on delivery isn't available for this order — please pay online.",
        )

    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user["id"],
        "items": order_items,
        "address": body.address.model_dump(),
        "payment_method": method,
        "coupon_code": body.coupon_code,
        "is_gift": body.is_gift,
        "gift_note": body.gift_note,
        **bill,
        "amount": bill["total"],
        "status": "pending_payment",
        "razorpay_order_id": None,
        "razorpay_payment_id": None,
        "created_at": now,
    }
    res = await db.orders.insert_one(doc)
    our_id = str(res.inserted_id)

    # ── Cash on delivery: nothing to collect now, so the order is live the
    # moment it is placed (same side effects the paid path runs on capture).
    if method == "cod":
        placed = await db.orders.find_one_and_update(
            {"_id": res.inserted_id},
            {"$set": {"status": "placed", "placed_at": now}},
            return_document=True,
        )
        await _decrement_stock(db, placed["items"])
        if placed.get("coupon_code"):
            await db.coupons.update_one(
                {"code": placed["coupon_code"].strip().upper()}, {"$inc": {"used_count": 1}}
            )
        await _send_invoice_email_safely(db, placed)
        return {
            "id": our_id,
            "order_id": our_id,
            "payment_method": "cod",
            "status": "placed",
            "bill": bill,
            **{k: bill[k] for k in ("subtotal", "discount", "delivery", "tax", "total")},
        }

    # ── Online: open a Razorpay order the checkout modal can be handed.
    amount_paise = int(round(bill["total"] * 100))
    currency_code = bill.get("currency_code") or "INR"
    try:
        rp = razorpay_service.create_order(amount_paise, receipt=our_id, currency=currency_code)
    except Exception as e:
        # Never leave a payable order dangling in pending_payment when the
        # gateway never even saw it — that is exactly what shows up later as
        # a ghost order in the admin panel.
        await db.orders.update_one(
            {"_id": res.inserted_id},
            {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc)}},
        )
        detail = (
            "Online payment isn't configured for this store yet."
            if isinstance(e, RuntimeError)
            else f"Could not start the payment: {e}"
        )
        raise HTTPException(status_code=503 if isinstance(e, RuntimeError) else 502, detail=detail)

    await db.orders.update_one({"_id": res.inserted_id}, {"$set": {"razorpay_order_id": rp["id"]}})

    return {
        # `id` / `razorpay_amount` / `razorpay_currency` are what the storefront
        # checkout reads before it opens the Razorpay modal; the flatter
        # `order_id` / `amount` / `currency` keys are kept for older clients.
        "id": our_id,
        "order_id": our_id,
        "payment_method": "online",
        "status": "pending_payment",
        "razorpay_order_id": rp["id"],
        "razorpay_amount": amount_paise,
        "razorpay_currency": currency_code,
        "amount": amount_paise,
        "currency": currency_code,
        "key_id": app_settings.RAZORPAY_KEY_ID,
        "bill": bill,
        "prefill": {
            "name": body.address.name or user.get("name", ""),
            "contact": body.address.phone,
            "email": user.get("email", ""),
        },
    }


async def _mark_order_paid(db, order_id_str: str, razorpay_payment_id: str) -> dict | None:
    """Atomically transition an order to 'placed' exactly once, no matter how
    many times (or from where — client verify, webhook, webhook retries, or
    both racing) this is called for the same order.

    Returns the updated order doc only when THIS call performed the
    transition; None means some other call already handled it — callers must
    treat that as a normal success, not an error, and must NOT re-run stock/
    coupon/email side effects.

    Matches status != "placed" (not just "pending_payment") on purpose: if
    Razorpay confirms a real capture for an order that had been marked
    "cancelled" (e.g. a past signature-check edge case), that's still real
    money the customer paid — it should still be fulfilled, not left
    cancelled.
    """
    updated = await db.orders.find_one_and_update(
        {"_id": to_object_id(order_id_str), "status": {"$ne": "placed"}},
        {"$set": {
            "status": "placed",
            "razorpay_payment_id": razorpay_payment_id,
            "paid_at": datetime.now(timezone.utc),
        }},
        return_document=True,
    )
    if not updated:
        return None
    await _decrement_stock(db, updated["items"])
    if updated.get("coupon_code"):
        await db.coupons.update_one(
            {"code": updated["coupon_code"].strip().upper()}, {"$inc": {"used_count": 1}}
        )
    return updated


async def _send_invoice_email_safely(db, order_doc: dict) -> None:
    """Best-effort invoice email with PDF attachment — never raises, so it's
    safe to call from a background task (webhook) or inline (client verify).
    """
    try:
        from app.services.email_service import send_invoice_email
        from app.services.invoice_template import render_pdf
        from io import BytesIO
        from xhtml2pdf import pisa

        cache = await _product_image_cache(db, [order_doc])
        _refresh_item_images(cache, order_doc.get("items"))
        user_doc = await db.users.find_one({"_id": to_object_id(order_doc["user_id"])})
        email = user_doc.get("email", "") if user_doc else ""
        if not email:
            return
        pdf_bytes = None
        try:
            html_str = render_pdf(order_doc)
            buf = BytesIO()
            pisa.CreatePDF(html_str, dest=buf)
            pdf_bytes = buf.getvalue()
        except Exception as pe:
            print(f"[invoice-pdf] generation failed: {pe}")
        send_invoice_email(email, order_doc, pdf_bytes)
    except Exception as e:
        print(f"[invoice-email] failed to send: {e}")


@router.post("/verify")
async def verify_order(body: OrderVerify, user: dict = Depends(get_current_user)):
    db = get_db()
    order = await db.orders.find_one({"_id": to_object_id(body.order_id)})
    if not order or order["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found")

    ok = razorpay_service.verify_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    )
    if not ok:
        if order.get("status") != "placed":
            await db.orders.update_one({"_id": order["_id"]}, {"$set": {"status": "cancelled"}})
        raise HTTPException(status_code=400, detail="Payment verification failed")

    updated = await _mark_order_paid(db, str(order["_id"]), body.razorpay_payment_id)
    if updated:
        await _send_invoice_email_safely(db, updated)
    # updated is None when the webhook (or a retry of this same call) already
    # confirmed this order — still a success from the customer's perspective.

    return {"id": body.order_id, "order_id": body.order_id, "status": "confirmed"}


@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """Server-to-server payment confirmation from Razorpay itself — the
    reliable counterpart to /orders/verify, which depends on the customer's
    own browser still being alive right after payment. No auth dependency:
    Razorpay calls this directly, so authenticity comes from the signature,
    not a JWT. See _mark_order_paid for why this is safe to fire alongside
    (or instead of) the client-side path.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not app_settings.RAZORPAY_WEBHOOK_SECRET:
        # Not wired up in the Razorpay Dashboard yet on this deploy — stay
        # dormant rather than error, so nothing retry-storms an endpoint that
        # isn't configured.
        return {"status": "ignored"}

    if not razorpay_service.verify_webhook_signature(raw_body.decode("utf-8"), signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = json.loads(raw_body)
    if payload.get("event") != "payment.captured":
        return {"status": "ignored", "event": payload.get("event")}

    entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    rp_order_id = entity.get("order_id")
    payment_id = entity.get("id")
    if not rp_order_id or not payment_id:
        return {"status": "ignored", "reason": "missing order/payment id"}

    db = get_db()
    order = await db.orders.find_one({"razorpay_order_id": rp_order_id})
    if not order:
        return {"status": "ignored", "reason": "no matching order"}

    updated = await _mark_order_paid(db, str(order["_id"]), payment_id)
    if updated:
        # Fire-and-forget: Razorpay wants a fast response, the email can take
        # a moment (PDF render + send).
        asyncio.create_task(_send_invoice_email_safely(db, updated))

    return {"status": "ok"}





def _fmt_window(hours: float) -> str:
    if hours >= 24 and hours % 24 == 0:
        d = int(hours // 24)
        return f"{d} day" + ("s" if d != 1 else "")
    h = int(hours) if float(hours).is_integer() else hours
    return f"{h} hour" + ("s" if h != 1 else "")


@router.get("")
async def my_orders(user: dict = Depends(get_current_user)):
    db = get_db()
    # Hide abandoned online orders that were never paid — any online order
    # without a razorpay_payment_id is a ghost order (old or new).
    _no_ghosts = {"$nor": [{"payment_method": "online", "razorpay_payment_id": None}]}
    docs = await db.orders.find({
        "user_id": user["id"],
        **_no_ghosts,
    }).sort("created_at", -1).to_list(length=100)
    cache = await _product_image_cache(db, docs)
    out = [serialize(d) for d in docs]
    for o in out:
        _refresh_item_images(cache, o.get("items"))
    return out


@router.get("/admin/status-counts", dependencies=[Depends(require_admin)])
async def admin_status_counts():
    db = get_db()
    pipeline = [
        {"$match": {"$nor": [{"payment_method": "online", "razorpay_payment_id": None}]}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    results = await db.orders.aggregate(pipeline).to_list(length=None)
    counts = {r["_id"]: r["count"] for r in results}
    all_stages = STAGES + ["cancelled"]
    return {s: counts.get(s, 0) for s in all_stages}


def _orders_query(
    status: str | None,
    q: str | None,
    start_date: str | None,
    end_date: str | None,
    user_id: str | None,
) -> dict:
    """Shared filter-building for every admin orders listing (table view,
    Excel export, ...) so they can never quietly drift apart."""
    # Exclude ghost orders: online orders where payment was never completed.
    query: dict = {"$nor": [{"payment_method": "online", "razorpay_payment_id": None}]}

    if user_id:
        query["user_id"] = user_id

    if status:
        query["status"] = status

    if q:
        q = q.strip()
        search_val = q.lstrip("#")
        query["$or"] = [
            {"address.name": {"$regex": re.escape(search_val), "$options": "i"}},
            {"address.phone": {"$regex": re.escape(search_val), "$options": "i"}},
            {"$expr": {"$regexMatch": {"input": {"$toString": "$_id"}, "regex": re.escape(search_val), "options": "i"}}}
        ]

    if start_date or end_date:
        query["created_at"] = {}
        if start_date:
            try:
                dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                query["created_at"]["$gte"] = dt
            except ValueError:
                pass
        if end_date:
            try:
                dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                query["created_at"]["$lte"] = dt
            except ValueError:
                pass
        if not query["created_at"]:
            del query["created_at"]

    return query


@router.get("/admin/all", dependencies=[Depends(require_admin)])
async def all_orders(
    status: str | None = None,
    q: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user_id: str | None = None,
    limit: int = 100
):
    db = get_db()
    query = _orders_query(status, q, start_date, end_date, user_id)
    docs = await db.orders.find(query).sort("created_at", -1).to_list(length=limit)
    cache = await _product_image_cache(db, docs)
    out = [serialize(d) for d in docs]
    for o in out:
        _refresh_item_images(cache, o.get("items"))
    return out


def _short_id(oid) -> str:
    return f"#{str(oid)[-6:].upper()}"


def _fmt_dt(value) -> str:
    if not value:
        return ""
    return value.strftime("%d %b %Y, %I:%M %p")


def _payment_status(o: dict) -> str:
    if o.get("payment_method") == "online":
        return "Paid" if o.get("razorpay_payment_id") else "Unpaid"
    return (o.get("payment_method") or "").upper()


@router.get("/admin/export", dependencies=[Depends(require_admin)])
async def export_orders(
    status: str | None = None,
    q: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user_id: str | None = None,
):
    """Admin: download every order matching the current filters as a
    two-sheet Excel workbook (order summary + line-item detail). Read-only —
    touches nothing in the database.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from fastapi.responses import StreamingResponse
    from io import BytesIO

    db = get_db()
    query = _orders_query(status, q, start_date, end_date, user_id)
    docs = await db.orders.find(query).sort("created_at", -1).to_list(length=5000)

    user_ids = {d["user_id"] for d in docs if d.get("user_id")}
    emails: dict[str, str] = {}
    if user_ids:
        object_ids = []
        for uid in user_ids:
            try:
                object_ids.append(to_object_id(uid))
            except Exception:
                continue
        if object_ids:
            async for u in db.users.find({"_id": {"$in": object_ids}}, {"email": 1}):
                emails[str(u["_id"])] = u.get("email", "")

    wb = Workbook()
    bold = Font(bold=True)

    orders_ws = wb.active
    orders_ws.title = "Orders"
    orders_headers = [
        "Order ID", "Full Order ID", "Date Placed", "Paid At", "Status",
        "Payment Method", "Payment Status", "Customer Name", "Phone", "Email",
        "Delivery Address", "Item Count", "Items Summary",
        "Subtotal", "Discount", "Delivery Fee", "Tax", "Total",
        "Coupon Code", "Tracking ID", "Tracking URL",
    ]
    orders_ws.append(orders_headers)
    for cell in orders_ws[1]:
        cell.font = bold

    items_ws = wb.create_sheet("Order Items")
    items_headers = [
        "Order ID", "Date Placed", "Customer Name", "Phone", "Delivery Address",
        "Product ID", "Product Title", "Size Variant", "Pot Type", "Qty",
        "Unit Price", "Line Total", "Image URL",
    ]
    items_ws.append(items_headers)
    for cell in items_ws[1]:
        cell.font = bold

    for d in docs:
        oid = _short_id(d["_id"])
        placed = _fmt_dt(d.get("created_at"))
        addr = d.get("address") or {}
        name = addr.get("name", "")
        phone = addr.get("phone", "")
        email = emails.get(d.get("user_id"), "")
        full_address = ", ".join(
            p for p in [addr.get("house"), addr.get("area"), addr.get("city"), addr.get("state"), addr.get("pincode")] if p
        )
        items = d.get("items") or []
        items_summary = "; ".join(
            f"{it.get('qty', 0)}x {(it.get('title') or '').strip()}"
            + (f" ({_item_variant(it)})" if _item_variant(it) else "")
            for it in items
        )

        orders_ws.append([
            oid, str(d["_id"]), placed, _fmt_dt(d.get("paid_at")), d.get("status", ""),
            d.get("payment_method", ""), _payment_status(d), name, phone, email,
            full_address, len(items), items_summary,
            d.get("subtotal", 0), d.get("discount", 0), d.get("delivery", 0), d.get("tax", 0), d.get("amount", 0),
            d.get("coupon_code") or "", d.get("tracking_id") or "", d.get("tracking_url") or "",
        ])

        for it in items:
            items_ws.append([
                oid, placed, name, phone, full_address,
                str(it.get("product_id") or ""), (it.get("title") or "").strip(),
                _item_variant(it) or "", it.get("pot_type") or it.get("size") or "",
                it.get("qty", 0), it.get("price", 0),
                round((it.get("price") or 0) * (it.get("qty") or 0), 2),
                it.get("image") or "",
            ])

    for ws, headers in ((orders_ws, orders_headers), (items_ws, items_headers)):
        for i, header in enumerate(headers, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, min(40, len(header) + 4))

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    label = start_date[:10] if start_date else "all"
    if end_date and end_date[:10] != label:
        label += f"_to_{end_date[:10]}"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Orders_Royal_Wool_{label}.xlsx"'},
    )


@router.get("/admin/refunds", dependencies=[Depends(require_admin)])
async def admin_refunds():
    """All cancelled orders with their refund details (newest cancellation first)."""
    db = get_db()
    docs = await db.orders.find({"status": "cancelled"}).sort("cancelled_at", -1).to_list(length=500)
    return [serialize(d) for d in docs]


@router.post("/{order_id}/refund", dependencies=[Depends(require_admin)])
async def admin_refund(order_id: str):
    """Manually initiate / retry a Razorpay refund for a paid online order."""
    db = get_db()
    order = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_method") != "online" or not order.get("razorpay_payment_id"):
        raise HTTPException(status_code=400, detail="This order has no online payment to refund")
    if order.get("refund_status") == "initiated":
        raise HTTPException(status_code=400, detail="A refund is already initiated for this order")
    try:
        r = razorpay_service.refund(order["razorpay_payment_id"], int(round(order["amount"] * 100)))
    except Exception as e:
        await db.orders.update_one({"_id": order["_id"]}, {"$set": {"refund_status": "failed"}})
        raise HTTPException(status_code=502, detail=f"Refund failed: {e}")
    await db.orders.update_one(
        {"_id": order["_id"]}, {"$set": {"refund_id": r.get("id"), "refund_status": "initiated"}}
    )
    return {"refund_status": "initiated", "refund_id": r.get("id")}


@router.get("/{order_id}/payment", dependencies=[Depends(require_admin)])
async def admin_order_payment(order_id: str):
    """Live payment record from Razorpay for an online order — method, bank,
    UPI VPA / card, gateway fee, contact. The stored txn/coupon fields already
    come back with the order; this pulls the rest straight from the gateway."""
    db = get_db()
    order = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    pid = order.get("razorpay_payment_id")
    if not pid:
        raise HTTPException(status_code=400, detail="This order has no online payment")
    try:
        p = razorpay_service.fetch_payment(pid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch payment: {e}")
    card = p.get("card") or {}
    return {
        "id": p.get("id"),
        "status": p.get("status"),
        "captured": p.get("captured"),
        "method": p.get("method"),
        "amount": (p.get("amount") or 0) / 100,
        "currency": p.get("currency"),
        "bank": p.get("bank"),
        "wallet": p.get("wallet"),
        "vpa": p.get("vpa"),
        "card_last4": card.get("last4"),
        "card_network": card.get("network"),
        "card_type": card.get("type"),
        "email": p.get("email"),
        "contact": p.get("contact"),
        "fee": (p.get("fee") or 0) / 100,
        "tax": (p.get("tax") or 0) / 100,
        "created_at": p.get("created_at"),  # unix seconds
        "acquirer_data": p.get("acquirer_data"),
    }


@router.get("/{order_id}/invoice")
async def order_invoice(order_id: str, user: dict = Depends(get_current_user)):
    """Generate a premium PDF invoice for the customer to download."""
    db = get_db()
    doc = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not doc or (doc["user_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=404, detail="Order not found")

    cache = await _product_image_cache(db, [doc])
    _refresh_item_images(cache, doc.get("items"))

    from app.services.invoice_template import render_pdf
    from io import BytesIO
    from xhtml2pdf import pisa
    from fastapi.responses import StreamingResponse

    html_str = render_pdf(doc)
    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html_str, dest=pdf_buffer)

    if pisa_status.err:
        # Fallback: return HTML if PDF generation fails
        return HTMLResponse(content=html_str)

    pdf_buffer.seek(0)
    short_id = str(doc["_id"])[-8:].upper()
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Invoice_Royal_Wool_{short_id}.pdf"'
        },
    )


@router.get("/{order_id}")
async def get_order(order_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not doc or (doc["user_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=404, detail="Order not found")
    cache = await _product_image_cache(db, [doc])
    out = serialize(doc)
    _refresh_item_images(cache, out.get("items"))
    return out


# A customer may pull out while the order is still sitting with us. Once it has
# shipped it is in a courier's hands, so cancelling becomes a return instead.
CANCELLABLE = {"placed", "confirmed"}


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    reason: str = Body("", embed=True),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    doc = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not doc or doc["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found")

    status = doc.get("status")
    if status == "cancelled":
        raise HTTPException(status_code=409, detail="This order is already cancelled")
    if status not in CANCELLABLE:
        raise HTTPException(
            status_code=409,
            detail="This order has already shipped — please request a return instead.",
        )

    await db.orders.update_one(
        {"_id": doc["_id"]},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc),
            "cancelled_by": "customer",
            "cancel_reason": reason.strip()[:300],
        }},
    )
    await support.close_for_order(db, str(doc["_id"]), "Order cancelled")
    fresh = await db.orders.find_one({"_id": doc["_id"]})
    return serialize(fresh)


@router.patch("/{order_id}/status", dependencies=[Depends(require_admin)])
async def update_status(
    order_id: str, 
    status: str = Body(..., embed=True),
    tracking_id: str | None = Body(None, embed=True),
    tracking_url: str | None = Body(None, embed=True)
):
    if status not in STAGES + ["cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    db = get_db()
    
    update_data = {"status": status}
    if tracking_id:
        update_data["tracking_id"] = tracking_id
    if tracking_url:
        update_data["tracking_url"] = tracking_url

    res = await db.orders.find_one_and_update(
        {"_id": to_object_id(order_id)}, {"$set": update_data}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Order not found")

    # Count units sold once, and stamp the delivery time (drives the return
    # window), when the order is delivered.
    if status == "delivered" and not res.get("sold_counted"):
        for it in res.get("items", []):
            await db.products.update_one(
                {"_id": to_object_id(it["product_id"])}, {"$inc": {"sold_count": it["qty"]}}
            )
        await db.orders.update_one(
            {"_id": res["_id"]},
            {"$set": {"sold_counted": True, "delivered_at": datetime.now(timezone.utc)}},
        )

    # The support conversation belongs to a live order. Once the order is
    # delivered (or cancelled) the customer's chat thread is dropped on their
    # device, so any open handoff ticket for it is resolved here too.
    if status in ("delivered", "cancelled"):
        await support.close_for_order(db, str(res["_id"]), f"Order {status}")

    return serialize(res)


@router.patch("/admin/bulk-status", dependencies=[Depends(require_admin)])
async def bulk_update_status(body: BulkStatusUpdate):
    if body.status not in STAGES + ["cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    db = get_db()
    obj_ids = [to_object_id(id) for id in body.order_ids]
    
    # We fetch the orders first to see if they were already delivered
    orders = await db.orders.find({"_id": {"$in": obj_ids}}).to_list(length=None)
    
    # Perform the bulk update for the status field
    await db.orders.update_many(
        {"_id": {"$in": obj_ids}}, 
        {"$set": {"status": body.status}}
    )
    
    # If the new status is delivered, we must handle sold_count
    if body.status == "delivered":
        for o in orders:
            if not o.get("sold_counted"):
                for it in o.get("items", []):
                    await db.products.update_one(
                        {"_id": to_object_id(it["product_id"])}, {"$inc": {"sold_count": it["qty"]}}
                    )
                await db.orders.update_one(
                    {"_id": o["_id"]},
                    {"$set": {"sold_counted": True, "delivered_at": datetime.now(timezone.utc)}},
                )

    if body.status in ("delivered", "cancelled"):
        for o in orders:
            await support.close_for_order(db, str(o["_id"]), f"Order {body.status}")

    return {"modified_count": len(orders), "status": body.status}
