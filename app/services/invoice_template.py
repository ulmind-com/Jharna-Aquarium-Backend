"""Premium HTML invoice renderer for MyGarden.

Two render functions:
  render_pdf(order)   → HTML optimised for xhtml2pdf (uses Rs. for the rupee sign)
  render_email(order) → rich HTML for email clients (uses ₹ and modern CSS)
"""

from datetime import datetime, timezone
import base64
import urllib.request

# Cache fetched images so we don't re-download on every render
_img_cache: dict[str, str] = {}

def _get_image_b64(url: str) -> str:
    """Fetch an image URL and return a data:image/... URI for embedding."""
    if not url:
        return ""
    if url in _img_cache:
        return _img_cache[url]
    try:
        data = urllib.request.urlopen(url, timeout=8).read()
        ext = "jpeg"
        if url.lower().endswith(".png"):
            ext = "png"
        elif url.lower().endswith(".webp"):
            ext = "webp"
        data_uri = f"data:image/{ext};base64,{base64.b64encode(data).decode('ascii')}"
        _img_cache[url] = data_uri
        return data_uri
    except Exception:
        return url  # fallback to the original URL



def _fmt_money_pdf(amount: float | int | None) -> str:
    """Format for PDF: Rs. 1,234.00 (xhtml2pdf can't render ₹)."""
    if amount is None:
        return "Rs. 0.00"
    return f"Rs. {float(amount):,.2f}"


def _fmt_money_email(amount: float | int | None) -> str:
    """Format for email: ₹1,234.00 (browsers render ₹ fine)."""
    if amount is None:
        return "₹0.00"
    return f"₹{float(amount):,.2f}"


def _fmt_date(dt) -> str:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    if isinstance(dt, datetime):
        from datetime import timedelta
        ist = dt + timedelta(hours=5, minutes=30)
        return ist.strftime("%d %b %Y, %I:%M %p") + " IST"
    return str(dt)


def _extract(order: dict):
    """Pull common fields from the order document."""
    oid = str(order.get("_id", order.get("id", "")))
    short_id = oid[-8:].upper()
    created = order.get("created_at") or order.get("paid_at") or datetime.now(timezone.utc)
    addr = order.get("address", {})
    items = order.get("items", [])

    addr_parts = [addr.get("house"), addr.get("area"), addr.get("city"),
                  addr.get("state"), addr.get("pincode")]
    full_address = ", ".join(p for p in addr_parts if p)
    customer_name = addr.get("name", "Customer")
    customer_phone = addr.get("phone", "")

    payment_id = order.get("razorpay_payment_id", "")
    payment_method = ("Online - Razorpay" if order.get("payment_method") == "online"
                      else "Cash on Delivery")

    subtotal = float(order.get("subtotal", 0))
    discount = float(order.get("discount", 0))
    delivery = float(order.get("delivery", 0))
    delivery_free = order.get("delivery_free", False)
    total = float(order.get("amount", order.get("total", 0)))
    gst = order.get("gst", {})
    cgst = float(gst.get("cgst", 0))
    sgst = float(gst.get("sgst", 0))
    igst = float(gst.get("igst", 0))
    interstate = gst.get("interstate", False)

    return dict(
        oid=oid, short_id=short_id, created=created, addr=addr,
        items=items, full_address=full_address, customer_name=customer_name,
        customer_phone=customer_phone, payment_id=payment_id,
        payment_method=payment_method, subtotal=subtotal, discount=discount,
        delivery=delivery, delivery_free=delivery_free, total=total,
        cgst=cgst, sgst=sgst, igst=igst, interstate=interstate,
    )


# ═══════════════════════════════════════════════════════════════════
#  PDF INVOICE  (for xhtml2pdf — same layout as the original,
#  upgraded with premium visual design)
# ═══════════════════════════════════════════════════════════════════

