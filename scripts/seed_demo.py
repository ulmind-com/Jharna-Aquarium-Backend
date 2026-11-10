"""Seed demo catalogue: 3 top categories (Kids, Mens, Womens) + sub-categories
and 20 products covering every field permutation (discount types, colour
variants, size systems, stock levels, brands, active/inactive).

IMPORTANT: rating, review_count and sold_count are DYNAMIC — rating/reviews are
computed from real customer reviews and sold_count from delivered orders. They
are NEVER seeded; demo products start at zero, exactly like an admin-created one.

Images are intentionally left empty — add them from the admin panel.
Idempotent: re-running skips categories/products that already exist (by slug/title)
and re-zeroes the dynamic fields on the seeded demo products.

Run:  cd backend && python -m scripts.seed_demo
"""
import asyncio
from datetime import datetime, timezone

from app.db.mongodb import connect_to_mongo, get_db
from app.services.pricing import price_span


def now():
    return datetime.now(timezone.utc)


def col(name, hex_, stock, price=None, mrp=None, discount_pct=None, discount_on=None, sizes=None):
    """A colour variant (images added later from admin). Optional per-colour
    price/mrp/discount override + per-size rows."""
    return {"name": name, "hex": hex_, "images": [], "price": price, "mrp": mrp,
            "discount_pct": discount_pct, "discount_on": discount_on,
            "stock": stock, "sizes": sizes or []}


def sz(size, stock, price=None, mrp=None, discount_pct=None, discount_on=None):
    """A per-size row inside a colour (optional price/mrp/discount override + stock)."""
    return {"size": size, "price": price, "mrp": mrp,
            "discount_pct": discount_pct, "discount_on": discount_on, "stock": stock}


