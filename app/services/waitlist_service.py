"""Restock waitlist notifications.

Whenever a product save moves a size variant (or the whole product, for
variant-less items) from 0-or-less stock to available, every pending
waitlist row for that exact key is emailed automatically and marked
notified — no admin click required. Uses the exact same `variant_stock`
resolution the checkout stock check uses, so "in stock" always means the
same thing everywhere.
"""
from datetime import datetime, timezone

from app.models.common import to_object_id
from app.services.email_service import send_email
from app.services.pricing import variant_stock

_SITE_URL = "https://plantnursery.com"


def restocked_size_keys(before: dict, after: dict) -> set:
    """Which size_name keys (None = the base stock) went from
    0-or-less to available between the pre-update and post-update product doc.
    """
    names = {
        s.get("name")
        for s in (before.get("sizes") or []) + (after.get("sizes") or [])
        if isinstance(s, dict) and s.get("name")
    }
    names.add(None)
    return {n for n in names if variant_stock(before, n) < variant_stock(after, n)}


def _product_url(product_id: str) -> str:
    return f"{_SITE_URL}/product/{product_id}"


def _restock_email_html(product_title: str, sizes: list, url: str) -> str:
    real_sizes = [s for s in sizes if s]
    if not real_sizes:
        size_line = "back in stock"
    elif len(real_sizes) == 1:
        size_line = f"back in stock in <b>{real_sizes[0]}</b> size"
    else:
        size_line = "back in stock in these sizes: " + ", ".join(real_sizes)
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f0fdf4;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 0;">
      <tr><td align="center">
        <table role="presentation" width="480" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #dcfce7;">
          <tr><td style="background:#16a34a;height:6px;"></td></tr>
          <tr><td style="padding:36px 40px 8px;">
            <h1 style="margin:0 0 6px;font-size:20px;color:#064e3b;">🌿 It's back in stock!</h1>
            <p style="margin:0;color:#6b6b70;font-size:14px;line-height:20px;">
              <b>{product_title}</b> is {size_line} — you asked us to let you know the moment it
              returned, so grab it before it sells out again.
            </p>
          </td></tr>
          <tr><td align="center" style="padding:24px 40px 36px;">
            <a href="{url}" style="display:inline-block;background:#16a34a;color:#ffffff;text-decoration:none;
               padding:12px 28px;border-radius:10px;font-size:14px;font-weight:700;">Shop now 🌱</a>
          </td></tr>
        </table>
        <p style="margin:16px 0 0;color:#b5b5ba;font-size:11px;">MyGarden &middot; this is an automated message</p>
      </td></tr>
    </table>
  </body>
</html>"""


async def notify_restocked(db, product: dict, size_keys: set) -> int:
    """Email + mark-notified every pending waitlist row for `product` whose
    size_name is one of `size_keys`. Returns how many rows were resolved.
    Never raises — callers must treat this as best-effort (fire-and-forget).
    """
    if not size_keys:
        return 0
    product_id = str(product["_id"])
    pending = await db.waitlist.find({
        "product_id": product_id,
        "status": "pending",
        "size_name": {"$in": list(size_keys)},
    }).to_list(length=2000)
    if not pending:
        return 0

    await db.waitlist.update_many(
        {"_id": {"$in": [w["_id"] for w in pending]}},
        {"$set": {"status": "notified", "updated_at": datetime.now(timezone.utc)}},
    )

    by_user: dict[str, list] = {}
    for w in pending:
        by_user.setdefault(w["user_id"], []).append(w.get("size_name"))

    object_ids = []
    for uid in by_user:
        try:
            object_ids.append(to_object_id(uid))
        except Exception:
            continue

    emails: dict[str, str] = {}
    if object_ids:
        async for u in db.users.find({"_id": {"$in": object_ids}}, {"email": 1}):
            emails[str(u["_id"])] = u.get("email") or ""

    title = product.get("title", "Plant").strip()
    url = _product_url(product_id)
    sent = 0
    for uid, sizes in by_user.items():
        email = emails.get(uid)
        if not email:
            continue
        html = _restock_email_html(title, sizes, url)
        if send_email(email, f"🌿 Back in stock: {title}", html):
            sent += 1
    return sent


async def notify_restocked_safely(db, product: dict, size_keys: set) -> None:
    try:
        await notify_restocked(db, product, size_keys)
    except Exception as e:  # pragma: no cover
        print(f"[restock-notify] failed for product {product.get('_id')}: {e}")
