"""Seed the catalogue with the premium indoor and outdoor plant range.

Forty plants, each with a Wikimedia Commons photograph (see `_plant_photos`),
three pot variants and a filled-in `plant_spec`. Difficulty is set per plant
rather than blanket "Easy", so the Low-Effort Plants band on the home page
actually narrows the catalogue instead of repeating it.

Also builds the starter bundles the Ready to Buy Combos band renders.

Run:  python -m scripts.seed_premium_plants
"""
import asyncio
from datetime import datetime, timezone

from app.db.mongodb import connect_to_mongo, get_db
from app.models.product import ProductCreate
from scripts._plant_photos import PHOTOS

# name, price, difficulty, sunlight, pet_safe, air_purifying, flowering, blurb, extra tags
INDOOR = [
    ("Money Plant (Pothos)", 249, "Easy", "Low Light", False, True, False,
     "Lucky trailing vine that keeps growing in the dimmest corner of the house.", ["lucky", "trailing"]),
    ("Snake Plant", 299, "Easy", "Low to Bright", False, True, False,
     "Nearly indestructible upright leaves that release oxygen through the night.", ["bedroom"]),
    ("Jade Plant", 279, "Easy", "Bright Direct", False, False, False,
     "Plump succulent leaves on a woody trunk — the classic good-fortune plant.", ["succulent", "lucky"]),
    ("ZZ Plant", 349, "Easy", "Low Light", False, True, False,
     "Waxy dark-green fronds that shrug off a fortnight without water.", ["office"]),
    ("Peace Lily", 329, "Easy", "Bright Indirect", False, True, True,
     "Glossy leaves and white sail-shaped blooms that clean the air as they flower.", []),
    ("Monstera Deliciosa", 649, "Moderate", "Bright Indirect", False, True, False,
     "The split-leaf statement plant every living room photograph is built around.", ["statement"]),
    ("Areca Palm", 499, "Moderate", "Bright Indirect", True, True, False,
     "Feathery arching fronds that turn a bare corner into a tropical one.", ["tropical"]),
    ("Aglaonema (Chinese Evergreen)", 399, "Easy", "Low Light", False, True, False,
     "Painted pink and silver foliage that holds its colour away from a window.", []),
    ("Spider Plant", 199, "Easy", "Bright Indirect", True, True, False,
     "Arching striped ribbons that throw out baby plants you can pot on.", ["hanging"]),
    ("Lucky Bamboo", 249, "Easy", "Low Light", False, False, False,
     "Sculpted stalks that live happily in nothing but water and pebbles.", ["lucky", "desk"]),
    ("Fittonia (Nerve Plant)", 199, "Moderate", "Bright Indirect", True, False, False,
     "Tiny leaves veined in white and rose — made for terrariums and desks.", ["terrarium"]),
    ("Calathea", 449, "Hard", "Bright Indirect", True, True, False,
     "Patterned leaves that fold up at dusk and open again each morning.", ["statement"]),
    ("Syngonium (Arrowhead Plant)", 229, "Easy", "Bright Indirect", False, True, False,
     "Arrow-shaped leaves that climb a moss pole or spill from a shelf.", ["trailing"]),
    ("Boston Fern", 349, "Moderate", "Bright Indirect", True, True, False,
     "Soft cascading fronds that love a humid bathroom windowsill.", ["hanging", "bathroom"]),
    ("Aloe Vera", 199, "Easy", "Bright Direct", False, False, False,
     "Thick spears of soothing gel — a first-aid kit that sits on the sill.", ["succulent", "medicinal"]),
    ("Rubber Plant", 449, "Easy", "Bright Indirect", False, True, False,
     "Broad burgundy-green leaves with a high polish, growing tall and upright.", ["statement"]),
    ("Fiddle Leaf Fig", 799, "Hard", "Bright Indirect", False, True, False,
     "Violin-shaped leaves on a slender trunk — demanding, and worth it.", ["statement"]),
    ("Cast Iron Plant", 379, "Easy", "Low Light", True, False, False,
     "Named for what it survives: deep shade, draughts and forgotten watering.", ["office"]),
    ("Philodendron", 299, "Easy", "Bright Indirect", False, True, False,
     "Heart-shaped leaves that trail for metres with almost no encouragement.", ["trailing"]),
    ("Anthurium", 429, "Moderate", "Bright Indirect", False, True, True,
     "Lacquered red blooms that keep coming back for most of the year.", ["gifting"]),
]

