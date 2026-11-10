from pydantic import BaseModel, Field


class OrderItemIn(BaseModel):
    product_id: str
    qty: int = Field(ge=1)
    size_variant: str | None = None     # "Small", "Medium", "Large" etc.
    pot_type: str | None = None         # "Nursery Pot", "Ceramic Pot", etc.


class Address(BaseModel):
    tag: str = "Home"          # Home / Work / Other
    name: str = ""
    house: str = ""            # House / Flat / Block no
    area: str = ""             # apartment / road / area
    city: str = ""
    state: str = ""
    pincode: str = ""
    phone: str = ""
    lat: float | None = None
    lng: float | None = None


class OrderCreate(BaseModel):
    items: list[OrderItemIn]
    address: Address
    payment_method: str = "online"
    coupon_code: str | None = None
    is_gift: bool = False
    gift_note: str | None = None        # hand-written note for gifting


class OrderVerify(BaseModel):
    order_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

class BulkStatusUpdate(BaseModel):
    order_ids: list[str]
    status: str
