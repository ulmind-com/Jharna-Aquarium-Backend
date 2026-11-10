from pydantic import BaseModel, Field


class DeliveryConfig(BaseModel):
    # Free delivery threshold
    free_above: float = 499             # order subtotal for free delivery (0 = off)

    # Home State Pricing
    home_state: str = "West Bengal"
    home_base_fee: float = 65           # flat fee for up to base_weight_kg
    home_base_weight_kg: float = 2      # plants are heavier
    home_extra_fee_per_kg: float = 25   # charge per extra kg above base weight

    # Rest of India Pricing
    rest_base_fee: float = 99           # flat fee for up to base_weight_kg
    rest_base_weight_kg: float = 2
    rest_extra_fee_per_kg: float = 35


class ShopConfig(BaseModel):
    name: str = "MyGarden"
    address: str = ""
    phone: str = ""
    email: str = ""          # support email surfaced to customers (chat, help)
    state: str = ""          # seller's state — same-state order = CGST+SGST, else IGST
    lat: float | None = None
    lng: float | None = None


class SocialLink(BaseModel):
    label: str = ""                    # e.g. "Instagram"
    href: str = ""                     # full profile URL


class SupportConfig(BaseModel):
    """
    The support card on the storefront Contact page.

    The number/email/address themselves live in ShopConfig so they stay a single
    source of truth; everything else the card renders is editable here. A blank
    string means "hide that row", so the admin can drop a channel without code.
    """
    title: str = "Stuck with plant care? We're here to help."
    note: str = "Reach us on whichever channel suits you."
    hotline_label: str = "Hotline"
    email_label: str = "Email"
    address_label: str = "Nursery"
    whatsapp: str = ""                 # display number; blank hides the row
    whatsapp_label: str = "SMS / WhatsApp"
    whatsapp_message: str = "Hi, I have a question about your plants."
    hours: str = "Open 10am – 7pm IST, every day"
    socials: list[SocialLink] = Field(default_factory=lambda: [
        SocialLink(label="Instagram", href=""),
        SocialLink(label="Facebook", href=""),
    ])


class PlantGuaranteeConfig(BaseModel):
    """Plant health guarantee settings."""
    enabled: bool = True
    days: int = 30
    label: str = "30-Day Plant Guarantee"
    description: str = "If your plant doesn't survive within 30 days, we'll replace it free of charge."


class CodConfig(BaseModel):
    """Cash on delivery availability. `max_order` is the highest order total
    we're willing to hand to a courier as cash (0 = no ceiling)."""
    enabled: bool = True
    max_order: float = 20000
    label: str = "Cash on Delivery"
    note: str = "Pay in cash when your plants are delivered."


class RewardMilestone(BaseModel):
    """One stop on the cart's unlock rail."""
    amount: float = 0                  # cart subtotal that unlocks this reward
    label: str = ""                    # "Free Shipping", "Free gift", "₹100 off"
    caption: str = ""                  # optional second line under the label
    icon: str = ""                     # PNG uploaded from the admin panel
    kind: str = "gift"                 # shipping | gift | discount — picks the fallback art


class RewardsConfig(BaseModel):
    """The green-and-yellow unlock rail shown in the cart.

    Everything a customer sees here is editable from the admin panel: how many
    stops there are, what each one is worth, what it is called and which PNG
    sits on it.
    """
    enabled: bool = True
    show_in_cart: bool = True
    show_sticky_bar: bool = True
    # `{amount}` is the gap still to close, `{reward}` the next stop's label.
    teaser: str = "Add {amount} more to unlock {reward}"
    unlocked: str = "All rewards unlocked"
    milestones: list[RewardMilestone] = Field(default=[
        RewardMilestone(amount=499, label="Free Shipping", kind="shipping"),
        RewardMilestone(amount=899, label="Free gift", kind="gift"),
        RewardMilestone(amount=1499, label="₹100 off", kind="discount"),
        RewardMilestone(amount=2499, label="₹300 off", kind="discount"),
    ])


class Settings(BaseModel):
    currency: str = "₹"
    currency_code: str = "INR"
    tax_rate: float = 0.05             # 5%

    shop: ShopConfig = ShopConfig()
    delivery: DeliveryConfig = DeliveryConfig()
    support: SupportConfig = SupportConfig()
    plant_guarantee: PlantGuaranteeConfig = PlantGuaranteeConfig()
    cod: CodConfig = CodConfig()
    rewards: RewardsConfig = RewardsConfig()

    announcements: list[str] = Field(default=[
        "🌿 Free shipping on orders above ₹499",
        "🌱 30-Day Plant Guarantee on all plants",
        "🪴 Buy any 4 plants @ ₹1,199",
        "📞 Support 10am–7pm IST, all days",
    ])


class SettingsUpdate(BaseModel):
    currency: str | None = None
    currency_code: str | None = None
    tax_rate: float | None = None

    shop: ShopConfig | None = None
    delivery: DeliveryConfig | None = None
    support: SupportConfig | None = None
    plant_guarantee: PlantGuaranteeConfig | None = None
    cod: CodConfig | None = None
    rewards: RewardsConfig | None = None
    announcements: list[str] | None = None
