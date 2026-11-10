"""Journal / blog posts, authored from the admin panel.

The storefront reads `/blog/posts` (list) and `/blog/posts/{slug}` (detail) and
falls back to its bundled demo posts when nothing is published yet, so an empty
collection is a valid state.
"""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/blog", tags=["blog"])

MAX_LIMIT = 50


class BlogBlock(BaseModel):
    """One chunk of article copy. `url` is only used by `link` blocks."""

    type: str = "p"  # p | h2 | quote | link
    text: str = ""
    url: str = ""


class BlogPostIn(BaseModel):
    title: str
    slug: str = ""                       # auto-derived from the title when blank
    excerpt: str = ""
    image: str = ""                      # cover photo (recommended 1200 x 800)
    author: str = "Royal Wool"
    tag: str = "Journal"
    published_at: str = ""               # ISO date from the admin date picker
    body: list[BlogBlock] = Field(default_factory=list)
    link: str = ""                       # optional CTA link shown under the article
    link_label: str = ""
    featured: bool = False               # pins the post to the journal hero slot
    published: bool = True
    order: int = 0


def slugify(value: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", value.lower()))


async def _unique_slug(db, slug: str, ignore_id=None) -> str:
    base = slug or "post"
    candidate, n = base, 2
    while True:
        clash = await db.blog_posts.find_one({"slug": candidate})
        if not clash or (ignore_id is not None and clash["_id"] == ignore_id):
            return candidate
        candidate, n = f"{base}-{n}", n + 1


def _normalize(doc: dict) -> dict:
    """Fill in the derived fields the storefront expects."""
    doc["slug"] = slugify(doc.get("slug") or "") or slugify(doc.get("title", ""))
    doc["published_at"] = doc.get("published_at") or datetime.now(timezone.utc).isoformat()
    doc["body"] = [b for b in doc.get("body", []) if (b.get("text") or b.get("url"))]
    return doc


async def _find(db, key: str):
    """Look a post up by slug first, then by id — the storefront uses slugs."""
    doc = await db.blog_posts.find_one({"slug": key})
    if doc:
        return doc
    try:
        return await db.blog_posts.find_one({"_id": to_object_id(key)})
    except ValueError:
        return None


async def _list(page: int, limit: int, admin: bool):
    db = get_db()
    page = max(1, page)
    limit = max(1, min(limit, MAX_LIMIT))
    q = {} if admin else {"published": True}
    total = await db.blog_posts.count_documents(q)
    docs = (
        await db.blog_posts.find(q)
        .sort([("featured", -1), ("order", 1), ("published_at", -1)])
        .skip((page - 1) * limit)
        .limit(limit)
        .to_list(length=limit)
    )
    return {
        "items": [serialize(d) for d in docs],
        "total": total,
        "page": page,
        "has_more": page * limit < total,
    }


@router.get("/posts")
async def list_posts(page: int = 1, limit: int = 9, per_page: int | None = None, admin: bool = False):
    return await _list(page, per_page or limit, admin)


@router.get("")
async def list_posts_alias(page: int = 1, limit: int = 9, per_page: int | None = None, admin: bool = False):
    return await _list(page, per_page or limit, admin)


@router.post("/posts", dependencies=[Depends(require_admin)])
async def create_post(body: BlogPostIn):
    db = get_db()
    doc = _normalize(body.model_dump())
    doc["slug"] = await _unique_slug(db, doc["slug"])
    doc["created_at"] = datetime.now(timezone.utc)
    res = await db.blog_posts.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.patch("/posts/{post_id}", dependencies=[Depends(require_admin)])
async def update_post(post_id: str, body: dict = Body(...)):
    db = get_db()
    body.pop("id", None)
    body.pop("created_at", None)
    oid = to_object_id(post_id)
    if "slug" in body or "title" in body:
        current = await db.blog_posts.find_one({"_id": oid}) or {}
        body["slug"] = await _unique_slug(
            db, slugify(body.get("slug") or "") or slugify(body.get("title") or current.get("title", "")), oid
        )
    if "body" in body:
        body["body"] = [b for b in body["body"] if (b.get("text") or b.get("url"))]
    body["updated_at"] = datetime.now(timezone.utc)
    res = await db.blog_posts.find_one_and_update({"_id": oid}, {"$set": body}, return_document=True)
    if not res:
        raise HTTPException(status_code=404, detail="Post not found")
    return serialize(res)


@router.delete("/posts/{post_id}", dependencies=[Depends(require_admin)])
async def delete_post(post_id: str):
    db = get_db()
    await db.blog_posts.delete_one({"_id": to_object_id(post_id)})
    return {"deleted": True}


@router.get("/posts/{key}")
async def get_post(key: str):
    doc = await _find(get_db(), key)
    if not doc:
        raise HTTPException(status_code=404, detail="Post not found")
    return serialize(doc)


@router.get("/{key}")
async def get_post_alias(key: str):
    return await get_post(key)
