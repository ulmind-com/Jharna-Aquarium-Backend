"""Garden Services — the home page band plus the standalone services page.

The band's copy and photo live in a single settings document so the admin can
restyle it without touching the service list, while each service is its own
document rendered as a card on /garden-services.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/garden-services", tags=["garden-services"])

SECTION_ID = "section"


class SectionConfig(BaseModel):
    """Every piece of copy on the home band and the /garden-services page."""
    # Home band
    title: str = "Garden services by MyGarden"
    body: str = ""
    image: str = ""
    cta_label: str = "View all Garden Service"
    active: bool = True

    # Page hero
    hero_title: str = "Year round care"
    hero_subtitle: str = "for your garden & office space"
    hero_image: str = ""
    hero_cta_label: str = "Book service"
    hero_overlay: bool = False   # on when the hero photo has no headline baked in

    # Services grid
    page_title: str = "Garden Services"
    page_subtitle: str = ""
    page_image: str = ""
    services_title: str = "What are you looking for ?"
    services_note: str = ""

    # Why-us + lead form
    why_title: str = "Why Choose MyGarden?"
    why_points: list[str] = []
    split_image_1: str = ""
    split_image_2: str = ""
    form_title: str = "Get in touch with us."
    form_note: str = ""
    form_cta_label: str = "Get a Call Back"
    locations: list[str] = []
    phone: str = ""
    hours: str = ""
    whatsapp: str = ""

    # Lower sections
    process_title: str = "Our Process"
    process_note: str = ""
    clients_title: str = "Our Esteemed Clients"
    clients_note: str = ""
    projects_title: str = "Our Projects"
    steps_title: str = "How it works?"
    testimonials_title: str = "What our customers say"
    about_title: str = "More About MyGarden Garden Services"
    about_body: str = ""
    faq_title: str = "FAQs"
    seo_body: str = ""
    contact_note: str = ""


BLOCK_KINDS = {"project", "client", "testimonial", "faq", "process", "step"}


class BlockIn(BaseModel):
    kind: str
    title: str = ""
    body: str = ""
    image: str = ""
    author: str = ""
    order: int = 0
    active: bool = True


class BlockUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    image: str | None = None
    author: str | None = None
    order: int | None = None
    active: bool | None = None


class EnquiryIn(BaseModel):
    name: str
    phone: str
    location: str = ""
    service: str = ""
    note: str = ""


class ServiceIn(BaseModel):
    title: str
    summary: str = ""
    description: str = ""
    image: str = ""
    price_from: str = ""
    duration: str = ""
    features: list[str] = []
    order: int = 0
    active: bool = True


class ServiceUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    description: str | None = None
    image: str | None = None
    price_from: str | None = None
    duration: str | None = None
    features: list[str] | None = None
    order: int | None = None
    active: bool | None = None


async def _section(db) -> dict:
    doc = await db.garden_service_section.find_one({"_id": SECTION_ID})
    if not doc:
        return SectionConfig().model_dump()
    doc.pop("_id", None)
    return {**SectionConfig().model_dump(), **serialize(doc)}


async def _blocks(db, admin: bool = False) -> dict[str, list]:
    """Projects, client logos, testimonials, FAQs and the two step lists,
    grouped by kind so the page can render each strip in one pass."""
    q: dict = {} if admin else {"active": True}
    docs = await db.garden_service_blocks.find(q).sort([("kind", 1), ("order", 1)]).to_list(length=500)
    grouped: dict[str, list] = {kind: [] for kind in BLOCK_KINDS}
    for d in docs:
        grouped.setdefault(d.get("kind", "project"), []).append(serialize(d))
    return grouped


@router.get("")
async def public_garden_services():
    """The band's copy plus every live service and page block, in admin order."""
    db = get_db()
    docs = await db.garden_services.find({"active": True}).sort("order", 1).to_list(length=200)
    return {"section": await _section(db), "items": [serialize(d) for d in docs], "blocks": await _blocks(db)}


@router.get("/admin", dependencies=[Depends(require_admin)])
async def admin_garden_services():
    """Everything, including services switched off."""
    db = get_db()
    docs = await db.garden_services.find({}).sort("order", 1).to_list(length=200)
    return {"section": await _section(db), "items": [serialize(d) for d in docs], "blocks": await _blocks(db, admin=True)}