async def main():
    await connect_to_mongo()
    db = get_db()

    async def cat(name, slug, parent=None, order=0):
        ex = await db.categories.find_one({"slug": slug})
        if ex:
            return str(ex["_id"])
        res = await db.categories.insert_one(
            {"name": name, "slug": slug, "parent_id": parent, "image": None, "order": order}
        )
        return str(res.inserted_id)

    # ── Top-level categories ────────────────────────────────────────────────
    kids = await cat("Kids", "kids", None, 0)
    mens = await cat("Mens", "mens", None, 1)
    womens = await cat("Womens", "womens", None, 2)

    # ── Sub-categories ──────────────────────────────────────────────────────
    kids_boys = await cat("Boys Clothing", "kids-boys", kids, 0)
    kids_girls = await cat("Girls Clothing", "kids-girls", kids, 1)
    kids_shoes = await cat("Kids Footwear", "kids-footwear", kids, 2)

    mens_tees = await cat("T-Shirts", "mens-tshirts", mens, 0)
    mens_jeans = await cat("Jeans", "mens-jeans", mens, 1)
    mens_shoes = await cat("Footwear", "mens-footwear", mens, 2)

    wom_kurti = await cat("Kurtis", "womens-kurtis", womens, 0)
    wom_saree = await cat("Sarees", "womens-sarees", womens, 1)
    wom_dress = await cat("Dresses", "womens-dresses", womens, 2)

    # ── 20 products, every permutation ──────────────────────────────────────
    # Only catalogue fields — NO rating/review_count/sold_count (those are dynamic).
    products = [
        # KIDS · Boys
        {"title": "Boys Printed T-Shirt", "brand": "H&M Kids", "category_id": kids_boys,
         "description": "Soft cotton round-neck tee with fun prints.",
         "mrp": 799, "price": 499, "sizes": ["2-3Y", "4-5Y", "6-7Y"],
         "colors": [col("Red", "#E23744", 12), col("Blue", "#2F6BFF", 8), col("Yellow", "#F5C518", 0)]},

        {"title": "Boys Denim Shorts", "brand": "U.S. Polo Assn.", "category_id": kids_boys,
         "description": "Durable denim shorts with adjustable waist.",
         "mrp": 1299, "price": 899, "discount_pct": 10, "discount_on": "price",
         "sizes": ["3-4Y", "5-6Y", "7-8Y"], "colors": [col("Navy", "#1F2A44", 15)]},

        # KIDS · Girls
        {"title": "Girls Party Frock", "brand": "Cutecumber", "category_id": kids_girls,
         "description": "Flared party frock with sequin detailing.",
         "mrp": 2499, "price": 1799, "sizes": ["2-3Y", "4-5Y"],
         "colors": [col("Pink", "#FF6FA3", 6), col("Maroon", "#7B1F2B", 3)]},

        {"title": "Girls Legging Pack of 3", "brand": "Max Kids", "category_id": kids_girls,
         "description": "Everyday stretch leggings, pack of three.",
         "mrp": 699, "price": 699, "sizes": ["S", "M", "L"], "colors": [], "stock": 40},  # no discount, no variants

        # KIDS · Footwear
        {"title": "Kids Sports Shoes", "brand": "Campus", "category_id": kids_shoes,
         "description": "Lightweight everyday sports shoes with velcro strap.",
         "mrp": 1499, "price": 1199, "discount_pct": 20, "discount_on": "mrp",
         "sizes": ["10", "11", "12", "13"],
         "colors": [col("White", "#FFFFFF", 10), col("Black", "#1C1613", 5)]},

        {"title": "Kids Casual Sandals", "brand": "Bata", "category_id": kids_shoes,
         "description": "Comfy summer sandals for everyday wear.",
         "mrp": 599, "price": 449, "sizes": ["8", "9", "10"],
         "colors": [col("Brown", "#7A4B2B", 0), col("Blue", "#2F6BFF", 0)]},  # all out of stock

        # MENS · T-Shirts
        {"title": "Men's Cotton Crew Tee", "brand": "Levi's", "category_id": mens_tees,
         "description": "Classic 100% cotton crew-neck t-shirt.",
         "mrp": 1199, "price": 799, "sizes": ["S", "M", "L", "XL", "XXL"],
         "colors": [col("Black", "#1C1613", 25), col("White", "#FFFFFF", 30),
                    col("Navy", "#1F2A44", 12), col("Olive", "#708238", 5)]},

        {"title": "Men's Oversized Tee", "brand": "Bewakoof", "category_id": mens_tees,
         "description": "Drop-shoulder oversized fit tee.",
         "mrp": 999, "price": 399, "sizes": ["M", "L", "XL"],
         "colors": [col("Beige", "#E8DCC8", 18), col("Black", "#1C1613", 20)]},  # ~60% off

        {"title": "Men's Polo T-Shirt", "brand": "U.S. Polo Assn.", "category_id": mens_tees,
         "description": "Pique-knit polo with tipped collar.",
         "mrp": 1799, "price": 1799, "discount_pct": 15, "discount_on": "price",
         "sizes": ["M", "L", "XL"],
         "colors": [col("Maroon", "#7B1F2B", 10), col("Navy", "#1F2A44", 8)]},  # discount via pct, mrp==price

        # MENS · Jeans
        {"title": "Men's Slim Fit Jeans", "brand": "Wrangler", "category_id": mens_jeans,
         "description": "Stretchable slim-fit denim.",
         "mrp": 2999, "price": 1999, "sizes": ["28", "30", "32", "34", "36"],
         "colors": [col("Blue", "#2F6BFF", 14), col("Black", "#1C1613", 9), col("Grey", "#9AA0A6", 4)]},

        {"title": "Men's Distressed Jeans", "brand": "Spykar", "category_id": mens_jeans,
         "description": "Ripped-knee tapered jeans.",
         "mrp": 3499, "price": 2499, "discount_pct": 10, "discount_on": "mrp",
         "sizes": ["30", "32", "34"], "colors": [col("Blue", "#3B5998", 3)]},  # low stock

        {"title": "Men's Cargo Joggers", "brand": "HRX", "category_id": mens_jeans,
         "description": "Utility cargo joggers with side pockets.",
         "mrp": 2199, "price": 1499, "sizes": ["S", "M", "L", "XL"], "colors": [], "stock": 0},  # out of stock

        # MENS · Footwear
        {"title": "Men's Running Sneakers", "brand": "New Balance", "category_id": mens_shoes,
         "description": "Cushioned running sneakers for daily miles.",
         "mrp": 5999, "price": 3999, "sizes": ["7", "8", "9", "10", "11"],
         "colors": [col("Orange", "#F26A21", 8), col("Black", "#1C1613", 12), col("Blue", "#2F6BFF", 6)]},

        {"title": "Men's Formal Derby Shoes", "brand": "Hush Puppies", "category_id": mens_shoes,
         "description": "Genuine leather derby formal shoes.",
         "mrp": 4499, "price": 3199, "discount_pct": 5, "discount_on": "price",
         "sizes": ["7", "8", "9", "10"],
         "colors": [col("Brown", "#7A4B2B", 7), col("Black", "#1C1613", 9)]},

        {"title": "Men's Flip Flops", "brand": "Adidas", "category_id": mens_shoes,
         "description": "Everyday cushioned flip flops.",
         "mrp": 899, "price": 599, "sizes": ["Free Size"], "colors": [col("Black", "#1C1613", 40)]},  # Free Size

        # WOMENS · Kurtis
        {"title": "Women's Anarkali Kurti", "brand": "Libas", "category_id": wom_kurti,
         "description": "Floor-length Anarkali with intricate print.",
         "mrp": 2299, "price": 1299, "sizes": ["S", "M", "L", "XL", "XXL"],
         "colors": [col("Teal", "#0E8F8F", 10), col("Maroon", "#7B1F2B", 6), col("Mustard", "#D4A017", 4)]},

        {"title": "Women's Straight Cotton Kurti", "brand": "W", "category_id": wom_kurti,
         "description": "Breathable straight-cut cotton kurti.",
         "mrp": 1599, "price": 1599, "sizes": ["M", "L"], "colors": [col("Pink", "#FF6FA3", 12)]},  # no discount

        # WOMENS · Sarees
        {"title": "Banarasi Silk Saree", "brand": "Kalki Fashion", "category_id": wom_saree,
         "description": "Handwoven Banarasi silk with zari border.",
         "mrp": 8999, "price": 5999, "sizes": ["Free Size"],
         "colors": [col("Red", "#E23744", 5), col("Gold", "#D4AF37", 3), col("Green", "#3BB54A", 2)]},

        {"title": "Georgette Printed Saree", "brand": "Soch", "category_id": wom_saree,
         "description": "Lightweight georgette saree with floral print.",
         "mrp": 2499, "price": 1499, "discount_pct": 20, "discount_on": "mrp",
         "sizes": ["Free Size"],
         "colors": [col("Blue", "#2F6BFF", 0), col("Pink", "#FF6FA3", 0)]},  # out of stock

        # WOMENS · Dresses  (inactive — demo of hidden/draft state, toggle on in admin)
        {"title": "Women's Bodycon Dress", "brand": "Zara", "category_id": wom_dress,
         "description": "Ribbed bodycon midi dress. (Set inactive as a draft demo.)",
         "mrp": 3499, "price": 2799, "sizes": ["XS", "S", "M", "L"],
         "colors": [col("Black", "#1C1613", 15), col("Red", "#E23744", 8)], "is_active": False},
    ]

    inserted = 0
    for p in products:
        if await db.products.find_one({"title": p["title"]}):
            continue
        p.setdefault("images", [])
        p.setdefault("discount_pct", 0)
        p.setdefault("discount_on", "price")
        p.setdefault("colors", [])
        p.setdefault("sizes", [])
        p.setdefault("stock", 0)
        p.setdefault("low_stock_threshold", 5)
        p.setdefault("is_active", True)
        # Dynamic fields always start at zero — reviews/orders fill them in.
        p["rating"] = 0
        p["review_count"] = 0
        p["sold_count"] = 0
        p["created_at"] = now()
        await db.products.insert_one(p)
        inserted += 1

    # Keep the dynamic fields at their real baseline on the seeded demo products
    # (fixes any earlier hard-coded values). Only touches these exact demo titles.
    titles = [p["title"] for p in products]
    reset = await db.products.update_many(
        {"title": {"$in": titles}},
        {"$set": {"rating": 0, "review_count": 0, "sold_count": 0}},
    )

    # Feed EVERY colour-variant product with a per-size matrix + a little
    # price/discount variety, so all products exercise the new config:
    #   - biggest size costs ~10% more (size-level price)
    #   - 2nd colour ~5% pricier (colour-level price)
    #   - 3rd colour gets 10% off MRP (colour-level discount)
    #   - first colour's first size gets 10% off (size-level discount)
    #   - one size on the last colour is out of stock (realism)
    # Products with no colour variants (or no sizes) are left as-is.
    variants = 0
    async for p in db.products.find({}):
        colors = [c for c in (p.get("colors") or []) if isinstance(c, dict)]
        base_sizes = p.get("sizes") or []
        base_price = p.get("price") or 0
        if not colors or not base_sizes or not base_price:
            continue
        new_colors = []
        n_c, n_s = len(colors), len(base_sizes)
        for ci, c in enumerate(colors):
            colour_stock = int(c.get("stock", 0)) or (n_s * 4)
            per = max(1, colour_stock // n_s)
            rows = []
            for si, s in enumerate(base_sizes):
                price = round(base_price * 1.1) if si == n_s - 1 else None      # biggest size +10%
                stock = 0 if (ci == n_c - 1 and si == n_s // 2) else per        # one size sold out
                disc = 10 if (ci == 0 and si == 0) else None                    # size-level discount
                on = "price" if disc else None
                rows.append(sz(s, stock, price=price, discount_pct=disc, discount_on=on))
            new_colors.append(col(
                c.get("name", ""), c.get("hex", "#000000"), 0,
                price=round(base_price * 1.05) if ci == 1 else None,            # 2nd colour pricier
                discount_pct=10 if ci == 2 else None,                          # 3rd colour 10% off
                discount_on="price" if ci == 2 else None,
                sizes=rows,
            ) | {"images": c.get("images", [])})
        await db.products.update_one({"_id": p["_id"]}, {"$set": {"colors": new_colors}})
        variants += 1

    # Per-product GST as CGST/SGST/IGST (Indian apparel slabs: cheapest variant
    # < ₹1000 -> 5% GST, else 12%). Same-state = CGST+SGST, inter-state = IGST.
    taxed = 0
    async for p in db.products.find({}):
        fp = price_span(p).get("final_price") or (p.get("price") or 0)
        total = 5 if fp < 1000 else 12
        await db.products.update_one(
            {"_id": p["_id"]},
            {"$set": {"cgst": total / 2, "sgst": total / 2, "igst": total},
             "$unset": {"tax_pct": ""}},
        )
        taxed += 1

    total = await db.products.count_documents({})
    cats = await db.categories.count_documents({})
    print(f"Inserted {inserted} new products; reset dynamic fields on {reset.modified_count} demo products.")
    print(f"Fed per-colour/per-size price+discount+stock to {variants} colour-variant products.")
    print(f"Set CGST/SGST/IGST on {taxed} products (5% under ₹1000, else 12%).")
    print(f"Catalogue now has {total} products, {cats} categories.")
    print("Done. rating/reviews/sold stay dynamic. Add images from the admin panel.")


if __name__ == "__main__":
    asyncio.run(main())
