from datetime import datetime
from pydantic import BaseModel, Field

class ComboIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    active: bool = True
    
    qty: int = Field(ge=2)
    price: float = Field(ge=0)
    
    product_ids: list[str] = Field(default_factory=list)
    weight_target: int | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
