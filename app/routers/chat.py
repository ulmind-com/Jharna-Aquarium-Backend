"""Support chat endpoints.

The transcript is deliberately *not* persisted — the browser holds it and drops
it the moment the order reaches a final state. The only thing that outlives a
conversation is a human-handoff ticket, which the admin panel reads from here.
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import get_current_user, require_admin
from app.services import agent, support

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage] = []
    order_id: str | None = None


class ActionIn(BaseModel):
    action: str
    order_id: str | None = None
    product_id: str | None = None
    reason: str = ""
    messages: list[ChatMessage] = []


@router.get("/open")
async def open_chat(
    order_id: str | None = None,
    product_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Greeting, live order card and the quick actions that make sense *now*."""
    return await agent.opening(get_db(), user, order_id, product_id)


@router.get("/suggestions")
async def suggestions(order_id: str | None = None, user: dict = Depends(get_current_user)):
    """Back-compat list of plain prompts."""
    return {"questions": await agent.suggestions_for(get_db(), user, order_id)}


@router.post("/action")
async def action(body: ActionIn, user: dict = Depends(get_current_user)):
    """A tapped quick action — answered from the database, never from the model."""
    return await agent.run_action(
        get_db(),
        user,
        body.action,
        order_id=body.order_id,
        product_id=body.product_id,
        reason=body.reason,
        transcript=[m.model_dump() for m in body.messages],
    )


@router.post("")
async def chat(body: ChatIn, user: dict = Depends(get_current_user)):
    history = [m.model_dump() for m in body.messages]
    return await agent.reply(get_db(), user, history, body.order_id)


# ───────────────────────── admin: human handoffs ─────────────────────────

@router.get("/admin/tickets", dependencies=[Depends(require_admin)])
async def admin_tickets(status: str | None = None):
    db = get_db()
    return {"items": await support.list_tickets(db, status), "counts": await support.counts(db)}


@router.get("/admin/tickets/counts", dependencies=[Depends(require_admin)])
async def admin_ticket_counts():
    return await support.counts(get_db())


@router.patch("/admin/tickets/{ticket_id}", dependencies=[Depends(require_admin)])
async def admin_update_ticket(
    ticket_id: str,
    status: str = Body(..., embed=True),
    note: str = Body("", embed=True),
):
    if status not in (support.OPEN, support.CLOSED):
        raise HTTPException(status_code=400, detail="status must be 'open' or 'closed'")
    doc = await support.set_status(get_db(), ticket_id, status, note)
    if not doc:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return doc


@router.delete("/admin/tickets/{ticket_id}", dependencies=[Depends(require_admin)])
async def admin_delete_ticket(ticket_id: str):
    if not await support.delete_ticket(get_db(), ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ok": True}
