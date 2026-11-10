"""Customer-support chat agent for the nursery.

Two very different things happen in this file, on purpose:

1. **Quick actions** (`run_action`) — tracking, cancelling, and handing over to
   a human — are answered by plain Python against the database. They are the
   things a customer actually taps, so they must never depend on a model being
   up, fast, or in the mood to call a tool. Pressing "Cancel this order" either
   cancels the order or explains exactly why it can't; it can't time out into
   "sorry, I'm having trouble".

2. **Free text** (`reply`) — anything typed in the box — goes to Groq with the
   order and store policy in the system prompt, plus tools so the model can run
   the same deterministic actions when the customer asks for them in prose.

Nothing about the conversation is stored. The transcript lives in the browser
and is dropped when the order reaches its end state; only a human-handoff
ticket survives, in `app.services.support`.
"""
import asyncio
import json

import requests

from app.core.config import settings
from app.models.common import to_object_id
from app.services import support
from app.services.pricing import get_settings

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

STAGES = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"]
CANCELLABLE = {"placed", "confirmed"}
# End states: the order is done, so the chat about it is done too.
FINAL = {"delivered", "cancelled"}

# The long label heads the order card; the short one reads naturally mid-
# sentence ("currently confirmed").
STAGE_SHORT = {
    "placed": "placed",
    "confirmed": "confirmed",
    "shipped": "shipped",
    "out_for_delivery": "out for delivery",
    "delivered": "delivered",
    "cancelled": "cancelled",
}

STAGE_LABEL = {
    "placed": "Order placed",
    "confirmed": "Confirmed & being packed",
    "shipped": "Shipped",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}

STATUS_LINE = {
    "placed": "We've got your order and the nursery is getting it ready 🌱",
    "confirmed": "Your plants are being potted and packed right now 📦",
    "shipped": "Your order has left the nursery and is on its way 🚚",
    "out_for_delivery": "Out for delivery — it should reach you today 🛵",
    "delivered": "This order was delivered ✅",
    "cancelled": "This order was cancelled.",
}

CANCEL_REASONS = [
    "Ordered by mistake",
    "Found a better price",
    "Delivery is too slow",
    "Changed my mind",
]

# Free-text prompts offered when there's no order in context.
SUGGESTIONS = [
    "Where's my order?",
    "Plant care tips",
    "Delivery charges",
    "Offers & coupons",
    "Plant guarantee",
    "Talk to a human",
]


# ───────────────────────── helpers ─────────────────────────

def _key() -> str:
    return settings.GROQ_AGENT_API_KEY or settings.GROQ_API_KEY


