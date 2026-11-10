"""Editorial media for the storefront's home sections.

Each frontend section that shows a photo or a clip has a slot list here, so the
admin can swap the imagery without a rebuild. Sections whose content is already
products (Editorial Spotlight, Runway Lookbook) aren't listed — they follow the
catalogue instead.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/site-media", tags=["site-media"])


class SectionSpec(BaseModel):
    key: str
    label: str
    kind: str          # "image" | "video"
    slots: int         # how many the layout is designed around
    aspect: str        # guidance shown in the admin uploader
    description: str
    captions: bool     # whether title/subtitle are rendered by the section


# Mirrors src/components/home/* on the storefront. `slots` is the count the
# layout is built for — extra items are ignored by the section, fewer fall back
# to the bundled assets.
SECTIONS: list[SectionSpec] = [
    SectionSpec(
        key="atelier_stories",
        label="Atelier Stories",
        kind="image",
        slots=6,
        aspect="4:5 portrait",
        description="The stacked editorial column midway down the home page.",
        captions=True,
    ),
    SectionSpec(
        key="diagonal_edit",
        label="Diagonal Edit",
        kind="image",
        slots=6,
        aspect="3:4 portrait",
        description="The offset diagonal grid of campaign shots.",
        captions=True,
    ),
    SectionSpec(
        key="shop_gallery",
        label="Shop Gallery Pills",
        kind="image",
        slots=4,
        aspect="1:1 square",
        description="Round category tiles in the shop gallery strip.",
        captions=True,
    ),
    SectionSpec(
        key="couture_simplicity",
        label="Couture Simplicity",
        kind="image",
        slots=2,
        aspect="4:5 portrait",
        description="The two-up atelier feature beside the copy block.",
        captions=False,
    ),
    SectionSpec(
        key="video_reel",
        label="Video Reel",
        kind="video",
        slots=6,
        aspect="9:16 vertical",
        description="The autoplaying clip carousel.",
        captions=True,
    ),
    SectionSpec(
        key="spotlight",
        label="Spotlight Section",
        kind="image",
        slots=1,
        aspect="3:4 portrait",
        description="The editorial spotlight card (e.g. 'Spun for softness. Made to last.'). Upload one hero product image.",
        captions=True,
    ),
    SectionSpec(
        key="range_cards",
        label="Range Cards",
        kind="image",
        slots=3,
        aspect="16:9 landscape",
        description="The three scroll-stacking range cards (e.g. Cotton Delight, Cotton Candy, Hobby India). Upload one image per range.",
        captions=True,
    ),
    SectionSpec(
        key="hero",
        label="Hero Slider",
        kind="image",
        slots=5,
        aspect="16:9 landscape",
        description="The full-width hero slider at the top of the home page.",
        captions=True,
    ),
]

SECTION_KEYS = {s.key for s in SECTIONS}
SECTION_BY_KEY = {s.key: s for s in SECTIONS}


class MediaIn(BaseModel):
    section: str
    url: str
    poster: str | None = None       # video only — still frame
    title: str = ""
    subtitle: str = ""
    order: int = 0
    active: bool = True


class MediaUpdate(BaseModel):
    url: str | None = None
    poster: str | None = None
    title: str | None = None
    subtitle: str | None = None
    order: int | None = None
    active: bool | None = None


def _check_section(section: str) -> SectionSpec:
    spec = SECTION_BY_KEY.get(section)
    if not spec:
        raise HTTPException(status_code=400, detail=f"Unknown section '{section}'")
    return spec


@router.get("/sections")
async def list_sections():
    """The catalogue of manageable sections — drives the admin's tab list."""
    return [s.model_dump() for s in SECTIONS]


@router.get("")
async def public_media(section: str | None = None):
    """Public: active media, oldest-ordered first, grouped by section.

    The storefront asks for everything once and picks its own section out, so
    the home page costs a single request.
    """
    db = get_db()
    q: dict = {"active": True}
    if section:
        _check_section(section)
        q["section"] = section
    docs = await db.site_media.find(q).sort([("section", 1), ("order", 1)]).to_list(length=300)

    grouped: dict[str, list] = {key: [] for key in SECTION_KEYS}
    for d in docs:
        grouped.setdefault(d["section"], []).append(serialize(d))
    return grouped


@router.get("/admin", dependencies=[Depends(require_admin)])
async def admin_media(section: str | None = None):
    """Admin: everything, including items switched off."""
    db = get_db()
    q: dict = {}
    if section:
        _check_section(section)
        q["section"] = section
    docs = await db.site_media.find(q).sort([("section", 1), ("order", 1)]).to_list(length=300)
    return [serialize(d) for d in docs]


@router.post("", dependencies=[Depends(require_admin)])
async def create_media(body: MediaIn):
    _check_section(body.section)
    db = get_db()
    doc = body.model_dump()
    # Append to the end of that section unless the caller placed it explicitly.
    if not doc.get("order"):
        last = await db.site_media.find({"section": body.section}).sort("order", -1).to_list(length=1)
        doc["order"] = (last[0].get("order", 0) + 1) if last else 0
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.site_media.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/{media_id}", dependencies=[Depends(require_admin)])
async def update_media(media_id: str, body: MediaUpdate):
    db = get_db()
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.site_media.find_one_and_update(
        {"_id": to_object_id(media_id)}, {"$set": patch}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Media not found")
    return serialize(res)


@router.put("/order", dependencies=[Depends(require_admin)])
async def reorder_media(ids: list[str] = Body(..., embed=True)):
    """Persist a drag-and-drop reorder: the array position becomes `order`."""
    db = get_db()
    for i, mid in enumerate(ids):
        await db.site_media.update_one({"_id": to_object_id(mid)}, {"$set": {"order": i}})
    return {"ok": True, "count": len(ids)}


@router.delete("/{media_id}", dependencies=[Depends(require_admin)])
async def delete_media(media_id: str):
    db = get_db()
    res = await db.site_media.delete_one({"_id": to_object_id(media_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Media not found")
    return {"deleted": True}
