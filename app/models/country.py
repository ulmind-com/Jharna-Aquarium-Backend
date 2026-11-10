from pydantic import BaseModel, Field

class CountryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=120)
