"""Admin-editable storefront sections.

Every band on a storefront page (hero, category strip, reels, spotlight, the
comparison table, the farm rail …) is one document here. The admin panel reads
`/page-sections/types` to know which fields each band accepts, then edits,
reorders, hides, adds or removes bands without a rebuild.

The storefront asks for `/page-sections?page=home` and renders the list in
order. On a cold database the current hand-built home page is seeded verbatim,
so switching to this router changes nothing visually — it only makes every
piece of copy and artwork editable.

`fixed` types are backed by their own collections (banners, categories, stores,
garden services …). They still live here so the admin controls their position,
heading and visibility; their content keeps coming from the dedicated routers.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/page-sections", tags=["page-sections"])

PAGES = {"home"}


# ── Type catalogue ───────────────────────────────────────────────────────────
# `fields` drives the admin form for the band itself; `item_fields` drives the
# repeater beneath it. A type with no `item_fields` has no repeater.
#
# Field types the admin panel knows how to render:
#   text | textarea | image | video | lottie | link | number | bool | select

def _f(key: str, label: str, type_: str = "text", **extra: Any) -> dict:
    return {"key": key, "label": label, "type": type_, **extra}


STATUS_OPTIONS = ["positive", "negative", "mixed"]

SECTION_TYPES: list[dict] = [
    {
        "type": "hero",
        "label": "Hero Slider",
        "description": "Full-width slider at the very top. Slides are managed in Marquee Banner / Banners.",
        "source": "banners",
        "fields": [],
        "item_fields": [],
    },
    {
        "type": "category_strip",
        "label": "Our Categories",
        "description": "The green band of round category tiles. Tiles come from Categories.",
        "source": "categories",
        "fields": [_f("title", "Heading"), _f("limit", "How many tiles", "number")],
        "item_fields": [],
    },
    {
        "type": "trust_strip",
        "label": "Yellow Trust Strip",
        "description": "The yellow bar with animated badges (90-day soil, arrives healthy …).",
        "fields": [_f("bg_color", "Background colour")],
        "item_fields": [_f("lottie", "Animation (.json)", "lottie"), _f("title", "Label")],
    },
    {
        "type": "bestsellers",
        "label": "Bestsellers",
        "description": "Two rows of the catalogue's bestselling products, pulled live.",
        "fields": [
            _f("title", "Heading"),
            _f("subtitle", "Sub-heading"),
            _f("cta_label", "Link label"),
            _f("cta_link", "Link target", "link"),
            _f("limit", "How many products", "number"),
        ],
        "item_fields": [],
    },
    {
        "type": "video_reel",
        "label": "Featured Reels",
        "description": "The grid of vertical autoplaying clips.",
        "fields": [_f("title", "Heading"), _f("subtitle", "Sub-heading")],
        "item_fields": [_f("video", "Clip", "video"), _f("poster", "Poster frame", "image"), _f("title", "Caption")],
    },
    {
        "type": "spotlight",
        "label": "In the Spotlight",
        "description": "Two square promo artworks side by side.",
        "fields": [_f("title", "Heading"), _f("subtitle", "Sub-heading")],
        "item_fields": [_f("image", "Artwork", "image"), _f("link", "Links to", "link"), _f("title", "Alt text")],
    },
    {
        "type": "low_effort",
        "label": "Low-Effort Plants",
        "description": "Two rows of the easiest plants to keep alive, pulled live from the catalogue.",
        "fields": [
            _f("title", "Heading"),
            _f("subtitle", "Sub-heading"),
            _f("cta_label", "Link label"),
            _f("cta_link", "Link target", "link"),
            _f("limit", "How many products", "number"),
        ],
        "item_fields": [],
    },
    {
        "type": "bhidu",
        "label": "Bhidu Approved Rail",
        "description": "The sunburst rail with the cut-out person and a product carousel.",
        "fields": [
            _f("badge_label", "Sticker line 1"),
            _f("badge_label_2", "Sticker line 2"),
            _f("title", "Big heading"),
            _f("cta_label", "Link label"),
            _f("cta_link", "Link target", "link"),
            _f("image", "Cut-out person", "image"),
            _f("limit", "How many products", "number"),
        ],
        "item_fields": [],
    },
    {
        "type": "offers",
        "label": "Offers for You",
        "description": "The drifting marquee of offer artwork.",
        "fields": [_f("title", "Heading")],
        "item_fields": [_f("image", "Artwork", "image"), _f("link", "Links to", "link"), _f("title", "Alt text")],
    },
    {
        "type": "combos",
        "label": "Ready to Buy Combos",
        "description": "Two rows of bundle cards. Bundles come from Combos.",
        "source": "combos",
        "fields": [
            _f("title", "Heading"),
            _f("subtitle", "Sub-heading"),
            _f("cta_label", "Link label"),
            _f("cta_link", "Link target", "link"),
            _f("limit", "How many bundles", "number"),
        ],
        "item_fields": [],
    },
    {
        "type": "self_watering",
        "label": "About Self-Watering Planters",
        "description": "Teal explainer band with the cutaway shot and three steps.",
        "fields": [
            _f("title", "Heading"),
            _f("description", "Body copy", "textarea"),
            _f("image", "Cutaway photo", "image"),
            _f("subtitle", "Steps heading"),
        ],
        "item_fields": [_f("image", "Step image", "image"), _f("title", "Step caption")],
    },
    {
        "type": "planters",
        "label": "Planters That Redefine Spaces",
        "description": "Centred intro, three benefit cards and a planter product grid.",
        "fields": [_f("title", "Heading"), _f("subtitle", "Sub-heading", "textarea"), _f("limit", "How many products", "number")],
        "item_fields": [_f("image", "Icon", "image"), _f("title", "Benefit title"), _f("subtitle", "Benefit text", "textarea")],
    },
    {
        "type": "product_grid",
        "label": "Storefront Product Grid",
        "description": "The Filter / Sort by grid of catalogue products.",
        "fields": [_f("limit", "How many products", "number")],
        "item_fields": [],
    },
    {
        "type": "shop_by_space",
        "label": "Transform Your Home",
        "description": "Room tiles. Uses the 'Shop by Space' category tree when it exists, otherwise these tiles.",
        "source": "categories",
        "fields": [_f("title", "Heading")],
        "item_fields": [_f("image", "Photo", "image"), _f("title", "Room name"), _f("link", "Links to", "link")],
    },
    {
        "type": "trust_bar",
        "label": "Delivery Trust Bar",
        "description": "The four promises row. Copy comes from Store Settings.",
        "source": "settings",
        "fields": [],
        "item_fields": [],
    },
    {
        "type": "product_rails",
        "label": "Product Rails",
        "description": "The rails built in Storefront Layout, plus Recommended for you.",
        "source": "home-sections",
        "fields": [],
        "item_fields": [],
    },
    {
        "type": "google_reviews",
        "label": "Google Reviews",
        "description": "Customer review cards synced from the Business Profile.",
        "source": "google-reviews",
        "fields": [_f("eyebrow", "Eyebrow"), _f("title", "Heading"), _f("limit", "How many", "number")],
        "item_fields": [],
    },
    {
        "type": "blog",
        "label": "Journal Cards",
        "description": "Latest posts from the Plant Care Blog.",
        "source": "blog",
        "fields": [_f("eyebrow", "Eyebrow"), _f("title", "Heading"), _f("limit", "How many", "number")],
        "item_fields": [],
    },
    {
        "type": "farm_to_home",
        "label": "From Our Farm to Your Home",
        "description": "Dark green band with the auto-drifting photo rail.",
        "fields": [_f("title", "Heading"), _f("subtitle", "Sub-heading", "textarea")],
        "item_fields": [_f("image", "Photo", "image"), _f("title", "Caption / alt text")],
    },
    {
        "type": "comparison",
        "label": "Us vs the Rest Table",
        "description": "The three-column comparison table.",
        "fields": [
            _f("title", "Heading"),
            _f("brand_label", "Featured column"),
            _f("local_label", "Left column"),
            _f("others_label", "Right column"),
        ],
        "item_fields": [
            _f("label", "Row label"),
            _f("local_status", "Left mark", "select", options=STATUS_OPTIONS),
            _f("local_title", "Left text"),
            _f("brand_status", "Featured mark", "select", options=STATUS_OPTIONS),
            _f("brand_title", "Featured text"),
            _f("brand_badge", "Featured badge"),
            _f("others_status", "Right mark", "select", options=STATUS_OPTIONS),
            _f("others_title", "Right text"),
        ],
    },
    {
        "type": "grow_banner",
        "label": "Wide Image Banner",
        "description": "Full-bleed photo banner with headline and a button.",
        "fields": [
            _f("image", "Photo", "image"),
            _f("image_alt", "Alt text"),
            _f("title", "Headline (one line per row)", "textarea"),
            _f("subtitle", "Sub-line"),
            _f("cta_label", "Button label"),
            _f("cta_link", "Button target", "link"),
        ],
        "item_fields": [],
    },
    {
        "type": "store_locator",
        "label": "Find Your Nearest Store",
        "description": "City tabs and the store photo rail. Stores come from Store Locations.",
        "source": "stores",
        "fields": [_f("title", "Heading"), _f("subtitle", "Sub-heading", "textarea")],
        "item_fields": [],
    },
    {
        "type": "garden_services",
        "label": "Garden Services Band",
        "description": "Orange services band. Copy comes from Garden Services.",
        "source": "garden-services",
        "fields": [],
        "item_fields": [],
    },
    {
        "type": "gifting",
        "label": "Green Gifting Band",
        "description": "Gifting hero band. Copy comes from Home Bands.",
        "source": "gifting",
        "fields": [],
        "item_fields": [],
    },
    {
        "type": "press",
        "label": "As Featured In",
        "description": "Press logo marquee. Logos come from Home Bands.",
        "source": "press",
        "fields": [],
        "item_fields": [],
    },
    # ── Free-form bands the admin can add anywhere ──
    {
        "type": "custom_banner",
        "label": "Custom Banner (new)",
        "description": "A blank image banner with a headline and a button — add as many as you like.",
        "fields": [
            _f("image", "Photo", "image"),
            _f("image_alt", "Alt text"),
            _f("title", "Headline", "textarea"),
            _f("subtitle", "Sub-line", "textarea"),
            _f("cta_label", "Button label"),
            _f("cta_link", "Button target", "link"),
            _f("bg_color", "Background colour"),
        ],
        "item_fields": [],
    },
    {
        "type": "custom_cards",
        "label": "Custom Card Grid (new)",
        "description": "A heading plus a grid of image cards — add as many as you like.",
        "fields": [_f("eyebrow", "Eyebrow"), _f("title", "Heading"), _f("subtitle", "Sub-heading", "textarea"), _f("bg_color", "Background colour")],
        "item_fields": [
            _f("image", "Photo", "image"),
            _f("title", "Card title"),
            _f("subtitle", "Card text", "textarea"),
            _f("link", "Links to", "link"),
        ],
    },
    {
        "type": "custom_text",
        "label": "Custom Text Block (new)",
        "description": "A centred heading and paragraph — useful for announcements or SEO copy.",
        "fields": [
            _f("eyebrow", "Eyebrow"),
            _f("title", "Heading"),
            _f("description", "Body copy", "textarea"),
            _f("cta_label", "Button label"),
            _f("cta_link", "Button target", "link"),
            _f("bg_color", "Background colour"),
        ],
        "item_fields": [],
    },
]

TYPE_BY_KEY = {t["type"]: t for t in SECTION_TYPES}
# Types backed by another collection may only exist once on a page.
SINGLETON_TYPES = {t["type"] for t in SECTION_TYPES if t.get("source")}


# ── Seed: the home page exactly as it ships today ────────────────────────────

_ART = "/Watering%20Planters"
_ICONS = "/Planters"


def _cmp(label: str, local: tuple, brand: tuple, others: tuple) -> dict:
    """(status, title, badge) triples → one comparison row."""
    row = {"label": label}
    for col, vals in (("local", local), ("brand", brand), ("others", others)):
        row[f"{col}_status"] = vals[0]
        row[f"{col}_title"] = vals[1] if len(vals) > 1 else ""
        row[f"{col}_badge"] = vals[2] if len(vals) > 2 else ""
    return row


HOME_DEFAULTS: list[dict] = [
    {"type": "hero"},
    {"type": "category_strip", "title": "Our Categories", "limit": 9},
    {
        "type": "trust_strip",
        "bg_color": "#facc15",
        "items": [
            {"lottie": "/lottie/soil.json", "title": "90-Day Pre Fertilised Soil"},
            {"lottie": "/lottie/healthy.json", "title": "Arrives Healthy"},
            {"lottie": "/lottie/replacement.json", "title": "Free Replacement"},
            {"lottie": "/lottie/support.json", "title": "Free Plant Care Support"},
        ],
    },
    {
        "type": "bestsellers",
        "title": "Bestsellers",
        "subtitle": "The plants and picks our customers keep coming back for",
        "cta_label": "View all",
        "cta_link": "/plants",
        "limit": 10,
    },
    {
        "type": "video_reel",
        "title": "Featured Reels",
        "subtitle": "Get inspired by our beautiful community spaces",
        "items": [
            {"video": "/Video/video-1.mp4", "title": "Transform your living room"},
            {"video": "/Video/video-2.mp4", "title": "Easy care tips for busy days"},
            {"video": "/Video/video-3.mp4", "title": "Styling your work desk"},
            {"video": "/Video/video-4.mp4", "title": "Pet-friendly plants"},
            {"video": "/Video/video-5.mp4", "title": "Morning mist routine"},
            {"video": "/Video/video-6.mp4", "title": "Propagating made simple"},
        ],
    },
    {
        "type": "spotlight",
        "title": "In the Spotlight",
        "subtitle": "One for the Tadka, One for the Drama",
        "items": [
            {"image": "/images/spotlight-1.png", "link": "/search?q=Peace%20Lily", "title": "Starring Peace Lily"},
            {"image": "/images/spotlight-2.png", "link": "/search?q=Kadi%20Patta", "title": "Kadi Patta Plant New Launch"},
        ],
    },
    {
        "type": "low_effort",
        "title": "Low-Effort Plants",
        "subtitle": "Hard to kill, easy to love — pick one and forget the fuss",
        "cta_label": "View all",
        "cta_link": "/plants",
        "limit": 10,
    },
    {
        "type": "bhidu",
        "badge_label": "Bhidu",
        "badge_label_2": "Approved",
        "title": "Plants",
        "cta_label": "view all",
        "cta_link": "/plants",
        "image": "/images/bhidu-person.png",
        "limit": 6,
    },
    {"type": "offers", "title": "Offers for You", "items": [
        {"image": "/card/offer-1.jpg", "link": "/offers", "title": "Buy any 4 plants bundle offer"},
        {"image": "/card/offer-2.jpg", "link": "/offers", "title": "Build your own plant bundle"},
        {"image": "/card/offer-3.jpg", "link": "/offers", "title": "Plant and pot combo offer"},
        {"image": "/card/offer-4.jpg", "link": "/offers", "title": "Seasonal plant offer"},
        {"image": "/card/offer-5.jpg", "link": "/offers", "title": "Indoor plant bundle offer"},
        {"image": "/card/offer-6.jpg", "link": "/offers", "title": "Gardening essentials offer"},
    ]},
    {
        "type": "combos",
        "title": "Ready to Buy Combos",
        "subtitle": "Hand-picked bundles — everything you need, priced together",
        "cta_label": "View all combos",
        "cta_link": "/combos",
        "limit": 8,
    },
    {
        "type": "self_watering",
        "title": "About Self-Watering Planters",
        "description": "Self-watering planters provide consistent moisture, prevent overwatering, and simplify care for healthy plant growth.",
        "image": f"{_ART}/care_plant.png",
        "subtitle": "How it works",
        "items": [
            {"image": f"{_ART}/1.png", "title": "Fill the Water Reservoir"},
            {"image": f"{_ART}/2.png", "title": "Water reaches the soil as needed"},
            {"image": f"{_ART}/3.png", "title": "Healthy and Happy Plant"},
        ],
    },
    {
        "type": "planters",
        "title": "Planters That Redefine Spaces",
        "subtitle": "Our FRP planters are the perfect balance of style and strength—transforming any corner into a modern green retreat.",
        "limit": 4,
        "items": [
            {"image": f"{_ICONS}/Lightweight.png", "title": "Lightweight yet strong",
             "subtitle": "Made from high-quality, UV & frost resistant Fiberglass."},
            {"image": f"{_ICONS}/UV%20&%20moisture%20resistant.png", "title": "UV & moisture resistant",
             "subtitle": "Perfect for both indoor and outdoor spaces."},
            {"image": f"{_ICONS}/Designed%20for%20modern%20spaces.png", "title": "Designed for modern spaces",
             "subtitle": "Clean, minimal design that fits any décor."},
        ],
    },
    {"type": "product_grid", "limit": 6},
    {
        "type": "shop_by_space",
        "title": "Transform Your Home.",
        "items": [
            {"image": "/places/living-room.jpg", "title": "Living Room", "link": "/search?q=living%20room"},
            {"image": "/places/bedroom.jpg", "title": "Bedroom", "link": "/search?q=bedroom"},
            {"image": "/places/balcony.jpg", "title": "Balcony", "link": "/search?q=balcony"},
            {"image": "/places/office.jpg", "title": "Office", "link": "/search?q=office"},
        ],
    },
    {"type": "trust_bar"},
    {"type": "product_rails"},
    {"type": "google_reviews", "eyebrow": "Google reviews", "title": "What our customers say", "limit": 6},
    {"type": "blog", "eyebrow": "Journal", "title": "Plant care stories", "limit": 3},
    {
        "type": "farm_to_home",
        "title": "From Our Farm to Your Home",
        "subtitle": "Every plant is nursed in our farms, hand-picked, and packed to survive the journey — not just reach your doorstep.",
        "items": [
            {"image": "/farm/farm-1.jpg", "title": "Grown with care in our nursery"},
            {"image": "/farm/farm-2.jpg", "title": "Quality you can trust"},
            {"image": "/farm/farm-3.jpg", "title": "Packed for a greener tomorrow"},
            {"image": "/farm/farm-4.jpg", "title": "Brings nature home"},
        ],
    },
    {
        "type": "comparison",
        "title": "MyGarden vs the Rest",
        "brand_label": "MyGarden",
        "local_label": "Local Nurseries",
        "others_label": "Others",
        "items": [
            _cmp("Plant quality", ("negative", "Poor health (No quality checks)"),
                 ("positive", "Green, healthy & bushy", "3-step quality check"), ("mixed", "Inconsistent")),
            _cmp("Pests", ("negative", "Common issue"), ("positive", "Pest-controlled"), ("negative", "Possible risk")),
            _cmp("Repotting", ("negative", "Requires repotting (Pot is missing)"),
                 ("positive", "Not required", "Comes in a MyGarden Gropot"), ("mixed", "Varies; not consistent")),
            _cmp("Soil", ("negative", "Standard soil"), ("positive", "Pre-mixed", "90-Day fertilised"),
                 ("negative", "Standard soil")),
            _cmp("Growing conditions", ("negative", "Outsourced"),
                 ("positive", "Grown by experts on MyGarden farms"), ("negative", "Outsourced")),
            _cmp("After-sale help", ("negative", "None"), ("positive", "Expert support"), ("negative", "None")),
            _cmp("Guaranteed", ("negative", "No guarantee"),
                 ("positive", "Assured quality, 30 days replacement"), ("mixed", "Conditional")),
            _cmp("One-stop garden shop", ("negative",), ("positive",), ("negative",)),
        ],
    },
    {
        "type": "grow_banner",
        "image": "/garden.png",
        "image_alt": "Seed packets, pots and seedling trays on a sunlit garden table",
        "title": "Grow your\nown Garden",
        "subtitle": "Shop our 300+ Seeds",
        "cta_label": "Shop Now",
        "cta_link": "/category/seeds",
    },
    {"type": "store_locator", "title": "Find Your Nearest Store.",
     "subtitle": "Step inside for exotic plants, rare planters, and an experience you can't find online."},
    {"type": "garden_services"},
    {"type": "gifting"},
    {"type": "press"},
]


# ── Model ────────────────────────────────────────────────────────────────────

class SectionIn(BaseModel):
    page: str = "home"
    type: str
    title: str = ""
    subtitle: str = ""
    eyebrow: str = ""
    description: str = ""
    image: str = ""
    image_alt: str = ""
    cta_label: str = ""
    cta_link: str = ""
    bg_color: str = ""
    limit: int | None = None
    items: list[dict] = Field(default_factory=list)
    extras: dict = Field(default_factory=dict)
    order: int | None = None
    active: bool = True


def _blank(type_: str) -> dict:
    """An empty document for a type — every field the admin form expects."""
    return {
        "type": type_, "title": "", "subtitle": "", "eyebrow": "", "description": "",
        "image": "", "image_alt": "", "cta_label": "", "cta_link": "", "bg_color": "",
        "limit": None, "items": [], "extras": {},
    }


def _check_type(type_: str) -> dict:
    spec = TYPE_BY_KEY.get(type_)
    if not spec:
        raise HTTPException(status_code=400, detail=f"Unknown section type '{type_}'")
    return spec


def _check_page(page: str) -> str:
    if page not in PAGES:
        raise HTTPException(status_code=400, detail=f"Unknown page '{page}'")
    return page


async def _backfill(db, page: str, defaults: list[dict]) -> int:
    """Add bands that shipped after this page was first seeded.

    A page seeded on an older build is missing every band added since, and the
    only way to get them used to be a reset — which throws away the admin's
    copy and artwork. Instead each absent band is slotted in behind the shipped
    band it follows, so a page nobody has reordered ends up with the shipped
    layout, and one that has been reordered keeps its arrangement.
    """
    have = set(await db.page_sections.distinct("type", {"page": page}))
    if all(d["type"] in have for d in defaults):
        return 0

    docs = await db.page_sections.find({"page": page}).sort("order", 1).to_list(length=200)
    order_of = {d.get("type"): d.get("order", 0) for d in docs}
    now = datetime.now(timezone.utc)

    added: list[dict] = []
    for i, default in enumerate(defaults):
        if default["type"] in have:
            continue
        # Half a step behind the nearest earlier band still on the page; -1 puts
        # a band that ships first at the very top.
        before = next((defaults[j]["type"] for j in range(i - 1, -1, -1) if defaults[j]["type"] in order_of), None)
        doc = _blank(default["type"])
        doc.update(default)
        doc.update({
            "page": page,
            "order": order_of[before] + 0.5 if before else -1.0,
            "active": True,
            "created_at": now,
            "updated_at": now,
        })
        added.append(doc)

    await db.page_sections.insert_many(added)
    # insert_many stamps `_id` on the dicts, so both lists renumber together.
    for order, doc in enumerate(sorted(docs + added, key=lambda d: d.get("order", 0))):
        await db.page_sections.update_one({"_id": doc["_id"]}, {"$set": {"order": order}})
    return len(added)


async def seed_page(db, page: str, *, force: bool = False) -> int:
    """Write the shipped layout for `page`. An already-seeded page only gains
    the bands that shipped after it was seeded — its edits stay untouched."""
    defaults = HOME_DEFAULTS if page == "home" else []
    if not force and await db.page_sections.count_documents({"page": page}):
        return await _backfill(db, page, defaults)
    if force:
        await db.page_sections.delete_many({"page": page})
    now = datetime.now(timezone.utc)
    docs = []
    for order, default in enumerate(defaults):
        doc = _blank(default["type"])
        doc.update(default)
        doc.update({"page": page, "order": order, "active": True, "created_at": now, "updated_at": now})
        docs.append(doc)
    if docs:
        await db.page_sections.insert_many(docs)
    return len(docs)


# ── Public ───────────────────────────────────────────────────────────────────

@router.get("/types")
async def list_types():
    """The catalogue that drives the admin's section forms and the add picker."""
    return SECTION_TYPES