def render_pdf(order: dict) -> str:
    d = _extract(order)
    fmt = _fmt_money_pdf
    item_rows = ""
    for idx, it in enumerate(d["items"]):
        img_url = it.get("image") or ""
        img_data = _get_image_b64(img_url) if img_url else ""
        img_cell = f'<img src="{img_data}" width="36" height="36" />' if img_data else ""
        title = it.get("title", "Product")
        variant = it.get("size_variant") or it.get("color", "")
        pot = it.get("pot_type") or it.get("size", "")
        meta = " | ".join(p for p in [variant, pot] if p)
        qty = it.get("qty", 1)
        price = float(it.get("price", 0))
        line = price * qty
        bg = "#faf7f2" if idx % 2 == 0 else "#ffffff"

        item_rows += f"""
        <tr style="background:{bg};">
          <td width="40" style="padding:6px 3px;border-bottom:1px solid #ebe7e0;vertical-align:top;text-align:center;">{img_cell}</td>
          <td style="padding:6px 5px;border-bottom:1px solid #ebe7e0;vertical-align:top;font-size:10px;color:#2c2320;">
            {title}{f'<br/><span style="font-size:8px;color:#9a9490;">{meta}</span>' if meta else ''}
          </td>
          <td width="30" style="padding:6px 3px;border-bottom:1px solid #ebe7e0;text-align:center;font-size:10px;color:#2c2320;">{qty}</td>
          <td width="75" style="padding:6px 3px;border-bottom:1px solid #ebe7e0;text-align:right;font-size:10px;color:#6b6560;">{fmt(price)}</td>
          <td width="85" style="padding:6px 3px;border-bottom:1px solid #ebe7e0;text-align:right;font-size:10px;font-weight:bold;color:#2c2320;">{fmt(line)}</td>
        </tr>"""

    def _sr(label, value, color="#2c2320", bold=False):
        fw = "font-weight:bold;" if bold else ""
        fs = "font-size:12px;" if bold else "font-size:10px;"
        return f"""<tr>
          <td style="padding:3px 6px;text-align:right;font-size:10px;color:#8c8680;">{label}</td>
          <td width="120" style="padding:3px 6px;text-align:right;{fs}{fw}color:{color};">{value}</td>
        </tr>"""

    summary = _sr("Subtotal", fmt(d["subtotal"]))
    if d["discount"] > 0:
        summary += _sr("Discount", f"- {fmt(d['discount'])}", color="#15803d")
    if d["delivery_free"] or d["delivery"] == 0:
        summary += _sr("Delivery", "FREE", color="#15803d")
    elif d["delivery"] > 0:
        summary += _sr("Delivery", fmt(d["delivery"]))
    if d["interstate"] and d["igst"] > 0:
        summary += _sr("IGST", fmt(d["igst"]))
    else:
        if d["cgst"] > 0:
            summary += _sr("CGST", fmt(d["cgst"]))
        if d["sgst"] > 0:
            summary += _sr("SGST", fmt(d["sgst"]))

    return f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Invoice #{d["short_id"]}</title>
  <style>
    @page {{ size: A4; margin: 1cm 1.2cm; }}
    body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11px; color: #333; margin: 0; padding: 0; }}
  </style>