OUTDOOR = [
    ("Hibiscus", 299, "Easy", "Full Sun", True, False, True,
     "Dinner-plate blooms in red and coral, opening fresh through the season.", []),
    ("Rose", 349, "Moderate", "Full Sun", True, False, True,
     "The garden classic — scented, repeat-flowering and worth the pruning.", ["fragrant", "gifting"]),
    ("Jasmine", 279, "Easy", "Full Sun", True, False, True,
     "Small white flowers that scent an entire balcony after dark.", ["fragrant"]),
    ("Bougainvillea", 399, "Easy", "Full Sun", False, False, True,
     "Sheets of papery magenta bracts over a wall or a terrace railing.", ["climber"]),
    ("Periwinkle (Vinca)", 149, "Easy", "Full Sun", False, False, True,
     "Tireless little blooms that flower through the hottest months.", ["borders"]),
    ("Croton", 329, "Moderate", "Full Sun", False, False, False,
     "Leaves splashed in yellow, orange and crimson — colour without flowers.", []),
    ("Plumeria (Frangipani)", 549, "Moderate", "Full Sun", False, False, True,
     "Waxy pinwheel flowers with the scent people associate with holidays.", ["fragrant"]),
    ("Oleander", 299, "Easy", "Full Sun", False, False, True,
     "A tough flowering shrub that takes heat, wind and coastal salt.", ["hedge"]),
    ("Gardenia", 449, "Hard", "Bright Indirect", True, False, True,
     "Creamy double blooms with a scent that carries across the garden.", ["fragrant"]),
    ("Marigold", 99, "Easy", "Full Sun", True, False, True,
     "Gold and orange pompoms for festivals, borders and kitchen gardens.", ["borders"]),
    ("Adenium (Desert Rose)", 599, "Easy", "Full Sun", False, False, True,
     "A swollen bonsai-like trunk topped with bright trumpet flowers.", ["bonsai", "succulent"]),
    ("Canna Lily", 249, "Easy", "Full Sun", True, False, True,
     "Bold paddle leaves and hot-coloured flowers on tall upright stems.", []),
    ("Moss Rose (Portulaca)", 129, "Easy", "Full Sun", True, False, True,
     "A succulent ground cover that flowers hardest where nothing else will.", ["succulent", "borders"]),
    ("Bird of Paradise", 899, "Moderate", "Full Sun", False, False, True,
     "Architectural fans of leaf and a flower shaped like a crested bird.", ["statement"]),
    ("Cycas Palm (Sago Palm)", 1299, "Moderate", "Full Sun", False, False, False,
     "A slow, sculptural survivor from the age of dinosaurs — a lifetime plant.", ["statement"]),
    ("Chrysanthemum", 199, "Moderate", "Full Sun", True, False, True,
     "Dense autumn blooms in every colour, cut-and-come-again for vases.", ["seasonal"]),
    ("Petunia", 149, "Easy", "Full Sun", True, False, True,
     "Trumpets of colour that spill over the edge of a balcony planter.", ["hanging"]),
    ("Sunflower", 129, "Easy", "Full Sun", True, False, True,
     "Tall, cheerful and fast — the plant that gets children into gardening.", ["seasonal"]),
    ("Lavender", 399, "Moderate", "Full Sun", True, False, True,
     "Silver foliage and purple spikes that draw bees and calm the evening.", ["fragrant", "herbs"]),
    ("Hydrangea", 649, "Hard", "Bright Indirect", False, False, True,
     "Great mopheads of bloom that shift colour with the soil they grow in.", ["statement"]),
]