@router.get("")
async def public_sections(page: str = "home"):
    _check_page(page)
    db = get_db()
    await seed_page(db, page)
    docs = await db.page_sections.find({"page": page, "active": True}).sort("order", 1).to_list(length=200)
    return [serialize(d) for d in docs]


# ── Admin ────────────────────────────────────────────────────────────────────

@router.get("/admin", dependencies=[Depends(require_admin)])
async def admin_sections(page: str = "home"):
    _check_page(page)
    db = get_db()
    await seed_page(db, page)
    docs = await db.page_sections.find({"page": page}).sort("order", 1).to_list(length=200)
    return [serialize(d) for d in docs]


@router.post("", dependencies=[Depends(require_admin)])
async def create_section(body: SectionIn):
    _check_page(body.page)
    _check_type(body.type)
    db = get_db()
    if body.type in SINGLETON_TYPES and await db.page_sections.count_documents(
        {"page": body.page, "type": body.type}
    ):
        raise HTTPException(status_code=400, detail=f"'{body.type}' is already on this page")

    doc = _blank(body.type)
    doc.update({k: v for k, v in body.model_dump().items() if v is not None})
    if body.order is None:
        last = await db.page_sections.find({"page": body.page}).sort("order", -1).to_list(length=1)
        doc["order"] = (last[0].get("order", 0) + 1) if last else 0
    now = datetime.now(timezone.utc)
    doc["created_at"] = now
    doc["updated_at"] = now
    res = await db.page_sections.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.put("/order", dependencies=[Depends(require_admin)])