</head>
<body>

  <!-- HEADER: Logo + Brand left, INVOICE right -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td width="50%" style="vertical-align:middle;">
        <span style="font-size:22px;color:#0a5c3e;font-weight:bold;vertical-align:middle;">Plant</span>
        <span style="font-size:22px;color:#008B5E;font-style:italic;vertical-align:middle;"> Nursery</span>
        <br/>
        <span style="font-size:8px;color:#999;letter-spacing:2px;">FARM-FRESH PLANTS &amp; GARDEN ESSENTIALS</span>
      </td>
      <td width="50%" style="text-align:right;vertical-align:top;">
        <span style="font-size:26px;font-weight:bold;color:#2c2320;">INVOICE</span><br/>
        <span style="font-size:11px;color:#888;">#{d["short_id"]}</span><br/>
        <span style="font-size:10px;color:#888;">{_fmt_date(d["created"])}</span>
      </td>
    </tr>
  </table>

  <!-- MAROON + GOLD ACCENT LINES -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0 0;">
    <tr><td style="background:#800000;height:2px;"></td></tr>
    <tr><td style="background:#D4AF37;height:1px;"></td></tr>
  </table>

  <!-- BILL TO / PAYMENT -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0;">
    <tr>
      <td width="55%" style="vertical-align:top;background:#faf7f2;padding:8px 10px;border-left:3px solid #D4AF37;">
        <p style="font-size:8px;font-weight:bold;color:#D4AF37;letter-spacing:2px;margin:0 0 3px;">BILL TO</p>
        <p style="font-size:13px;font-weight:bold;color:#2c2320;margin:0 0 2px;">{d["customer_name"]}</p>
        <p style="font-size:9px;color:#6b6560;margin:0;line-height:1.5;">{d["full_address"]}</p>
        {f'<p style="font-size:9px;color:#6b6560;margin:1px 0 0;">{d["customer_phone"]}</p>' if d["customer_phone"] else ""}
      </td>
      <td width="3%"></td>
      <td width="42%" style="text-align:right;vertical-align:top;background:#faf7f2;padding:8px 10px;border-left:3px solid #800000;">
        <p style="font-size:8px;font-weight:bold;color:#800000;letter-spacing:2px;margin:0 0 3px;">PAYMENT</p>
        <p style="font-size:13px;font-weight:bold;color:#2c2320;margin:0 0 2px;">{fmt(d["total"])}</p>
        <p style="font-size:9px;color:#6b6560;margin:0;">{d["payment_method"]}</p>
        {f'<p style="font-size:8px;color:#8c8680;margin:1px 0 0;">{d["payment_id"]}</p>' if d["payment_id"] else ""}
      </td>
    </tr>
  </table>

  <!-- ITEMS TABLE -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr style="background:#800000;">
      <td width="40" style="padding:5px 3px;font-size:7px;color:#D4AF37;">&nbsp;</td>
      <td style="padding:5px 5px;font-size:7px;font-weight:bold;color:#D4AF37;letter-spacing:1.5px;">ITEM</td>
      <td width="30" style="padding:5px 3px;font-size:7px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:center;">QTY</td>
      <td width="75" style="padding:5px 3px;font-size:7px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:right;">PRICE</td>
      <td width="85" style="padding:5px 3px;font-size:7px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:right;">TOTAL</td>
    </tr>
    {item_rows}
  </table>

  <!-- SUMMARY -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;">
    {summary}
    <tr><td colspan="2"><hr style="border:none;border-top:1px solid #D4AF37;margin:4px 0;" /></td></tr>
    <tr style="background:#800000;">
      <td style="padding:7px 6px;text-align:right;font-size:11px;font-weight:bold;color:#D4AF37;letter-spacing:1px;">Grand Total</td>
      <td width="120" style="padding:7px 6px;text-align:right;font-size:16px;font-weight:bold;color:#ffffff;">{fmt(d["total"])}</td>
    </tr>
  </table>

  <!-- GOLD LINE BELOW TOTAL -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="background:#D4AF37;height:2px;"></td></tr>
  </table>

  <hr style="border:none;border-top:1px solid #e5e5e5;margin:14px 0 8px;" />

  <!-- FOOTER -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="text-align:center;padding:2px 0;">
      <p style="font-size:11px;color:#800000;font-style:italic;font-weight:bold;margin:0 0 4px;">Thank you for shopping with MyGarden!</p>
      <p style="font-size:8px;color:#bbb;margin:0 0 1px;">This is a computer generated invoice and does not require a signature.</p>
      <p style="font-size:8px;color:#bbb;margin:0;">MyGarden &middot; Farm-Fresh Plants &amp; Garden Essentials</p>
    </td></tr>
  </table>

</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════
#  EMAIL INVOICE  (premium HTML for email clients — ₹ works fine)
# ═══════════════════════════════════════════════════════════════════

