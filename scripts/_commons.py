"""Wikimedia Commons photo lookup, shared by the catalogue seeders.

Commons is the only image source here: freely licensed, hot-linkable, and it
costs nothing to serve — the Cloudinary free tier is left for the pictures the
admin uploads. `gallery` returns several photographs of one subject so a
product page has a filmstrip rather than a single still.

Botanical plates, maps, diagrams and logos are filtered out by filename: a
19th-century lithograph is not a product photograph.
"""

import json
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "MyGarden-catalogue/1.0 (nursery catalogue; contact: ulmind.in@gmail.com)"}
WIDTH = 1200

_NOT_A_PHOTO = re.compile(
    r"köhler|kohler|blanco|medizinal|thom[eé]|illustration|drawing|engraving|lithograph"
    r"|plantarum|botanical|herbarium|specimen|map|diagram|chart|logo|icon|coat.of.arms"
    r"|\bsvg\b|\.svg|stamp|banknote|poster|screenshot|1[6-9]\d\d",
    re.I,
)


def _api(host: str, params: dict) -> dict:
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.load(r)


def _ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("image/")
    except Exception:
        return False


def _clean(url: str) -> str:
    return url.split("?utm_")[0]


def search(term: str, limit: int = 12) -> list[tuple[str, str]]:
    """(file title, 1200px URL) for a Commons search, widest matches first."""
    data = _api("commons.wikimedia.org", {
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {term}",
        "gsrnamespace": 6, "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url", "iiurlwidth": WIDTH,
    })
    pages = sorted((data.get("query", {}).get("pages", {}) or {}).values(), key=lambda p: p["index"])
    out = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if url:
            out.append((page["title"][5:], _clean(url)))
    return out


def gallery(term: str, want: int = 3, pool: int = 12) -> list[str]:
    """Several verified photographs of one subject, best match first."""
    picked: list[str] = []
    for name, url in search(term, pool):
        if _NOT_A_PHOTO.search(name):
            continue
        if _ok(url):
            picked.append(url)
        if len(picked) == want:
            break
    return picked


_ART = re.compile(
    r"google art project|barnes foundation|museum|renoir|c[eé]zanne|seurat|van gogh|monet"
    r"|still life|oil on canvas|watercolou?r|woodcut|postcard|mural|fresco|sculpture",
    re.I,
)


def product_gallery(term: str, must: list[str], want: int = 3, pool: int = 40) -> list[str]:
    """Photographs of a thing you can buy.

    Commons ranks a painting of a watering can as highly as a photograph of
    one, so a candidate has to carry every must-word in its filename and none
    of the gallery-wall giveaways. Matches that satisfy the filter first, then
    anything else the search returned, so a thin subject still gets a picture.
    """
    strict: list[str] = []
    loose: list[str] = []
    for name, url in search(term, pool):
        if _NOT_A_PHOTO.search(name) or _ART.search(name):
            continue
        low = name.lower().replace("_", " ")
        (strict if all(word in low for word in must) else loose).append(url)
        if len(strict) >= want:
            break
    picked: list[str] = []
    for url in strict + loose:
        if _ok(url):
            picked.append(url)
        if len(picked) == want:
            break
    return picked


def lead_images(articles: list[str]) -> dict[str, str]:
    """Wikipedia article -> its lead photograph, asked for in batches of 20."""
    out: dict[str, str] = {}
    for i in range(0, len(articles), 20):
        data = _api("en.wikipedia.org", {
            "action": "query", "prop": "pageimages", "piprop": "thumbnail",
            "pithumbsize": WIDTH, "titles": "|".join(articles[i:i + 20]), "redirects": 1,
        })
        query = data.get("query", {})
        alias: dict[str, str] = {}
        for key in ("normalized", "redirects"):
            for row in query.get(key, []):
                alias[row["to"]] = alias.get(row["from"], row["from"])
        for page in query.get("pages", {}).values():
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb:
                out[alias.get(page["title"], page["title"])] = _clean(thumb)
    return out
