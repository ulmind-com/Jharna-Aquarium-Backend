"""Transactional email via Resend (https://resend.com).

Safe to call before configuration: if RESEND_API_KEY is unset it logs what it
would have sent (handy for local dev where the OTP prints to the server console)
and returns False, so nothing crashes.
"""
import requests

from app.core.config import settings

_RESEND_URL = "https://api.resend.com/emails"


def _from() -> str:
    name = (settings.MAIL_FROM_NAME or "").strip()
    return f"{name} <{settings.MAIL_ADDRESS}>" if name else settings.MAIL_ADDRESS


def send_email(to: str, subject: str, html: str) -> bool:
    if not settings.RESEND_API_KEY:
        print(f"[email] RESEND_API_KEY unset — would email {to}: {subject}")
        return False
    try:
        r = requests.post(
            _RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"from": _from(), "to": [to], "subject": subject, "html": html},
            timeout=15,
        )
        if r.status_code >= 400:
            print(f"[email] Resend error {r.status_code}: {r.text}")
            return False
        return True
    except Exception as e:  # pragma: no cover
        print(f"[email] send failed: {e}")
        return False


def send_otp_email(to: str, code: str, ttl_minutes: int) -> bool:
    return send_email(to, "Your verification code", _otp_html(code, ttl_minutes))


def send_invoice_email(to: str, order: dict, pdf_bytes: bytes | None = None) -> bool:
    """Send a premium HTML invoice email with the PDF attached."""
    from app.services.invoice_template import render_email
    oid = str(order.get("_id", order.get("id", "")))
    short_id = oid[-8:].upper()
    html = render_email(order)
    subject = f"Your MyGarden invoice · #{short_id}"

    if pdf_bytes and settings.RESEND_API_KEY:
        import base64
        try:
            r = requests.post(
                _RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": _from(),
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    "attachments": [{
                        "filename": f"Invoice_Plant_Nursery_{short_id}.pdf",
                        "content": base64.b64encode(pdf_bytes).decode("ascii"),
                    }],
                },
                timeout=30,
            )
            if r.status_code >= 400:
                print(f"[email] Resend error {r.status_code}: {r.text}")
                return False
            return True
        except Exception as e:
            print(f"[email] send failed: {e}")
            return False
    else:
        return send_email(to, subject, html)


def _otp_html(code: str, ttl_minutes: int) -> str:
    boxes = "".join(
        f'<span style="display:inline-block;min-width:44px;padding:12px 0;margin:0 4px;'
        f'background:#F7ECE2;border-radius:10px;font-size:26px;font-weight:700;'
        f'letter-spacing:2px;color:#1c1613;text-align:center;">{d}</span>'
        for d in code
    )
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f7f9;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 0;">
      <tr><td align="center">
        <table role="presentation" width="440" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #eceae7;">
          <tr><td style="background:#F26A21;height:6px;"></td></tr>
          <tr><td style="padding:36px 40px 8px;">
            <h1 style="margin:0 0 6px;font-size:20px;color:#1c1613;">Verify your email</h1>
            <p style="margin:0;color:#6b6b70;font-size:14px;line-height:20px;">
              Use the code below to finish creating your account. It expires in {ttl_minutes} minutes.
            </p>
          </td></tr>
          <tr><td align="center" style="padding:24px 40px;">{boxes}</td></tr>
          <tr><td style="padding:0 40px 36px;">
            <p style="margin:0;color:#9a9a9f;font-size:12px;line-height:18px;">
              Didn't request this? You can safely ignore this email — no account is created until the code is entered.
            </p>
          </td></tr>
        </table>
        <p style="margin:16px 0 0;color:#b5b5ba;font-size:11px;">MyGarden · this is an automated message</p>
      </td></tr>
    </table>
  </body>
</html>"""
