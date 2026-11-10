"""Seed the Plant Journal with a starter set of posts.

They land in the same `blog_posts` collection the admin panel edits, so every
post can be rewritten, re-tagged, unpublished or deleted from Admin → Blog.

Run:  python -m scripts.seed_blog
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.db.mongodb import connect_to_mongo, get_db
from app.routers.blog import slugify

U = "https://images.unsplash.com/"
AUTHOR = "MyGarden Nursery"


def p(text):
    return {"type": "p", "text": text, "url": ""}


def h(text):
    return {"type": "h2", "text": text, "url": ""}


def q(text):
    return {"type": "quote", "text": text, "url": ""}


POSTS = [
    {
        "title": "A beginner's guide to keeping your first indoor plant alive",
        "excerpt": "Light, water, drainage — get these three right and almost every houseplant forgives the rest.",
        "image": f"{U}photo-1485955900006-10f4d324d411?w=1400",
        "tag": "Gardening Basics",
        "featured": True,
        "body": [
            p("Most first plants don't die of neglect — they drown in kindness. Before you buy anything, look at the spot you want to fill and be honest about how much light it actually gets."),
            h("Start with the light, not the plant"),
            p("A window that gets three to four hours of gentle morning sun will keep a pothos, snake plant or ZZ plant happy for years. A dim corner two metres from the nearest window is a low-light spot, whatever the shop tag says."),
            h("Water on the soil's schedule, not yours"),
            p("Push a finger two inches into the soil. Dry? Water until it runs out of the drainage hole. Still damp? Come back in three days. That single habit prevents the most common cause of plant death."),
            q("If you only remember one thing: a pot without a drainage hole is a bucket, and roots cannot swim."),
            h("Give it four weeks before you judge"),
            p("A new plant is adjusting to your home's light, humidity and air flow. A couple of older leaves yellowing in the first fortnight is settling in, not failure."),
        ],
    },
    {
        "title": "How to choose the right potting mix for every plant",
        "excerpt": "Garden soil belongs in the garden. Here's what actually goes into a pot, and why.",
        "image": f"{U}photo-1416879595882-3373a0480b5b?w=1400",
        "tag": "Gardening Basics",
        "body": [
            p("Potting mix isn't soil — it's a blend designed to hold moisture while letting air reach the roots. Packed garden soil does the opposite once it sits in a container."),
            h("The everyday blend"),
            p("Two parts cocopeat, one part compost and one part perlite or coarse sand suits most indoor foliage. It stays damp without turning to mud."),
            h("Succulents and cacti"),
            p("Flip the ratio: one part cocopeat to two parts sand or perlite. These plants store their own water and rot quickly in a mix that stays wet."),
            h("Refresh it every year"),
            p("Mix compresses and runs out of nutrition. Even if the plant isn't outgrowing its pot, replacing the top third of the mix each spring makes a visible difference."),
        ],
    },
    {
        "title": "Watering 101: how often is too often?",
        "excerpt": "Overwatering kills more houseplants than any pest. A simple check settles it every time.",
        "image": f"{U}photo-1518335935020-cfd6580c1ab4?w=1400",
        "tag": "Plant Care",
        "body": [
            p("There is no weekly watering day that works for every plant, in every pot, in every season. What works is checking before you pour."),
            h("The two-inch test"),
            p("Finger into the soil up to the second knuckle. Dry at that depth means water. Cool and damp means wait. Terracotta dries faster than ceramic; a plant in bright light drinks more than the same plant in a corner."),
            h("Water properly when you do"),
            p("A splash at the top wets only the surface roots. Water slowly until it drains from the bottom, then tip out whatever collects in the saucer."),
            q("Underwatered plants droop and recover in an hour. Overwatered plants droop and never do — that's how you tell them apart."),
            h("Winter changes everything"),
            p("Growth slows, evaporation slows, and the same plant may need water half as often from November to February."),
        ],
    },
    {
        "title": "Yellow leaves? Here's what your plant is telling you",
        "excerpt": "Read the pattern — which leaves, which part, how fast — and the cause is usually obvious.",
        "image": f"{U}photo-1466781783364-36c955e42a7f?w=1400",
        "tag": "Garden Maintenance",
        "body": [
            p("Yellowing is a symptom, not a disease. The useful question is which leaves are turning, and how quickly."),
            h("Lower leaves, slow and soft"),
            p("Usually overwatering. Let the mix dry further between waterings and check that the drainage hole isn't blocked."),
            h("All-over pale, new growth thin"),
            p("Not enough light, or the mix is spent. Move it closer to a window and feed once the plant is back in active growth."),
            h("Crisp yellow edges"),
            p("Dry air or salt build-up from tap water and fertiliser. Flush the pot thoroughly every couple of months and mist humidity-loving varieties."),
            h("Sudden, patchy, with webbing"),
            p("Check the undersides. Spider mites thrive in dry indoor air — wipe the leaves, rinse the plant and isolate it until it is clear."),
        ],
    },
    {
        "title": "Start a kitchen garden in six pots",
        "excerpt": "Coriander, chillies, mint and three more that grow happily on an Indian balcony.",
        "image": f"{U}photo-1530836369250-ef72a3f5cda8?w=1400",
        "tag": "Kitchen Gardening",
        "body": [
            p("You don't need a plot. Six pots on a sunny balcony can cover most of what a kitchen reaches for every week."),
            h("The six to begin with"),
            p("Coriander, mint, green chilli, curry leaf, spinach and cherry tomato. All of them handle heat, all of them crop within weeks rather than seasons."),
            h("Sun is the only non-negotiable"),
            p("Edibles want four to six hours of direct sun. A balcony that gets morning sun is ideal; harsh afternoon light needs a shade net through summer."),
            h("Harvest often"),
            p("Picking is pruning. Cutting coriander and mint regularly keeps them bushy instead of letting them run to seed."),
        ],
    },
    {
        "title": "From seed to sprout: seed starting made simple",
        "excerpt": "Why some seeds never come up, and the small changes that fix it.",
        "image": f"{U}photo-1466692476868-aef1dfb1e735?w=1400",
        "tag": "Kitchen Gardening",
        "body": [
            p("Germination is mostly about consistency. Seeds need warmth, moisture and the right sowing depth — miss one and the tray stays bare."),
            h("Sow at the right depth"),
            p("A seed goes about twice as deep as it is wide. Fine seeds like lettuce and coriander are barely covered; beans and pumpkin go an inch down."),
            h("Keep it evenly damp"),
            p("A tray that dries out once mid-germination is a tray that fails. Cover it loosely until the first shoots appear, then uncover and give them light immediately."),
            q("Leggy, pale seedlings stretching sideways are asking for one thing — more light, sooner."),
            h("Transplant at the right moment"),
            p("Move them on once they have two true leaves, in the cool of the evening, and water them in straight away."),
        ],
    },
    {
        "title": "Style your home with plants: five corners that always work",
        "excerpt": "Scale, grouping and pot colour do more for a room than any single rare plant.",
        "image": f"{U}photo-1493663284031-b7e3aefcae8e?w=1400",
        "tag": "Indoor Gardening",
        "body": [
            p("A well-placed plant reads as intentional. The trick is matching the plant's habit to the space it has to fill."),
            h("The empty corner"),
            p("One tall plant — an areca palm or a rubber plant — in a pot that reaches roughly a third of its height. Corners want vertical, not wide."),
            h("Above the shelf"),
            p("Trailing pothos or peperomia. Let the vines fall naturally and trim only when they reach the floor."),
            h("The work desk"),
            p("Small, low-maintenance and green: a jade, a fittonia or a snake plant. Something you can water once a fortnight and forget."),
            h("Group in odd numbers"),
            p("Three pots of different heights in one tone read as a collection; six matching pots in a row read as a nursery shelf."),
        ],
    },
    {
        "title": "Repotting: when to do it and how to avoid the shock",
        "excerpt": "Roots circling the pot, water running straight through — your plant is asking for room.",
        "image": f"{U}photo-1523348837708-15d4a09cfac2?w=1400",
        "tag": "Garden Maintenance",
        "body": [
            p("Most houseplants want a bigger pot every 12 to 18 months. Repotting at the wrong time, or into a pot that is far too large, sets them back for months."),
            h("The signs"),
            p("Roots appearing at the drainage hole, water running straight through, or growth that has simply stopped through a growing season."),
            h("Go one size up, not three"),
            p("Two inches wider is right. A huge pot holds far more damp mix than the roots can use, and that is how root rot starts."),
            h("Aftercare"),
            p("Water thoroughly once, then keep it out of harsh direct sun for a week and skip fertiliser for a month while the roots settle."),
        ],
    },
    {
        "title": "Feeding your plants: fertiliser without the fear",
        "excerpt": "What the three numbers on the pack mean, and how little you actually need.",
        "image": f"{U}photo-1457530378978-8bac673b8062?w=1400",
        "tag": "Plant Care",
        "body": [
            p("Potting mix runs out of nutrition in a few months. Feeding replaces it — but more is emphatically not better."),
            h("Reading the label"),
            p("The three numbers are nitrogen, phosphorus and potassium. Nitrogen drives leaves, phosphorus drives roots and flowers, potassium keeps the plant resilient."),
            h("Half strength, twice as often"),
            p("Dilute to half what the pack says and feed every two weeks through the growing season. Fertiliser burn shows up as scorched leaf tips."),
            h("Stop in winter"),
            p("A plant that isn't growing can't use what you give it, and the salts simply build up in the mix."),
        ],
    },
]


async def main():
    await connect_to_mongo()
    db = get_db()
    now = datetime.now(timezone.utc)

    created = 0
    for index, post in enumerate(POSTS):
        if await db.blog_posts.find_one({"title": post["title"]}):
            continue
        doc = {
            **post,
            "slug": slugify(post["title"]),
            "author": AUTHOR,
            "published_at": (now - timedelta(days=index * 6 + 2)).isoformat(),
            "link": "/plants",
            "link_label": "Shop the plants in this guide",
            "featured": bool(post.get("featured")),
            "published": True,
            "order": index,
            "created_at": now,
        }
        await db.blog_posts.insert_one(doc)
        created += 1
    print(f"{created} journal posts inserted (total {await db.blog_posts.count_documents({})}).")


if __name__ == "__main__":
    asyncio.run(main())