# A second indoor range — the shelf, desk and terrarium plants people buy with
# a pot rather than on their own.
INDOOR_EXTRA = [
    ("Peperomia", 229, "Easy", "Bright Indirect", True, True, False,
     "Thick rounded leaves on a compact plant that never outgrows a shelf.", ["desk"]),
    ("Dracaena Marginata", 449, "Easy", "Bright Indirect", False, True, False,
     "Slim canes topped with spiky red-edged leaves — height without bulk.", ["statement"]),
    ("Dieffenbachia (Dumb Cane)", 379, "Easy", "Bright Indirect", False, True, False,
     "Broad cream-splashed leaves that fill a corner quickly.", []),
    ("Croton Petra", 349, "Moderate", "Bright Direct", False, False, False,
     "Leaves in flame colours that deepen the more sun they get.", []),
    ("Schefflera (Umbrella Plant)", 399, "Easy", "Bright Indirect", False, True, False,
     "Glossy leaflets spread like spokes from every stem.", []),
    ("Ponytail Palm", 699, "Easy", "Bright Direct", True, False, False,
     "A swollen water-storing trunk under a spray of curling leaves.", ["succulent"]),
    ("String of Pearls", 299, "Moderate", "Bright Indirect", False, False, False,
     "Strands of bead-like leaves that pour over the rim of a hanging pot.", ["hanging", "succulent"]),
    ("Echeveria Succulent", 179, "Easy", "Bright Direct", True, False, False,
     "A tight rosette of powder-blue leaves — a windowsill in one plant.", ["succulent", "desk"]),
    ("Haworthia Zebra Plant", 199, "Easy", "Bright Indirect", True, False, False,
     "Small dark spears banded in white, happy in a tiny pot forever.", ["succulent", "desk"]),
    ("Kalanchoe", 249, "Easy", "Bright Direct", False, False, True,
     "Clusters of tiny bright flowers over thick succulent leaves.", ["succulent"]),
    ("Christmas Cactus", 349, "Easy", "Bright Indirect", True, False, True,
     "Flat jointed stems that break into pink bloom in the cold months.", ["seasonal"]),
    ("English Ivy", 249, "Easy", "Bright Indirect", False, True, False,
     "A classic trailer that will climb anything you give it.", ["trailing", "hanging"]),
    ("Wandering Jew (Tradescantia)", 199, "Easy", "Bright Indirect", False, False, False,
     "Purple and silver stripes on a plant that roots from any cutting.", ["trailing", "hanging"]),
    ("Coleus", 179, "Easy", "Bright Indirect", False, False, False,
     "Foliage in wine, lime and rose — colour without waiting for a flower.", []),
    ("Begonia Rex", 379, "Moderate", "Bright Indirect", False, False, False,
     "Spiralled leaves painted in silver, purple and deep green.", ["statement"]),
    ("Maranta (Prayer Plant)", 349, "Moderate", "Bright Indirect", True, True, False,
     "Herringbone leaves that fold together like hands each evening.", []),
    ("Alocasia (Elephant Ear)", 599, "Hard", "Bright Indirect", False, True, False,
     "Great arrow-shaped leaves held high on dark upright stems.", ["statement"]),
    ("Bamboo Palm", 549, "Easy", "Bright Indirect", True, True, False,
     "Clumping canes and fine fronds that screen a room without blocking light.", ["tropical"]),
    ("Kentia Palm", 899, "Easy", "Bright Indirect", True, True, False,
     "The palm that tolerates a dim drawing room and still looks expensive.", ["tropical", "statement"]),
    ("Norfolk Island Pine", 649, "Moderate", "Bright Indirect", True, True, False,
     "A living conifer with tiers of soft needles — a year-round tree.", ["seasonal"]),
    ("Asparagus Fern", 249, "Easy", "Bright Indirect", False, True, False,
     "Feathery arching stems that soften the edge of any shelf.", ["hanging"]),
    ("Bird's Nest Fern", 399, "Moderate", "Bright Indirect", True, True, False,
     "Wavy fronds unfurling from a central rosette — a bathroom favourite.", ["bathroom"]),
    ("Staghorn Fern", 749, "Hard", "Bright Indirect", True, True, False,
     "Antler-shaped fronds that mount on a board and hang like sculpture.", ["statement", "hanging"]),
    ("Air Plant (Tillandsia)", 199, "Easy", "Bright Indirect", True, False, False,
     "Grows on nothing at all — a weekly soak is the whole routine.", ["desk"]),
    ("Bromeliad", 449, "Easy", "Bright Indirect", True, False, True,
     "A glossy rosette holding a bloom that lasts for months.", ["tropical"]),
    ("Orchid (Phalaenopsis)", 799, "Moderate", "Bright Indirect", True, False, True,
     "Arching sprays of bloom that hold for weeks — the gifting plant.", ["gifting", "statement"]),
    ("Hoya (Wax Plant)", 449, "Easy", "Bright Indirect", True, False, True,
     "Waxy leaves and star-shaped scented flower clusters.", ["trailing", "fragrant"]),
    ("Pilea (Chinese Money Plant)", 329, "Easy", "Bright Indirect", True, True, False,
     "Round coin leaves on slim stalks, and endless pups to give away.", ["lucky", "desk"]),
    ("Oxalis (Purple Shamrock)", 249, "Easy", "Bright Indirect", False, False, True,
     "Deep purple triangles that open and close with the light.", []),
    ("Ficus Benjamina", 549, "Moderate", "Bright Indirect", False, True, False,
     "A weeping fig that grows into a proper indoor tree.", ["statement"]),
]