def _groq(messages: list[dict], tools: list | None = None) -> dict:
    payload: dict = {
        "model": settings.GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
        # gpt-oss style models spend tokens on hidden reasoning before they
        # write anything — with a small budget the visible answer comes back
        # empty. Keep reasoning short and leave room for the actual reply.
        "max_tokens": 1200,
        "reasoning_effort": "low",
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    resp = requests.post(
        _GROQ_URL,
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
        json=payload,
        timeout=max(settings.GROQ_TIMEOUT, 12) + 8,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


async def _order(db, user, order_id):
    if not order_id:
        return None
    try:
        o = await db.orders.find_one({"_id": to_object_id(order_id)})
    except Exception:
        o = None
    return o if (o and o.get("user_id") == user["id"]) else None


async def _latest_open_order(db, user):
    """The order a customer most likely wants to talk about: the newest one
    that hasn't finished yet, else the newest one overall."""
    docs = await db.orders.find({"user_id": user["id"]}).sort("created_at", -1).to_list(length=20)
    docs = [d for d in docs if not (d.get("payment_method") == "online" and not d.get("razorpay_payment_id"))]
    for d in docs:
        if d.get("status") not in FINAL:
            return d
    return docs[0] if docs else None


def short_id(order) -> str:
    return str(order["_id"])[-6:].upper()


def order_card(order: dict | None, currency: str = "₹") -> dict | None:
    """Compact, UI-ready snapshot of an order for the chat header."""
    if not order:
        return None
    status = order.get("status") or "placed"
    return {
        "id": str(order["_id"]),
        "short": short_id(order),
        "status": status,
        "status_label": STAGE_LABEL.get(status, status.replace("_", " ").title()),
        "status_short": STAGE_SHORT.get(status, status.replace("_", " ")),
        "status_line": STATUS_LINE.get(status, "We're on it."),
        "stage_index": STAGES.index(status) if status in STAGES else -1,
        "stages": [{"key": s, "label": STAGE_LABEL[s]} for s in STAGES],
        "cancellable": status in CANCELLABLE,
        "final": status in FINAL,
        "total": order.get("amount"),
        "currency": currency,
        "tracking_id": order.get("tracking_id"),
        "tracking_url": order.get("tracking_url"),
        "placed_at": (order.get("created_at").isoformat() if order.get("created_at") else None),
        "items": [
            {
                "product_id": str(it.get("product_id") or ""),
                "title": it.get("title"),
                "image": it.get("image"),
                "qty": it.get("qty"),
                "size_variant": it.get("size_variant"),
            }
            for it in (order.get("items") or [])
        ][:6],
    }


def actions_for(order: dict | None) -> list[dict]:
    """The chips shown under a reply — always in step with the live order."""
    if not order:
        return [
            {"id": "orders", "label": "Where's my order?", "icon": "pin"},
            {"id": "care", "label": "Plant care help", "icon": "leaf"},
            {"id": "human", "label": "Talk to a human", "icon": "headset"},
        ]
    status = order.get("status")
    out = [{"id": "track", "label": "Where's my order?", "icon": "pin"}]
    if status in CANCELLABLE:
        out.append({"id": "cancel", "label": "Cancel this order", "icon": "cancel", "tone": "danger"})
    if status == "delivered":
        out.append({"id": "guarantee", "label": "Plant not doing well?", "icon": "leaf"})
    if status == "shipped" or status == "out_for_delivery":
        out.append({"id": "reschedule", "label": "Change delivery date", "icon": "calendar"})
    out.append({"id": "human", "label": "Talk to a human", "icon": "headset"})
    return out


async def _human_line(db) -> str:
    s = await get_settings(db)
    bits = []
    if s.shop.phone:
        bits.append(f"call **{s.shop.phone}**")
    if getattr(s, "support", None) and getattr(s.support, "whatsapp", ""):
        bits.append(f"WhatsApp **{s.support.whatsapp}**")
    if s.shop.email:
        bits.append(f"email **{s.shop.email}**")
    return " or ".join(bits) if bits else "reach us from the Support page"


# ───────────────────────── openers & suggestions ─────────────────────────

async def opening(db, user: dict, order_id: str | None = None, product_id: str | None = None) -> dict:
    """Everything the chat panel needs to draw its first screen."""
    s = await get_settings(db)
    order = await _order(db, user, order_id) or await _latest_open_order(db, user)
    name = (user.get("name") or "there").split(" ")[0]
    card = order_card(order, s.currency)

    lines = [f"Hi {name} 👋 I'm Sage, your nursery support assistant."]
    if card:
        lines.append(f"Let's sort out your order — what's the issue?")
        lines.append(f"You're asking about order **#{card['short']}** — currently {card['status_short']}.")
    else:
        lines.append("Ask me about delivery, offers, or how to keep your plants happy 🌿")

    return {
        "greeting": lines,
        "order": card,
        "actions": actions_for(order),
        "questions": SUGGESTIONS if not order else [],
        "prompt": "What can I help you with?",
    }


async def suggestions_for(db, user, order_id) -> list[str]:
    """Back-compat: plain string prompts for the older chat surface."""
    order = await _order(db, user, order_id)
    if not order:
        return SUGGESTIONS
    return [a["label"] for a in actions_for(order)]


# ───────────────────────── deterministic actions ─────────────────────────

async def _track(db, user, order, s) -> dict:
    if not order:
        return {"reply": "I don't see an active order on your account yet. Once you place one, I can track it here.", "order": None}
    card = order_card(order, s.currency)
    parts = [f"**Order #{card['short']}** — {card['status_label']}.", card["status_line"]]
    if card.get("tracking_id"):
        parts.append(f"Tracking ID: `{card['tracking_id']}`")
    if card["status"] in CANCELLABLE:
        parts.append("It hasn't shipped yet, so you can still cancel it from here.")
    return {"reply": "\n\n".join(parts), "order": card, "timeline": True}


async def _cancel_prompt(db, user, order, s) -> dict:
    if not order:
        return {"reply": "I couldn't find that order.", "order": None}
    card = order_card(order, s.currency)
    if card["status"] == "cancelled":
        return {"reply": f"Order **#{card['short']}** is already cancelled. Any online payment is refunded to the original method within 5–7 working days.", "order": card}
    if not card["cancellable"]:
        human = await _human_line(db)
        return {
            "reply": f"Order **#{card['short']}** has already {('been delivered' if card['status'] == 'delivered' else 'left the nursery')}, so it can't be cancelled from here. Our {s.plant_guarantee.days}-day plant guarantee still covers it — or {human} and the team will help.",
            "order": card,
            "actions": [{"id": "human", "label": "Talk to a human", "icon": "headset"}],
        }
    return {
        "reply": f"Just to confirm — cancel order **#{card['short']}** ({s.currency}{card['total']})? Tell me why and I'll do it right away.",
        "order": card,
        "confirm": {
            "action": "cancel_confirm",
            "reasons": CANCEL_REASONS,
            "cta": "Yes, cancel it",
            "dismiss": "Keep my order",
        },
    }


async def _cancel_confirm(db, user, order, s, reason: str) -> dict:
    if not order:
        return {"reply": "I couldn't find that order.", "order": None}
    status = order.get("status")
    if status == "cancelled":
        return {"reply": "That order is already cancelled.", "order": order_card(order, s.currency)}
    if status not in CANCELLABLE:
        return await _cancel_prompt(db, user, order, s)

    from datetime import datetime, timezone
    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc),
            "cancelled_by": "customer",
            "cancel_reason": (reason or "Cancelled from support chat")[:300],
        }},
    )
    # Put the plants back on the shelf.
    for it in (order.get("items") or []):
        try:
            await db.products.update_one(
                {"_id": to_object_id(it.get("product_id"))},
                {"$inc": {"stock": int(it.get("qty") or 0)}},
            )
        except Exception:
            pass

    await support.close_for_order(db, str(order["_id"]), "Order cancelled")
    fresh = await db.orders.find_one({"_id": order["_id"]})
    card = order_card(fresh, s.currency)
    refund = (
        "Your payment will be refunded to the original method within 5–7 working days."
        if order.get("payment_method") == "online"
        else "Nothing was charged, so there's nothing to refund."
    )
    return {
        "reply": f"Done — order **#{card['short']}** is cancelled. {refund}",
        "order": card,
        "done": True,
        "actions": [{"id": "human", "label": "Talk to a human", "icon": "headset"}],
    }


