"""Product photographs for things that are manufactured rather than grown.

Wikimedia has the botany covered, but it has no photograph of a watering can
that is not a Renoir. These come from Openverse, which indexes the CC0 stock
libraries (Rawpixel, StockSnap, Nappy) alongside Flickr and Commons.

The cascade, best first:
  1. CC0 / public-domain stock — no attribution obligation at all;
  2. anything Openverse will license for commercial use;
  3. Wikimedia Commons, through `_commons.product_gallery`.
A candidate has to carry a must-word in its title before it is kept, so a
search for "watering can" cannot answer with a photograph of a water feature.
"""

import json
import time
import urllib.parse
import urllib.request

from scripts._commons import _ok, product_gallery

UA = {"User-Agent": "MyGarden-catalogue/1.0 (nursery catalogue; contact: ulmind.in@gmail.com)"}
STOCK_SOURCES = "rawpixel,stocksnap,nappy"


def _openverse(term: str, want: int, must: list[str], **extra) -> list[str]:
    params = {"q": term, "page_size": 20, "mature": "false", **extra}
    url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            results = json.load(r).get("results", [])
    except Exception:
        return []
    picked: list[str] = []
    seen: set[str] = set()
    for row in results:
        title = (row.get("title") or "").lower()
        image = row.get("url")
        # a sticker or a cut-out PNG is not a product photograph
        if not image or "illustration" in title or "sticker" in title or "png" in title:
            continue
        if must and not any(word in title for word in must):
            continue
        if image in seen:
            continue
        seen.add(image)
        if _ok(image):
            picked.append(image)
        if len(picked) == want:
            break
    return picked


def photos(term: str, must: list[str], want: int = 3) -> list[str]:
    out = _openverse(term, want, must, license="cc0,pdm", source=STOCK_SOURCES)
    if len(out) < want:
        time.sleep(0.3)
        for url in _openverse(term, want, must, license="cc0,pdm"):
            if url not in out:
                out.append(url)
            if len(out) == want:
                break
    if len(out) < want:
        time.sleep(0.3)
        for url in _openverse(term, want, must, license_type="commercial"):
            if url not in out:
                out.append(url)
            if len(out) == want:
                break
    if len(out) < want:
        for url in product_gallery(term, must, want):
            if url not in out:
                out.append(url)
            if len(out) == want:
                break
    return out