# Facet detail the tuples do not carry. Anything not named here takes the
# default, so the sidebar never shows a value nothing was actually given.
GROWTH_RATE = {
    "Slow": {"Snake Plant", "ZZ Plant", "Cast Iron Plant", "Jade Plant", "Cycas Palm (Sago Palm)",
             "Haworthia Zebra Plant", "Ponytail Palm", "Kentia Palm", "Echeveria Succulent",
             "Norfolk Island Pine", "Air Plant (Tillandsia)", "Staghorn Fern", "Bromeliad"},
    "Fast": {"Money Plant (Pothos)", "Spider Plant", "Philodendron", "Syngonium (Arrowhead Plant)",
             "Boston Fern", "Marigold", "Sunflower", "Petunia", "Moss Rose (Portulaca)",
             "Periwinkle (Vinca)", "Canna Lily", "Bougainvillea", "English Ivy",
             "Wandering Jew (Tradescantia)", "Coleus", "Asparagus Fern"},
}
FLOWER_COLOUR = {
    "Peace Lily": "White", "Anthurium": "Red", "Hibiscus": "Red", "Rose": "Mixed",
    "Jasmine": "White", "Bougainvillea": "Pink", "Periwinkle (Vinca)": "Pink",
    "Plumeria (Frangipani)": "White", "Oleander": "Pink", "Gardenia": "White",
    "Marigold": "Yellow", "Adenium (Desert Rose)": "Pink", "Canna Lily": "Orange",
    "Moss Rose (Portulaca)": "Mixed", "Bird of Paradise": "Orange", "Chrysanthemum": "Mixed",
    "Petunia": "Purple", "Sunflower": "Yellow", "Lavender": "Purple", "Hydrangea": "Blue",
    "Kalanchoe": "Mixed", "Christmas Cactus": "Pink", "Bromeliad": "Red",
    "Orchid (Phalaenopsis)": "White", "Hoya (Wax Plant)": "White", "Oxalis (Purple Shamrock)": "Pink",
}
SEASON = {
    "Marigold": "Winter", "Chrysanthemum": "Winter", "Petunia": "Winter", "Sunflower": "Summer",
    "Hydrangea": "Monsoon", "Lavender": "Summer", "Moss Rose (Portulaca)": "Summer",
    "Christmas Cactus": "Winter", "Norfolk Island Pine": "Winter",
}
# The pot the plant is grown and sold in, which is what the container filter
# actually narrows by.
CONTAINER = {
    "Hanging Basket": {"String of Pearls", "English Ivy", "Wandering Jew (Tradescantia)",
                       "Asparagus Fern", "Boston Fern", "Spider Plant", "Staghorn Fern",
                       "Hoya (Wax Plant)", "Petunia"},
    "Terracotta Pot": {"Aloe Vera", "Jade Plant", "Echeveria Succulent", "Haworthia Zebra Plant",
                       "Adenium (Desert Rose)", "Ponytail Palm", "Kalanchoe", "Christmas Cactus",
                       "Moss Rose (Portulaca)", "Air Plant (Tillandsia)"},
    "Grow Bag": {"Marigold", "Sunflower", "Canna Lily", "Chrysanthemum", "Periwinkle (Vinca)",
                 "Rose", "Hibiscus"},
}
SOIL = {
    "Cactus & Succulent Mix": {"Aloe Vera", "Jade Plant", "Echeveria Succulent",
                               "Haworthia Zebra Plant", "Adenium (Desert Rose)", "Ponytail Palm",
                               "String of Pearls", "Kalanchoe", "Christmas Cactus",
                               "Moss Rose (Portulaca)"},
    "Well-drained Loamy": {"Rose", "Hibiscus", "Marigold", "Sunflower", "Lavender", "Gardenia",
                           "Hydrangea", "Chrysanthemum", "Petunia", "Bougainvillea"},
}