async def _human(db, user, order, s, note: str, transcript, product=None) -> dict:
    topic = f"Order #{short_id(order)}" if order else (f"Product: {product.get('title')}" if product else "General enquiry")
    ticket = await support.create_ticket(
        db, user, order=order, product=product, topic=topic, message=note, transcript=transcript
    )
    human = await _human_line(db)
    hours = getattr(getattr(s, "support", None), "hours", "") or ""
    tail = f" {hours}." if hours else ""
    return {
        "reply": (
            f"I've passed this to the nursery team 🌿 They can see "
            f"{'order #' + short_id(order) if order else 'your account'} and will get back to you on "
            f"{user.get('phone') or user.get('email') or 'your registered contact'}.\n\n"
            f"In a hurry? You can {human}.{tail}"
        ),
        "order": order_card(order, s.currency),
        "ticket_id": ticket.get("id"),
        "escalated": True,
    }


async def _guarantee(db, user, order, s) -> dict:
    human = await _human_line(db)
    return {
        "reply": (
            f"Sorry to hear that 🌱 Our **{s.plant_guarantee.days}-day plant guarantee** covers it — send a photo of the plant "
            f"and we'll replace it free. Tap *Talk to a human* and the team will take it from there, or {human}."
        ),
        "order": order_card(order, s.currency),
        "actions": [{"id": "human", "label": "Talk to a human", "icon": "headset"}],
    }


