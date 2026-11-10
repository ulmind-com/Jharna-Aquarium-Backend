"""Seed the nursery with an admin, plant categories and demo plant products.

Products use the current SizeVariant schema (name / pot_type / price / mrp /
stock / images) so pricing, stock and images resolve correctly end to end.

Run:  python -m scripts.seed_nursery
"""
import asyncio
from datetime import datetime, timezone

from app.core.security import hash_password
from app.db.mongodb import connect_to_mongo, get_db
from app.models.product import ProductCreate

ADMIN = {"name": "Admin", "email": "admin@shop.com", "password": "admin123"}

IMG = "https://images.unsplash.com/"
PHOTOS = {
    "spider": f"{IMG}photo-1572688484438-313a6e50c333?w=900",
    "money": f"{IMG}photo-1602923668104-8f9e03e77e62?w=900",
    "peace": f"{IMG}photo-1593691509543-c55fb32d8de5?w=900",
    "snake": f"{IMG}photo-1593482892290-f54927ae1bb6?w=900",
    "areca": f"{IMG}photo-1545241047-6083a3684587?w=900",
    "aloe": f"{IMG}photo-1596547609652-9cf5d8d76921?w=900",
    "anthurium": f"{IMG}photo-1509937528035-ad76254b0356?w=900",
    "zz": f"{IMG}photo-1632207691143-643e2a9a9361?w=900",
}


def variants(base_small, stock=25):
    """Small / Medium / Large pot variants around a base small price."""
    return [
        {"name": "Small", "pot_type": "Nursery Pot", "pot_size": "4 inch",
         "height": "6-8 inches", "price": base_small, "mrp": round(base_small * 1.4),
         "stock": stock, "images": []},
        {"name": "Medium", "pot_type": "Ceramic Pot", "pot_size": "6 inch",
         "height": "10-14 inches", "price": round(base_small * 2), "mrp": round(base_small * 2.6),
         "stock": stock, "images": []},
        {"name": "Large", "pot_type": "Ceramic Pot", "pot_size": "8 inch",
         "height": "16-22 inches", "price": round(base_small * 3.2), "mrp": round(base_small * 4),
         "stock": max(6, stock // 2), "images": []},
    ]


def plant(title, key, base, cat, *, desc, tags, spec, bestseller=False, new=False, featured=False):
    return ProductCreate(
        title=title,
        short_description=desc,
        description=desc,
        tags=tags,
        category_id=cat,
        mrp=round(base * 1.4),
        price=base,
        cgst=2.5, sgst=2.5, igst=5.0,
        shipping_weight=800,
        images=[PHOTOS[key]],
        sizes=variants(base),
        plant_spec=spec,
        care_tips=[
            "Water when the top inch of soil feels dry",
            "Keep in bright, indirect light",
            "Avoid overwatering — let excess drain out",
        ],
        includes=["Plant", "Pot", "Potting Soil"],
        warranty="30-day plant replacement guarantee",
        stock=30,
        rating=4.6,
        review_count=48,
        sold_count=120,
        is_active=True,
        is_bestseller=bestseller,
        is_new_arrival=new,
        is_featured=featured,
    ).model_dump()


async def main():
    await connect_to_mongo()
    db = get_db()

    if not await db.users.find_one({"email": ADMIN["email"]}):
        await db.users.insert_one({
            "name": ADMIN["name"], "email": ADMIN["email"], "phone": None,
            "password": hash_password(ADMIN["password"]), "role": "admin",
            "addresses": [], "fcm_tokens": [], "created_at": datetime.now(timezone.utc),
        })
        print(f"Admin -> {ADMIN['email']} / {ADMIN['password']}")

    async def cat(name, slug, icon, order, image):
        existing = await db.categories.find_one({"slug": slug})
        if existing:
            await db.categories.update_one({"_id": existing["_id"]}, {"$set": {"image": image}})
            return str(existing["_id"])
        res = await db.categories.insert_one({
            "name": name, "slug": slug, "parent_id": None,
            "description": f"{name} for your home & garden", "image": image,
            "icon": icon, "order": order,
        })
        return str(res.inserted_id)

    U = "https://images.unsplash.com/"
    indoor = await cat("Indoor Plants", "indoor-plants", "🪴", 1, f"{U}photo-1485955900006-10f4d324d411?w=500")
    air = await cat("Air Purifying", "air-purifying", "🌿", 2, f"{U}photo-1593482892290-f54927ae1bb6?w=500")
    flowering = await cat("Flowering Plants", "flowering-plants", "🌸", 3, f"{U}photo-1509937528035-ad76254b0356?w=500")
    low = await cat("Low Maintenance", "low-maintenance", "🌱", 4, f"{U}photo-1632207691143-643e2a9a9361?w=500")

    def sp(**kw):
        base = {"plant_type": "Indoor", "sunlight": "Bright Indirect",
                "watering": "Weekly", "difficulty_level": "Easy", "air_purifying": True,
                "pet_safe": False, "season": "All Season"}
        base.update(kw)
        return base

    products = [
        plant("Chlorophytum Spider Plant", "spider", 249, air,
              desc="A hardy air-purifying favourite with arching striped leaves.",
              tags=["air purifying", "pet safe", "easy care"],
              spec=sp(pet_safe=True, common_names=["Spider Plant", "Ribbon Plant"]),
              bestseller=True, featured=True),
        plant("Money Plant Variegated", "money", 299, indoor,
              desc="Lucky trailing vine with creamy variegated foliage.",
              tags=["lucky", "trailing", "low light"],
              spec=sp(sunlight="Low Light", common_names=["Pothos", "Devil's Ivy"]),
              bestseller=True),
        plant("Peace Lily Plant", "peace", 349, flowering,
              desc="Elegant white blooms and glossy leaves that purify air.",
              tags=["flowering", "air purifying"],
              spec=sp(flowering=True, flower_color="White"), featured=True),
        plant("Snake Plant (Sansevieria)", "snake", 279, low,
              desc="Nearly indestructible upright plant that thrives on neglect.",
              tags=["low maintenance", "air purifying"],
              spec=sp(watering="Every 2 weeks", sunlight="Low to Bright"),
              bestseller=True),
        plant("Areca Palm", "areca", 449, air,
              desc="Feathery tropical palm that brings a lush, breezy feel indoors.",
              tags=["air purifying", "tropical"],
              spec=sp(height_range="2-4 feet"), new=True),
        plant("Aloe Vera Plant", "aloe", 199, low,
              desc="Succulent with soothing gel and minimal water needs.",
              tags=["succulent", "medicinal", "low maintenance"],
              spec=sp(watering="Every 2 weeks", sunlight="Bright Direct", medicinal=True)),
        plant("Anthurium Red Plant", "anthurium", 399, flowering,
              desc="Striking heart-shaped red blooms almost all year round.",
              tags=["flowering", "gifting"],
              spec=sp(flowering=True, flower_color="Red"), new=True, featured=True),
        plant("ZZ Plant (Zamioculcas)", "zz", 329, low,
              desc="Glossy, drought-tolerant plant perfect for busy homes and offices.",
              tags=["low maintenance", "low light"],
              spec=sp(sunlight="Low Light", watering="Every 2-3 weeks")),
    ]

    inserted = 0
    for p in products:
        if await db.products.find_one({"title": p["title"]}):
            continue
        p["created_at"] = datetime.now(timezone.utc)
        await db.products.insert_one(p)
        inserted += 1
    print(f"Categories ready; {inserted} plant products inserted "
          f"(total now {await db.products.count_documents({})}).")


if __name__ == "__main__":
    asyncio.run(main())