def lookup(table: dict, name: str, default: str) -> str:
    """The key whose set holds `name`, or the default."""
    for key, names in table.items():
        if name in names:
            return key
    return default

# Titles that lead the catalogue, and the newest additions to it.
BESTSELLERS = {"Money Plant (Pothos)", "Snake Plant", "ZZ Plant", "Peace Lily", "Monstera Deliciosa",
               "Aloe Vera", "Spider Plant", "Hibiscus", "Adenium (Desert Rose)", "Marigold"}
NEW_ARRIVALS = {"Calathea", "Fiddle Leaf Fig", "Bird of Paradise", "Lavender", "Hydrangea", "Gardenia"}
FEATURED = {"Monstera Deliciosa", "Peace Lily", "Adenium (Desert Rose)", "Bird of Paradise"}


def variants(base: int, container: str, stock: int = 25) -> list[dict]:
    """Small / Medium / Large pot variants around a base small price.

    Small always ships in the nursery pot it was grown in; the larger two come
    in the container this plant is actually sold in, which is what the Growing
    Container Type filter narrows by.
    """
    return [
        {"name": "Small", "pot_type": "Nursery Pot", "pot_size": "4 inch", "height": "6-8 inches",
         "price": base, "mrp": round(base * 1.4), "stock": stock, "images": []},
        {"name": "Medium", "pot_type": container, "pot_size": "6 inch", "height": "10-14 inches",
         "price": round(base * 1.9), "mrp": round(base * 2.5), "stock": stock, "images": []},
        {"name": "Large", "pot_type": container, "pot_size": "8 inch", "height": "16-22 inches",
         "price": round(base * 3), "mrp": round(base * 3.8), "stock": max(6, stock // 2), "images": []},
    ]


CARE = {
    "Indoor": ["Water when the top inch of soil feels dry",
               "Keep in bright, indirect light away from harsh afternoon sun",
               "Wipe the leaves once a month so they can breathe"],
    "Outdoor": ["Water deeply in the morning, and again in the evening through summer",
                "Give it at least four to six hours of direct sun",
                "Feed once a month through the growing season"],
}


def build(row: tuple, kind: str) -> dict:
    name, base, difficulty, sunlight, pet_safe, purifying, flowering, blurb, extra = row
    container = lookup(CONTAINER, name, "Ceramic Pot")
    return ProductCreate(
        title=name,
        short_description=blurb,
        description=blurb,
        tags=[kind.lower(), difficulty.lower() + " care", *extra],
        # Indoor / outdoor is a tag, not a category: the home page's category
        # strip renders its bundled shortcuts only while no top-level category
        # exists, and two plant categories would replace all nine of them.
        category_id=None,
        mrp=round(base * 1.4),
        price=base,
        cgst=2.5, sgst=2.5, igst=5.0,
        shipping_weight=800,
        images=[PHOTOS[name]],
        sizes=variants(base, container),
        plant_spec={
            "plant_type": kind,
            "sunlight": sunlight,
            "watering": "Every 2 weeks" if difficulty == "Easy" and kind == "Indoor" else "Weekly",
            "difficulty_level": difficulty,
            "air_purifying": purifying,
            "pet_safe": pet_safe,
            "flowering": flowering,
            "growth_rate": lookup(GROWTH_RATE, name, "Medium"),
            "season": SEASON.get(name, "All Season"),
            "soil_type": lookup(SOIL, name, "All-purpose Potting Mix"),
            "fragrant": "fragrant" in extra,
            "medicinal": "medicinal" in extra,
            **({"flower_color": FLOWER_COLOUR[name]} if name in FLOWER_COLOUR else {}),
            "common_names": [name.split(" (")[0]],
        },
        care_tips=CARE[kind],
        includes=["Plant", "Pot", "Potting Soil"],
        warranty="30-day plant replacement guarantee",
        stock=30,
        rating=4.7 if name in BESTSELLERS else 4.5,
        review_count=180 if name in BESTSELLERS else 54,
        sold_count=640 if name in BESTSELLERS else 120,
        is_active=True,
        is_bestseller=name in BESTSELLERS,
        is_new_arrival=name in NEW_ARRIVALS,
        is_featured=name in FEATURED,
    ).model_dump()


# name, description, how many the shopper picks, bundle price, the pool to pick from.
# The price sits roughly a fifth under what the cheapest qty plants in the pool
# cost separately — a bundle that costs more than its parts is not a bundle.
BUNDLES = [
    ("Beginner's Green Starter Set",
     "Three plants that forgive a missed watering — the easiest possible start.",
     3, 499, ["Money Plant (Pothos)", "Snake Plant", "ZZ Plant", "Jade Plant", "Aloe Vera", "Spider Plant"]),
    ("Air-Purifying Home Trio",
     "Pick any three of the plants that work hardest on the air you breathe indoors.",
     3, 749, ["Peace Lily", "Areca Palm", "Snake Plant", "Rubber Plant", "Boston Fern", "Aglaonema (Chinese Evergreen)"]),
    ("Desk & Shelf Set",
     "Small plants sized for a work desk, a bookshelf or a bedside table.",
     4, 679, ["Lucky Bamboo", "Fittonia (Nerve Plant)", "Syngonium (Arrowhead Plant)", "Spider Plant", "Jade Plant"]),
    ("Balcony Bloom Box",
     "Four sun-loving bloomers that keep a balcony in colour all season.",
     4, 409, ["Hibiscus", "Marigold", "Petunia", "Periwinkle (Vinca)", "Moss Rose (Portulaca)", "Canna Lily"]),
    ("Fragrant Garden Bundle",
     "Any three of the plants people notice before they see them.",
     3, 799, ["Jasmine", "Plumeria (Frangipani)", "Gardenia", "Lavender", "Rose"]),
    ("Statement Corner Duo",
     "Two large plants that carry a whole corner of a room on their own.",
     2, 849, ["Monstera Deliciosa", "Fiddle Leaf Fig", "Bird of Paradise", "Rubber Plant"]),
]


async def main() -> None:
    await connect_to_mongo()
    db = get_db()
    now = datetime.now(timezone.utc)

    inserted = skipped = 0
    for rows, kind in ((INDOOR, "Indoor"), (INDOOR_EXTRA, "Indoor"), (OUTDOOR, "Outdoor")):
        for row in rows:
            doc = build(row, kind)
            existing = await db.products.find_one({"title": doc["title"]})
            if existing:
                # A plant seeded by an earlier run predates the facet fields, and
                # without them it is invisible to the filters that read them. Only
                # the fields this script owns are refreshed — copy, pricing and
                # stock the admin has since edited are left alone.
                spec = {**(existing.get("plant_spec") or {}), **doc["plant_spec"]}
                pots = {v["name"]: v["pot_type"] for v in doc["sizes"]}
                sizes = [
                    {**v, "pot_type": pots.get(v.get("name"), v.get("pot_type"))}
                    for v in (existing.get("sizes") or [])
                ]
                await db.products.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"plant_spec": spec, "sizes": sizes, "tags": doc["tags"]}},
                )
                skipped += 1
                continue
            doc["created_at"] = now
            await db.products.insert_one(doc)
            inserted += 1
    print(f"Plants: {inserted} inserted, {skipped} refreshed "
          f"(catalogue now {await db.products.count_documents({})}).")

    # ── Bundles ──
    made = 0
    for name, description, qty, price, pool in BUNDLES:
        if await db.combos.find_one({"name": name}):
            continue
        ids = []
        for title in pool:
            product = await db.products.find_one({"title": title}, {"_id": 1})
            if product:
                ids.append(str(product["_id"]))
        # A pool the shopper cannot fill would render a bundle nobody can buy.
        if len(ids) < qty:
            print(f"  skipped '{name}' — only {len(ids)} of its {qty} plants are in the catalogue")
            continue
        await db.combos.insert_one({
            "name": name, "description": description, "active": True,
            "qty": qty, "price": float(price), "product_ids": ids,
            "weight_target": None, "start_date": None, "end_date": None,
        })
        made += 1
    print(f"Bundles: {made} created (total now {await db.combos.count_documents({})}).")


if __name__ == "__main__":
    asyncio.run(main())
