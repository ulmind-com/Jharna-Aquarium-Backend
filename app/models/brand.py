from pydantic import BaseModel, Field

class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=100)
    logo: str | None = None
