"""Resolve a photograph for every packet in `_seed_catalogue` and write
`_seed_photos.py`.

The picture comes from the lead image of the species' Wikipedia article, taken
at 1200px through the pageimages API — a real photograph of the crop, freely
licensed, and a stable URL in a way a search-engine result is not. Anything the
article cannot supply falls back to a Commons image search for the species.
Every URL is fetched and confirmed to answer with an image before it is kept.

Run:  .venv/bin/python scripts/fetch_seed_photos.py
"""

import json
import urllib.parse
import urllib.request

from scripts._seed_catalogue import SEEDS

UA = {"User-Agent": "MyGarden-catalogue/1.0 (nursery seed catalogue; contact: ulmind.in@gmail.com)"}
WIDTH = 1200

# A handful of articles lead with a 19th-century botanical plate rather than a
# photograph. Those are replaced by a Commons photograph of the crop, named
# here as a file title and served through Special:FilePath.
OVERRIDES: dict[str, str] = {
    "Alfalfa": "Sprouted Alfalfa.jpg",
    "Chia": "Salvia hispanica seeds.jpg",
    "Chrysanthemum": "Chrysanthemum of my garden.jpg",
    "Trichosanthes cucumerina": "Trichosanthes cucumerina (snake gourd).jpg",
    "Verbena": "Verbena rigida flower.jpg",
    "Wax gourd": "Benincasa hispida-1-selvapuram-coimbatore-India.jpg",
    "Brassica juncea": "Starr-150403-1408-Brassica juncea-leaves-Southeast Eastern Island-Midway Atoll (24534864353).jpg",
    "Coriander": "Coriandrum sativum 4zz.jpg",
    "Cumin": "Dried cumin seeds.jpg",
    "Dill": "Anethum graveolens20090812 475.jpg",
    "Fenugreek": "Methi leaves.jpg",
    "Momordica charantia": "Momordica charantia 22052014.jpg",
    "Papaya": "Carica papaya 14 7 2012.jpg",
    "Passiflora edulis": "Passionfruit and cross section.jpg",
}


def file_path(name: str) -> str:
    return ("https://commons.wikimedia.org/wiki/Special:FilePath/"
            + urllib.parse.quote(name.replace(" ", "_")) + f"?width={WIDTH}")


def clean(url: str) -> str:
    """Drop the analytics query the API appends to a thumbnail URL."""
    return url.split("?utm_")[0]


def api(host: str, params: dict) -> dict:
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def lead_images(titles: list[str]) -> dict[str, str]:
    """Article title (as asked for) -> lead image URL."""
    out: dict[str, str] = {}
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        data = api("en.wikipedia.org", {
            "action": "query", "prop": "pageimages", "piprop": "thumbnail",
            "pithumbsize": WIDTH, "titles": "|".join(chunk), "redirects": 1,
        })
        query = data.get("query", {})
        # follow normalisations and redirects back to the title we asked for
        alias = {}
        for key in ("normalized", "redirects"):
            for row in query.get(key, []):
                alias[row["to"]] = alias.get(row["from"], row["from"])
        for page in query.get("pages", {}).values():
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb:
                out[alias.get(page["title"], page["title"])] = clean(thumb)
    return out


def commons_search(term: str) -> str | None:
    data = api("commons.wikimedia.org", {
        "action": "query", "generator": "search", "gsrsearch": f'filetype:bitmap {term}',
        "gsrnamespace": 6, "gsrlimit": 1, "prop": "imageinfo",
        "iiprop": "url", "iiurlwidth": WIDTH,
    })
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        return clean(url) if url else None
    return None


def is_image(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("image/")
    except Exception:
        return False


def main() -> None:
    wanted = {row[1] for row in SEEDS}
    found = lead_images(sorted(wanted))
    photos: dict[str, str] = {}
    for article in sorted(wanted):
        url = file_path(OVERRIDES[article]) if article in OVERRIDES else found.get(article)
        if not url or not is_image(url):
            url = commons_search(article)
            if url and not is_image(url):
                url = None
        if url:
            photos[article] = url
        else:
            print(f"  no photo: {article}")

    with open("scripts/_seed_photos.py", "w") as fh:
        fh.write('"""Photographs for `seed_seeds`, written by `fetch_seed_photos`.\n\n'
                 "Keyed by the Wikipedia article the picture leads — the species itself,\n"
                 "so the catalogue shows the crop rather than a stock seed envelope.\n"
                 'Every URL was fetched and confirmed to answer with an image.\n"""\n\n')
        fh.write("PHOTOS: dict[str, str] = {\n")
        for article, url in photos.items():
            fh.write(f"    {article!r}: {url!r},\n")
        fh.write("}\n")
    print(f"{len(photos)}/{len(wanted)} articles photographed -> scripts/_seed_photos.py")


if __name__ == "__main__":
    main()
