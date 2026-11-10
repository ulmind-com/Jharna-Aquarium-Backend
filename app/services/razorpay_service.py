import razorpay

from app.core.config import settings

_client: razorpay.Client | None = None


def _get_client() -> razorpay.Client:
    global _client
    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise RuntimeError("Razorpay is not configured")
    if _client is None:
        _client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
    return _client


def create_order(amount_paise: int, receipt: str, currency: str = "INR") -> dict:
    client = _get_client()
    return client.order.create(
        {"amount": amount_paise, "currency": currency, "receipt": receipt}
    )


def fetch_payment(payment_id: str) -> dict:
    """Fetch the full gateway record for a captured payment (method, bank,
    UPI VPA / card, fee, contact, etc.)."""
    client = _get_client()
    return client.payment.fetch(payment_id)


def refund(payment_id: str, amount_paise: int | None = None) -> dict:
    """Refund a captured payment (full by default). Raises on failure."""
    client = _get_client()
    data = {"amount": amount_paise} if amount_paise else {}
    return client.payment.refund(payment_id, data)


def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    client = _get_client()
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            }
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_webhook_signature(payload: str, signature: str) -> bool:
    """Verify an incoming Razorpay webhook call is genuinely from Razorpay.
    `payload` must be the exact raw request body string (not a re-serialized
    copy) — the signature is computed over those exact bytes.
    """
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    client = _get_client()
    try:
        client.utility.verify_webhook_signature(payload, signature, settings.RAZORPAY_WEBHOOK_SECRET)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