async def reorder_sections(ids: list[str] = Body(..., embed=True)):
    db = get_db()
    for i, sid in enumerate(ids):
        await db.page_sections.update_one({"_id": to_object_id(sid)}, {"$set": {"order": i}})
    return {"ok": True, "count": len(ids)}


@router.post("/reset", dependencies=[Depends(require_admin)])
async def reset_page(page: str = "home"):
    """Throw away every edit and reinstate the shipped layout for that page."""
    _check_page(page)
    count = await seed_page(get_db(), page, force=True)
    return {"ok": True, "sections": count}


@router.patch("/{section_id}", dependencies=[Depends(require_admin)])
async def update_section(section_id: str, body: dict = Body(...)):
    db = get_db()
    for k in ("id", "_id", "created_at", "page", "type"):
        body.pop(k, None)
    if not body:
        raise HTTPException(status_code=400, detail="Nothing to update")
    body["updated_at"] = datetime.now(timezone.utc)
    res = await db.page_sections.find_one_and_update(
        {"_id": to_object_id(section_id)}, {"$set": body}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Section not found")
    return serialize(res)


@router.delete("/{section_id}", dependencies=[Depends(require_admin)])
async def delete_section(section_id: str):
    db = get_db()
    res = await db.page_sections.delete_one({"_id": to_object_id(section_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Section not found")
    return {"deleted": True}