def render_email(order: dict) -> str:
    d = _extract(order)
    fmt = _fmt_money_email

    item_rows = ""
    for idx, it in enumerate(d["items"]):
        img_url = it.get("image") or ""
        img_cell = (
            f'<img src="{img_url}" width="48" height="48" '
            f'style="width:48px;height:48px;object-fit:cover;border-radius:8px;border:1px solid #e8e4de;" />'
        ) if img_url else (
            '<div style="width:48px;height:48px;border-radius:8px;background:#f3f0eb;"></div>'
        )
        title = it.get("title", "Product")
        color = it.get("color", "")
        size = it.get("size", "")
        meta = " · ".join(p for p in [color, size] if p)
        qty = it.get("qty", 1)
        price = float(it.get("price", 0))
        line = price * qty
        bg = "#faf8f5" if idx % 2 == 0 else "#ffffff"

        item_rows += f"""
        <tr style="background:{bg};">
          <td style="padding:14px 16px;border-bottom:1px solid #f0ede8;vertical-align:middle;">
            <table cellpadding="0" cellspacing="0" border="0"><tr>
              <td style="width:48px;vertical-align:middle;">{img_cell}</td>
              <td style="padding-left:14px;vertical-align:middle;">
                <div style="font-size:13px;color:#2c2320;font-weight:600;line-height:1.4;">{title}</div>
                {f'<div style="font-size:11px;color:#9a9490;margin-top:3px;">{meta}</div>' if meta else ''}
              </td>
            </tr></table>
          </td>
          <td style="padding:14px 8px;border-bottom:1px solid #f0ede8;text-align:center;font-size:13px;color:#2c2320;width:44px;">{qty}</td>
          <td style="padding:14px 8px;border-bottom:1px solid #f0ede8;text-align:right;font-size:13px;color:#8c8680;width:80px;">{fmt(price)}</td>
          <td style="padding:14px 16px;border-bottom:1px solid #f0ede8;text-align:right;font-size:14px;font-weight:700;color:#2c2320;width:90px;">{fmt(line)}</td>
        </tr>"""

    def _sr(label, value, color="#2c2320", bold=False):
        fw = "font-weight:700;" if bold else "font-weight:400;"
        fs = "font-size:14px;" if bold else "font-size:13px;"
        return f"""<tr>
          <td style="padding:5px 16px;text-align:right;{fw}{fs}color:#8c8680;">{label}</td>
          <td style="padding:5px 16px;text-align:right;{fw}{fs}color:{color};width:110px;">{value}</td>
        </tr>"""

    summary = _sr("Subtotal", fmt(d["subtotal"]))
    if d["discount"] > 0:
        summary += _sr("Discount", f"- {fmt(d['discount'])}", color="#15803d")
    if d["delivery_free"] or d["delivery"] == 0:
        summary += _sr("Delivery", "FREE", color="#15803d")
    elif d["delivery"] > 0:
        summary += _sr("Delivery", fmt(d["delivery"]))
    if d["interstate"] and d["igst"] > 0:
        summary += _sr("IGST", fmt(d["igst"]))
    else:
        if d["cgst"] > 0:
            summary += _sr("CGST", fmt(d["cgst"]))
        if d["sgst"] > 0:
            summary += _sr("SGST", fmt(d["sgst"]))

    return f"""\
<!doctype html>
<html>
<head><meta charset="utf-8" /><title>Invoice #{d["short_id"]}</title></head>
<body style="margin:0;padding:0;background:#f0ece6;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:28px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;overflow:hidden;border:1px solid #e8e4de;">

        <!-- TOP MAROON BANNER -->
        <tr><td style="background:#6b1520;padding:22px 32px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align:middle;">
              <table cellpadding="0" cellspacing="0"><tr>
                <td style="vertical-align:middle;">
                  <div style="font-size:22px;letter-spacing:-0.3px;">
                    <span style="color:#ffffff;font-weight:700;">Plant</span>
                    <span style="color:#8fe3bf;font-weight:500;font-style:italic;"> Nursery</span>
                  </div>
                  <div style="font-size:9px;color:#bfe8d4;margin-top:2px;letter-spacing:2px;">FARM-FRESH PLANTS &amp; GARDEN</div>
                </td>
              </tr></table>
            </td>
            <td style="text-align:right;vertical-align:middle;">
              <div style="font-size:20px;font-weight:800;color:#D4AF37;letter-spacing:2px;">INVOICE</div>
            </td>
          </tr></table>
        </td></tr>
        <!-- Gold accent line -->
        <tr><td style="background:#D4AF37;height:3px;font-size:1px;">&nbsp;</td></tr>

        <!-- INVOICE META -->
        <tr><td style="padding:22px 32px 16px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align:top;">
              <div style="font-size:11px;color:#8c8680;">Invoice No.</div>
              <div style="font-size:16px;font-weight:800;color:#6b1520;margin-top:2px;letter-spacing:0.5px;">#{d["short_id"]}</div>
            </td>
            <td style="text-align:right;vertical-align:top;">
              <div style="font-size:11px;color:#8c8680;">Date</div>
              <div style="font-size:13px;color:#2c2320;margin-top:2px;font-weight:500;">{_fmt_date(d["created"])}</div>
            </td>
          </tr></table>
        </td></tr>

        <!-- DIVIDER -->
        <tr><td style="padding:0 32px;"><div style="border-top:1px solid #e8e4de;"></div></td></tr>

        <!-- BILL TO + PAYMENT -->
        <tr><td style="padding:18px 32px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <!-- Bill To Card -->
            <td style="vertical-align:top;width:48%;background:#faf8f5;padding:14px 16px;border-left:3px solid #D4AF37;">
              <div style="font-size:9px;font-weight:700;color:#D4AF37;letter-spacing:2px;margin-bottom:8px;">BILL TO</div>
              <div style="font-size:15px;font-weight:700;color:#2c2320;">{d["customer_name"]}</div>
              <div style="font-size:12px;color:#6b6560;margin-top:5px;line-height:1.6;">{d["full_address"]}</div>
              {f'<div style="font-size:12px;color:#6b6560;margin-top:3px;">{d["customer_phone"]}</div>' if d["customer_phone"] else ''}
            </td>
            <td style="width:4%;"></td>
            <!-- Payment Card -->
            <td style="vertical-align:top;width:48%;background:#faf8f5;padding:14px 16px;border-left:3px solid #6b1520;text-align:right;">
              <div style="font-size:9px;font-weight:700;color:#6b1520;letter-spacing:2px;margin-bottom:8px;">PAYMENT</div>
              <div style="font-size:15px;font-weight:700;color:#2c2320;">{fmt(d["total"])}</div>
              <div style="font-size:12px;color:#6b6560;margin-top:5px;">{d["payment_method"]}</div>
              {f'<div style="font-size:11px;color:#9a9490;margin-top:3px;font-family:monospace;">{d["payment_id"]}</div>' if d["payment_id"] else ''}
            </td>
          </tr></table>
        </td></tr>

        <!-- ITEMS HEADER -->
        <tr><td style="padding:0 32px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr style="background:#6b1520;">
              <td style="padding:10px 16px;font-size:9px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;">ITEM DESCRIPTION</td>
              <td style="padding:10px 8px;font-size:9px;font-weight:700;color:#D4AF37;letter-spacing:1px;text-align:center;width:44px;">QTY</td>
              <td style="padding:10px 8px;font-size:9px;font-weight:700;color:#D4AF37;letter-spacing:1px;text-align:right;width:80px;">PRICE</td>
              <td style="padding:10px 16px;font-size:9px;font-weight:700;color:#D4AF37;letter-spacing:1px;text-align:right;width:90px;">TOTAL</td>
            </tr>
            {item_rows}
          </table>
        </td></tr>

        <!-- SUMMARY -->
        <tr><td style="padding:12px 32px 0;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="width:50%;"></td>
              <td style="width:50%;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  {summary}
                </table>
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- GRAND TOTAL BAR -->
        <tr><td style="padding:8px 32px 20px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="width:50%;"></td>
              <td style="width:50%;">
                <!-- Gold line above total -->
                <div style="border-top:2px solid #D4AF37;margin-bottom:0;"></div>
                <table width="100%" cellpadding="0" cellspacing="0" style="background:#6b1520;">
                  <tr>
                    <td style="padding:12px 16px;font-size:11px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;">GRAND TOTAL</td>
                    <td style="padding:12px 16px;text-align:right;font-size:18px;font-weight:800;color:#ffffff;width:110px;">{fmt(d["total"])}</td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- DIVIDER -->
        <tr><td style="padding:0 32px;"><div style="border-top:1px solid #e8e4de;"></div></td></tr>

        <!-- THANK YOU -->
        <tr><td style="padding:24px 32px 8px;text-align:center;">
          <div style="font-size:18px;color:#6b1520;font-style:italic;font-weight:500;">Thank you for your purchase!</div>
        </td></tr>

        <!-- DECORATIVE -->
        <tr><td style="text-align:center;padding:4px 0 20px;">
          <span style="color:#D4AF37;font-size:12px;">- - - - -</span>
        </td></tr>

        <!-- DIVIDER -->
        <tr><td style="padding:0 32px;"><div style="border-top:1px solid #e8e4de;"></div></td></tr>

        <!-- FOOTER -->
        <tr><td style="padding:18px 32px 12px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align:top;">
              <div style="font-size:11px;color:#8c8680;">This is a computer generated invoice</div>
              <div style="font-size:11px;color:#b5b0a8;margin-top:2px;">and does not require a signature.</div>
            </td>
            <td style="vertical-align:top;text-align:right;">
              <div style="font-size:11px;color:#8c8680;">MyGarden &middot; Farm-Fresh Plants &amp; Garden</div>
              <div style="font-size:11px;color:#b5b0a8;margin-top:2px;">MyGarden</div>
            </td>
          </tr></table>
        </td></tr>

        <!-- BOTTOM ACCENT -->
        <tr><td style="background:#D4AF37;height:3px;font-size:1px;">&nbsp;</td></tr>
        <tr><td style="background:#6b1520;height:6px;font-size:1px;">&nbsp;</td></tr>

      </table>
      <p style="margin:14px 0 0;color:#b5b0a8;font-size:11px;text-align:center;">The PDF invoice is attached to this email.</p>
    </td></tr>
  </table>
</body>
</html>"""


# Backward compat: keep `render` pointing to the PDF version
render = render_pdf