async def _reschedule(db, user, order, s) -> dict:
    human = await _human_line(db)
    return {
        "reply": (
            f"Your order is already with the courier, so the delivery date is changed on their side. "
            f"Tell me the date that suits you and I'll pass it to the team — or {human}."
        ),
        "order": order_card(order, s.currency),
        "actions": [{"id": "human", "label": "Talk to a human", "icon": "headset"}],
    }


async def _orders_overview(db, user, s) -> dict:
    docs = await db.orders.find({"user_id": user["id"]}).sort("created_at", -1).to_list(length=5)
    if not docs:
        return {"reply": "You haven't placed an order yet. When you do, you can track or cancel it right here 🌿", "order": None}
    lines = ["Here are your recent orders:"]
    for d in docs:
        lines.append(f"• **#{short_id(d)}** — {STAGE_LABEL.get(d.get('status'), d.get('status'))}")
    active = next((d for d in docs if d.get("status") not in FINAL), docs[0])
    return {"reply": "\n".join(lines), "order": order_card(active, s.currency), "actions": actions_for(active)}


async def run_action(
    db,
    user: dict,
    action: str,
    order_id: str | None = None,
    product_id: str | None = None,
    reason: str = "",
    transcript: list[dict] | None = None,
) -> dict:
    """Answer a tapped quick action without going anywhere near the model."""
    s = await get_settings(db)
    order = await _order(db, user, order_id)
    if not order and action in {"track", "cancel", "cancel_confirm", "guarantee", "reschedule", "human"}:
        order = await _latest_open_order(db, user)

    product = None
    if product_id:
        try:
            product = await db.products.find_one({"_id": to_object_id(product_id)})
        except Exception:
            product = None

    if action == "track":
        out = await _track(db, user, order, s)
    elif action == "cancel":
        out = await _cancel_prompt(db, user, order, s)
    elif action == "cancel_confirm":
        out = await _cancel_confirm(db, user, order, s, reason)
    elif action == "human":
        out = await _human(db, user, order, s, reason, transcript, product)
    elif action == "guarantee":
        out = await _guarantee(db, user, order, s)
    elif action == "reschedule":
        out = await _reschedule(db, user, order, s)
    elif action == "orders":
        out = await _orders_overview(db, user, s)
    elif action == "care":
        out = {
            "reply": "Happy to help 🌿 Tell me which plant it is and what you're seeing — yellow leaves, droopy stems, no new growth — and I'll give you a care plan.",
            "order": order_card(order, s.currency),
        }
    else:
        out = {"reply": "I'm not sure about that one — try one of the options below.", "order": order_card(order, s.currency)}

    out.setdefault("actions", actions_for(order))
    out.setdefault("order", order_card(order, s.currency))
    return out


# ───────────────────────── free-text chat ─────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "track_order",
            "description": "Look up the live status of the customer's current order.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Cancel the customer's current order. Only call this after the customer has clearly confirmed they want it cancelled and has given a reason.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string", "description": "Why the customer is cancelling"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "talk_to_human",
            "description": "Hand the conversation to the human nursery team. Call this when the customer asks for a person, or when the issue needs a human (damage, refunds, complaints).",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string", "description": "One-line summary of what the customer needs"}},
                "required": ["note"],
            },
        },
    },
]


