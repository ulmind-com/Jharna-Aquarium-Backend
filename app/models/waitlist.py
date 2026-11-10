from datetime import datetime, UTC
from typing import Annotated
from pydantic import BaseModel, Field, ConfigDict
from pydantic.functional_validators import BeforeValidator

PyObjectId = Annotated[str, BeforeValidator(str)]

class WaitlistRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId | None = Field(alias="_id", default=None)
    user_id: str
    product_id: str
    size_name: str | None = None       # which size variant they're waiting for
    status: str = "pending"  # pending | notified
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class WaitlistCreate(BaseModel):
    product_id: str
    size_name: str | None = None