@router.put("/section", dependencies=[Depends(require_admin)])
async def save_section(body: SectionConfig):
    db = get_db()
    patch = body.model_dump()
    patch["updated_at"] = datetime.now(timezone.utc)
    await db.garden_service_section.update_one({"_id": SECTION_ID}, {"$set": patch}, upsert=True)
    return await _section(db)


@router.post("", dependencies=[Depends(require_admin)])
async def create_service(body: ServiceIn):
    db = get_db()
    doc = body.model_dump()
    if not doc["title"].strip():
        raise HTTPException(status_code=400, detail="Title required")
    if not doc.get("order"):
        last = await db.garden_services.find({}).sort("order", -1).to_list(length=1)
        doc["order"] = (last[0].get("order", 0) + 1) if last else 0
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.garden_services.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/{service_id}", dependencies=[Depends(require_admin)])
async def update_service(service_id: str, body: ServiceUpdate):
    db = get_db()
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.garden_services.find_one_and_update(
        {"_id": to_object_id(service_id)}, {"$set": patch}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Service not found")
    return serialize(res)


@router.put("/order", dependencies=[Depends(require_admin)])
async def reorder_services(ids: list[str] = Body(..., embed=True)):
    """Persist a reorder: the array position becomes `order`."""
    db = get_db()
    for i, sid in enumerate(ids):
        await db.garden_services.update_one({"_id": to_object_id(sid)}, {"$set": {"order": i}})
    return {"ok": True, "count": len(ids)}


@router.delete("/{service_id}", dependencies=[Depends(require_admin)])
async def delete_service(service_id: str):
    db = get_db()
    res = await db.garden_services.delete_one({"_id": to_object_id(service_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"deleted": True}


@router.post("/blocks", dependencies=[Depends(require_admin)])
async def create_block(body: BlockIn):
    if body.kind not in BLOCK_KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown block kind '{body.kind}'")
    db = get_db()
    doc = body.model_dump()
    if not doc.get("order"):
        last = await db.garden_service_blocks.find({"kind": doc["kind"]}).sort("order", -1).to_list(length=1)
        doc["order"] = (last[0].get("order", 0) + 1) if last else 0
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.garden_service_blocks.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/blocks/{block_id}", dependencies=[Depends(require_admin)])
async def update_block(block_id: str, body: BlockUpdate):
    db = get_db()
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.garden_service_blocks.find_one_and_update(
        {"_id": to_object_id(block_id)}, {"$set": patch}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Block not found")
    return serialize(res)


@router.put("/blocks/order", dependencies=[Depends(require_admin)])
async def reorder_blocks(ids: list[str] = Body(..., embed=True)):
    """Persist a reorder inside one kind: array position becomes `order`."""
    db = get_db()
    for i, bid in enumerate(ids):
        await db.garden_service_blocks.update_one({"_id": to_object_id(bid)}, {"$set": {"order": i}})
    return {"ok": True, "count": len(ids)}


@router.delete("/blocks/{block_id}", dependencies=[Depends(require_admin)])
async def delete_block(block_id: str):
    db = get_db()
    res = await db.garden_service_blocks.delete_one({"_id": to_object_id(block_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"deleted": True}


@router.post("/enquiry")
async def create_enquiry(body: EnquiryIn):
    """Public: the "Get a Call Back" form on the services page."""
    db = get_db()
    if not body.name.strip() or not body.phone.strip():
        raise HTTPException(status_code=400, detail="Name and contact number are required")
    doc = body.model_dump()
    doc["handled"] = False
    doc["created_at"] = datetime.now(timezone.utc)
    await db.garden_service_enquiries.insert_one(doc)
    return {"ok": True}


@router.get("/enquiries", dependencies=[Depends(require_admin)])
async def list_enquiries():
    db = get_db()
    docs = await db.garden_service_enquiries.find({}).sort("created_at", -1).to_list(length=500)
    return [serialize(d) for d in docs]


@router.patch("/enquiries/{enquiry_id}", dependencies=[Depends(require_admin)])
async def update_enquiry(enquiry_id: str, handled: bool = Body(..., embed=True)):
    db = get_db()
    res = await db.garden_service_enquiries.find_one_and_update(
        {"_id": to_object_id(enquiry_id)}, {"$set": {"handled": handled}}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    return serialize(res)


@router.delete("/enquiries/{enquiry_id}", dependencies=[Depends(require_admin)])
async def delete_enquiry(enquiry_id: str):
    db = get_db()
    res = await db.garden_service_enquiries.delete_one({"_id": to_object_id(enquiry_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    return {"deleted": True}
