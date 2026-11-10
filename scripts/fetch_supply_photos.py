"""Resolve three photographs for every row in `_supplies_catalogue`.

Writes `scripts/_supply_photos.py` so the seeder is reproducible and a re-run
does not depend on a search returning the same thing twice. Sources and the
filtering are documented in `_stock_photos`.

Run:  .venv/bin/python -m scripts.fetch_supply_photos
"""

from scripts._commons import lead_images
from scripts._stock_photos import photos
from scripts._supplies_catalogue import ARTICLES, SUPPLIES


def main() -> None:
    # The article's lead photograph leads the gallery: an editor picked it to
    # show the object, which beats anything a keyword search ranks first.
    leads = lead_images(sorted({ARTICLES[name] for rows in SUPPLIES.values() for name, *_ in rows}))

    found: dict[str, list[str]] = {}
    for key, rows in SUPPLIES.items():
        for name, _price, term, must, _blurb in rows:
            urls = []
            lead = leads.get(ARTICLES[name])
            if lead:
                urls.append(lead)
            for url in photos(term, must, 3):
                if url not in urls:
                    urls.append(url)
                if len(urls) == 3:
                    break
            found[name] = urls
            print(f"  {len(urls)} {name}", flush=True)

    with open("scripts/_supply_photos.py", "w") as fh:
        fh.write('"""Photographs for `seed_supplies`, written by `fetch_supply_photos`.\n\n'
                 "Keyed by product name, best match first. Every URL was fetched and\n"
                 'confirmed to answer with an image.\n"""\n\nPHOTOS: dict[str, list[str]] = {\n')
        for name, urls in found.items():
            fh.write(f"    {name!r}: {urls!r},\n")
        fh.write("}\n")

    thin = [name for name, urls in found.items() if len(urls) < 2]
    print(f"\n{sum(len(v) for v in found.values())} photos for {len(found)} products")
    if thin:
        print("fewer than two photos: " + ", ".join(thin))


if __name__ == "__main__":
    main()
