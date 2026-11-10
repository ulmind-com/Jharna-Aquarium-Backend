from pydantic import BaseModel, Field

class ProductLineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    brand: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=100)