async def _system_prompt(db, user: dict, order: dict | None) -> str:
    s = await get_settings(db)
    human = await _human_line(db)
    lines = [
        f"You are 'Sage 🌿', the support and plant-care assistant for {s.shop.name}, a premium online plant nursery.",
        "Help with orders, tracking, cancellation, delivery, payments, offers — and real plant care advice (light, watering, soil, repotting, pests).",
        "Be warm, concrete and short: 2-4 sentences, no bullet-point walls, no markdown headings.",
        f"Currency: {s.currency}. Payments are online via UPI/Card/Netbanking (Razorpay).",
        f"Plant guarantee: {s.plant_guarantee.days} days — if the plant doesn't make it, we replace it free.",
        f"If the customer wants a person, use the talk_to_human tool and tell them they can also {human}.",
        "Use tools to act. Never claim an action happened unless the tool returned success. Never invent order numbers, dates or tracking IDs.",
    ]
    if order:
        card = order_card(order, s.currency)
        items = ", ".join(f"{i['title']} (x{i['qty']})" for i in card["items"]) or "—"
        lines.append(
            f"CURRENT ORDER #{card['short']}: status={card['status']}, total={s.currency}{card['total']}, "
            f"payment={'online' if order.get('payment_method') == 'online' else 'COD'}, "
            f"cancellable={'yes' if card['cancellable'] else 'no (already shipped/delivered)'}. Items: {items}. Focus on THIS order."
        )
    else:
        docs = await db.orders.find({"user_id": user["id"]}).sort("created_at", -1).to_list(length=5)
        if docs:
            lines.append("Recent orders: " + "; ".join(f"#{short_id(d)} ({d.get('status')})" for d in docs))
    return "\n".join(lines)


async def _run_tool(db, user, order, name, args, transcript) -> dict:
    s = await get_settings(db)
    if name == "track_order":
        return await _track(db, user, order, s)
    if name == "cancel_order":
        return await _cancel_confirm(db, user, order, s, args.get("reason") or "Cancelled from support chat")
    if name == "talk_to_human":
        return await _human(db, user, order, s, args.get("note") or "", transcript)
    return {"error": "Unknown action"}


async def reply(db, user: dict, history: list[dict], order_id: str | None = None) -> dict:
    """Answer free text. Always returns a dict: the message plus the live order
    card and fresh action chips, so the UI never drifts from reality."""
    s = await get_settings(db)
    order = await _order(db, user, order_id) or await _latest_open_order(db, user)

    def wrap(text: str, extra: dict | None = None) -> dict:
        out = {"reply": text, "order": order_card(order, s.currency), "actions": actions_for(order)}
        out.update(extra or {})
        return out

    if not _key():
        human = await _human_line(db)
        return wrap(f"I can still track or cancel your order with the buttons below. For anything else, {human}.")

    messages = [{"role": "system", "content": await _system_prompt(db, user, order)}]
    for m in (history or [])[-10:]:
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = str(m.get("content", "")).strip()[:1000]
        if content:
            messages.append({"role": role, "content": content})
    if len(messages) == 1:
        return wrap("Hi! I'm Sage 🌿 How can I help you today?")

    escalated = False
    try:
        for _ in range(3):
            msg = await asyncio.to_thread(_groq, messages, TOOLS if order else TOOLS[2:])
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                text = (msg.get("content") or "").strip()
                if not text:
                    # Reasoning models sometimes return an empty body; ask once
                    # more without tools rather than apologising to the customer.
                    text = ((await asyncio.to_thread(_groq, messages, None)).get("content") or "").strip()
                if not text:
                    text = "I'm here — could you say that once more? Or pick one of the options below."
                if order:
                    order = await db.orders.find_one({"_id": order["_id"]}) or order
                return wrap(text, {"escalated": escalated} if escalated else None)

            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                result = await _run_tool(db, user, order, name, args, history)
                escalated = escalated or bool(result.get("escalated"))
                if order:
                    order = await db.orders.find_one({"_id": order["_id"]}) or order
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps({k: v for k, v in result.items() if k in ("reply", "done", "escalated", "ticket_id")}),
                })
        final = await asyncio.to_thread(_groq, messages, None)
        return wrap((final.get("content") or "Done.").strip(), {"escalated": escalated} if escalated else None)
    except Exception as e:  # pragma: no cover
        print(f"[agent] groq failed: {e}")
        human = await _human_line(db)
        return wrap(
            f"I couldn't reach my brain just then 😅 The buttons below still work for tracking, cancelling and reaching the team — or {human}."
        )
