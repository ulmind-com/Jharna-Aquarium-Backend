from pydantic import BaseModel, Field, ConfigDict


class PlantSpec(BaseModel):
    """Plant-specific specifications — displayed on the product detail page."""
    plant_type: str | None = None          # Indoor, Outdoor, Indoor/Outdoor
    sunlight: str | None = None            # Full Sun, Partial Shade, Low Light, Bright Indirect
    watering: str | None = None            # Daily, Alternate Days, Weekly, Twice a Week
    difficulty_level: str | None = None    # Easy, Medium, Hard
    height_range: str | None = None        # "6-12 inches", "1-3 feet"
    spread: str | None = None              # "6-12 inches"
    flowering: bool = False
    flower_color: str | None = None
    fragrant: bool = False
    pet_safe: bool = False
    air_purifying: bool = False
    medicinal: bool = False
    season: str | None = None              # All Season, Summer, Winter, Monsoon
    soil_type: str | None = None           # Well-drained, Loamy, Sandy, Red Soil
    growth_rate: str | None = None         # Slow, Medium, Fast
    max_height: str | None = None          # "Up to 6 feet"
    origin: str | None = None              # "Tropical Asia"
    scientific_name: str | None = None     # "Spathiphyllum"
    common_names: list[str] = Field(default_factory=list)  # alternate names
    temperature_range: str | None = None   # "18-30°C"
    humidity: str | None = None            # Low, Medium, High


class SizeVariant(BaseModel):
    """Plant size / pot combination variant."""
    name: str                              # "Small", "Medium", "Large", "XL"
    pot_size: str | None = None            # "4 inch", "6 inch", "8 inch", "10 inch"
    pot_type: str | None = None            # "Nursery Pot", "Ceramic Pot", "GraPot", "Terracotta"
    pot_color: str | None = None           # "White", "Black", "Terracotta"
    height: str | None = None              # "6-8 inches" (plant height at this size)
    price: float | None = None             # selling price for this size
    mrp: float | None = None               # MRP for this size
    discount_pct: float | None = None      # discount % for this size
    stock: int = 0
    images: list[str] = []
    sku: str | None = None                 # per-variant SKU


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    short_description: str | None = None
    tags: list[str] = Field(default_factory=list)
    brand: str | None = None
    category_id: str | None = None
    # Extra shelves the product also belongs to — "Shop by Space" rooms and any
    # other cross-cutting collection. The catalogue matches either field, so a
    # plant can sit in Bedroom and Office without losing its home category.
    extra_category_ids: list[str] = Field(default_factory=list)

    sku: str | None = None
    shipping_weight: float | None = None

    mrp: float = Field(ge=0)                    # base MRP (struck through)
    price: float = Field(ge=0)                  # base selling price
    discount_pct: float = Field(default=0, ge=0, le=95)  # admin extra discount
    discount_on: str = "price"                  # "mrp" | "price"

    cgst: float | None = None                   # CGST % (same-state orders)
    sgst: float | None = None                   # SGST % (same-state orders)
    igst: float | None = None                   # IGST % (inter-state orders)

    images: list[str] = []                      # general gallery
    sizes: list[SizeVariant] = []               # size/pot variants

    # --- PLANT SPECIFIC ---
    plant_spec: PlantSpec = Field(default_factory=PlantSpec)
    care_instructions: str | None = None        # detailed care paragraph
    care_tips: list[str] = Field(default_factory=list)  # quick bullet tips
    includes: list[str] = Field(default_factory=list)   # "Plant", "Pot", "Soil", "Pebbles"
    warranty: str | None = None                 # "30-day plant guarantee"

    stock: int = 0                              # used when there are no size variants
    low_stock_threshold: int = 5

    rating: float = Field(default=0, ge=0, le=5)
    review_count: int = 0
    sold_count: int = 0

    is_active: bool = True
    is_featured: bool = False
    is_bestseller: bool = False
    is_new_arrival: bool = False


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    description: str | None = None
    short_description: str | None = None
    tags: list[str] | None = None
    brand: str | None = None
    category_id: str | None = None
    extra_category_ids: list[str] | None = None
    sku: str | None = None
    shipping_weight: float | None = None
    mrp: float | None = None
    price: float | None = None
    discount_pct: float | None = None
    discount_on: str | None = None
    cgst: float | None = None
    sgst: float | None = None
    igst: float | None = None

    images: list[str] | None = None
    sizes: list[SizeVariant] | None = None

    # --- PLANT SPECIFIC ---
    plant_spec: PlantSpec | None = None
    care_instructions: str | None = None
    care_tips: list[str] | None = None
    includes: list[str] | None = None
    warranty: str | None = None

    stock: int | None = None
    low_stock_threshold: int | None = None
    rating: float | None = None
    review_count: int | None = None
    sold_count: int | None = None
    is_active: bool | None = None
    is_featured: bool | None = None
    is_bestseller: bool | None = None
    is_new_arrival: bool | None = None
