"""Seed the storefront Offers page: two live coupons + a richer sale catalogue.

The coupons land in the same `coupons` collection the admin panel edits, so they
show up under Admin → Coupons and can be changed/disabled from there. They also
join the checkout auto-apply pool, so they discount any other product a customer
buys.

Run:  python -m scripts.seed_offers
"""
import asyncio
from datetime import datetime, timezone

from app.db.mongodb import connect_to_mongo, get_db
from app.models.product import ProductCreate

U = "https://images.unsplash.com/"

COUPONS = [
    {
        "code": "FREESHIP499",
        "type": "flat",
        "value": 0,
        "min_order": 499,
        "max_discount": 0,
        "active": True,
        "first_order_only": False,
        "free_shipping": True,
        "usage_limit": 0,
        "limit_per_user": 0,
        "valid_from": None,
        "valid_until": None,
        "description": "Free shipping on all orders above ₹499",
    },
    {
        "code": "SAVE10",
        "type": "percent",
        "value": 10,
        "min_order": 1499,
        "max_discount": 300,
        "active": True,
        "first_order_only": False,
        "free_shipping": False,
        "usage_limit": 0,
        "limit_per_user": 0,
        "valid_from": None,
        "valid_until": None,
        "description": "Get 10% off on orders above ₹1499 (up to ₹300)",
    },
]

PHOTOS = {
    "jade": f"{U}photo-1463320898484-cdee8141c787?w=900",
    "golden": f"{U}photo-1536882240095-0379873feb4e?w=900",
    "monstera": f"{U}photo-1614594975525-e45190c55d0b?w=900",
    "syngonium": f"{U}photo-1591958911259-bee2173bdccc?w=900",
    "bamboo": f"{U}photo-1512428813834-c702c7702b78?w=900",
    "fittonia": f"{U}photo-1604762524889-3e2fcc145683?w=900",
    "peperomia": f"{U}photo-1466781783364-36c955e42a7f?w=900",
    "jasmine": f"{U}photo-1565011523534-747a8601f10a?w=900",
}


def variants(base, stock=25):
    return [
        {"name": "Small", "pot_type": "Nursery Pot", "pot_size": "4 inch",
         "height": "6-8 inches", "price": base, "mrp": round(base * 1.35),
         "stock": stock, "images": []},
        {"name": "Medium", "pot_type": "Ceramic Pot", "pot_size": "6 inch",
         "height": "10-14 inches", "price": round(base * 1.9), "mrp": round(base * 2.5),
         "stock": stock, "images": []},
    ]


def plant(title, key, base, *, desc, tags, spec, rating, reviews,
          bestseller=False, new=False, featured=False):
    return ProductCreate(
        title=title,
        short_description=desc,
        description=desc,
        tags=tags,
        mrp=round(base * 1.35),
        price=base,
        cgst=2.5, sgst=2.5, igst=5.0,
        shipping_weight=800,
        images=[PHOTOS[key]],
        sizes=variants(base),
        plant_spec=spec,
        care_tips=[
            "Water when the top inch of soil feels dry",
            "Keep in bright, indirect light",
            "Feed once a month during the growing season",
        ],
        includes=["Plant", "Pot", "Potting Soil"],
        warranty="30-day plant replacement guarantee",
        stock=30,
        rating=rating,
        review_count=reviews,
        sold_count=200,
        is_active=True,
        is_bestseller=bestseller,
        is_new_arrival=new,
        is_featured=featured,
    ).model_dump()


def sp(**kw):
    base = {"plant_type": "Indoor", "sunlight": "Bright Indirect", "watering": "Weekly",
            "difficulty_level": "Easy", "air_purifying": True, "season": "All Season"}
    base.update(kw)
    return base


async def main():
    await connect_to_mongo()
    db = get_db()

    for c in COUPONS:
        existing = await db.coupons.find_one({"code": c["code"]})
        if existing:
            await db.coupons.update_one({"_id": existing["_id"]}, {"$set": c})
            print(f"coupon updated: {c['code']}")
            continue
        doc = {**c, "created_at": datetime.now(timezone.utc), "used_count": 0}
        await db.coupons.insert_one(doc)
        print(f"coupon created: {c['code']}")

    products = [
        plant("Jade Mini Plant", "jade", 249,
              desc="Easy-care lucky succulent", tags=["succulent", "lucky", "low maintenance"],
              spec=sp(watering="Every 2 weeks", sunlight="Bright Direct"),
              rating=4.8, reviews=414, bestseller=True),
        plant("Money Plant Golden", "golden", 249,
              desc="Golden plant, attracts luck", tags=["lucky", "trailing", "low light"],
              spec=sp(sunlight="Low Light"), rating=4.9, reviews=292, bestseller=True),
        plant("Monstera Adansonii Plant", "monstera", 549,
              desc="Playful split leaves, easy to grow", tags=["statement", "trailing"],
              spec=sp(height_range="1-2 feet"), rating=4.8, reviews=118,
              bestseller=True, featured=True),
        plant("Syngonium Pink Plant", "syngonium", 249,
              desc="Soft pink leaves, easy-trailing plant", tags=["pink", "trailing"],
              spec=sp(), rating=4.8, reviews=160, bestseller=True),
        plant("Lucky Bamboo 2 Layer", "bamboo", 399,
              desc="Good luck in water, zero soil mess", tags=["lucky", "water plant", "gifting"],
              spec=sp(watering="Weekly", soil_type="Water"), rating=4.8, reviews=67, new=True),
        plant("Fittonia Green Plant (Nerve Plant)", "fittonia", 299,
              desc="Veined leaves, tabletop charm", tags=["tabletop", "compact"],
              spec=sp(humidity="High"), rating=4.8, reviews=315, bestseller=True),
        plant("Peperomia Green Creeper Plant", "peperomia", 549,
              desc="Trailing creeper, perfect for shelves", tags=["trailing", "shelf"],
              spec=sp(), rating=4.8, reviews=69),
        plant("Jasmine Mogra Plant", "jasmine", 349,
              desc="Fragrant white blooms all summer", tags=["flowering", "fragrant", "outdoor"],
              spec=sp(plant_type="Outdoor", sunlight="Full Sun", flowering=True,
                      flower_color="White", fragrant=True),
              rating=4.7, reviews=204, new=True),
    ]

    inserted = 0
    for p in products:
        if await db.products.find_one({"title": p["title"]}):
            continue
        p["created_at"] = datetime.now(timezone.utc)
        await db.products.insert_one(p)
        inserted += 1
    print(f"{inserted} sale products inserted (total {await db.products.count_documents({})}).")


if __name__ == "__main__":
    asyncio.run(main())
