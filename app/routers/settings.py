import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.settings import Settings, SettingsUpdate
from app.services import pricing

router = APIRouter(prefix="/settings", tags=["settings"])

# Nominatim's usage policy requires a descriptive User-Agent identifying the app.
# Browsers can't set one (and ad-blockers often kill direct requests), so we proxy
# geocoding server-side instead of calling Nominatim from the admin panel.
_NOMINATIM_HEADERS = {"User-Agent": "RoyaallWoolAdmin/1.0 (care@royaallwool.in)"}


@router.get("/geocode", dependencies=[Depends(require_admin)])
async def geocode(q: str = Query(..., min_length=1), limit: int = 5):
    """Proxy address search to OpenStreetMap Nominatim (admin map picker)."""
    try:
        res = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "json", "q": q, "limit": limit, "addressdetails": 0},
            headers=_NOMINATIM_HEADERS,
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Geocoding failed: {e}")

    return [
        {"display_name": p.get("display_name"), "lat": p.get("lat"), "lon": p.get("lon")}
        for p in data
    ]


# Nominatim returns the town under whichever of these keys fits the place, in
# rough order of how a customer would write their own address.
_CITY_KEYS = ("city", "town", "municipality", "village", "suburb", "county", "state_district")
# The house/street part, most specific first — joined into the address line.
_STREET_KEYS = ("house_number", "building", "road", "neighbourhood", "suburb")


@router.get("/reverse-geocode")
async def reverse_geocode(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    """Turn the browser's coordinates into a fillable Indian address.

    Public, because the storefront's checkout uses it for "Use my current
    location". Only the coordinates the customer just consented to share are
    forwarded; nothing is stored.
    """
    try:
        res = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "json", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1},
            headers=_NOMINATIM_HEADERS,
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Location lookup failed: {e}")

    if not isinstance(data, dict) or data.get("error"):
        raise HTTPException(status_code=404, detail="No address found for that location")

    parts = data.get("address") or {}
    city = next((parts[k] for k in _CITY_KEYS if parts.get(k)), "")
    # A suburb doubling as the city shouldn't also repeat inside the street line.
    street = [parts[k] for k in _STREET_KEYS if parts.get(k) and parts[k] != city]

    return {
        "address": ", ".join(dict.fromkeys(street)),
        "city": city,
        "state": parts.get("state", ""),
        "pincode": (parts.get("postcode") or "").replace(" ", ""),
        "country": parts.get("country", ""),
        "display_name": data.get("display_name", ""),
        "lat": lat,
        "lon": lon,
    }


@router.get("", response_model=Settings)
async def read_settings():
    """Public: mobile app reads currency, tax, shop, delivery rules."""
    return await pricing.get_settings(get_db())


@router.put("", response_model=Settings, dependencies=[Depends(require_admin)])
async def update_settings(body: SettingsUpdate):
    db = get_db()
    current = await pricing.get_settings(db)
    data = current.model_dump()
    patch = body.model_dump(exclude_none=True)
    data.update(patch)
    merged = Settings(**data)
    return await pricing.save_settings(db, merged)
