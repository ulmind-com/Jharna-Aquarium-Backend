from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=100)
    parent_id: str | None = None       # None = top-level (Plants, Pots, Seeds …)
    blurb: str | None = None           # short line shown in nav panel / category cards
    description: str | None = None     # longer SEO description
    image: str | None = None
    icon: str | None = None            # emoji or icon class (🌿, 🪴, 🌻)
    image_scale: float | None = None   # home pill image size multiplier (1.0 = default)
    order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    parent_id: str | None = None
    blurb: str | None = None
    description: str | None = None
    image: str | None = None
    icon: str | None = None
    image_scale: float | None = None
    order: int | None = None
