"""LLM re-ranker for recommendations (Groq, OpenAI-compatible).

Production pattern: our heuristic engine retrieves a candidate set, then the LLM
re-ranks those candidates for the shopper's context. The LLM can ONLY reorder
real candidate ids (grounded — no hallucinated products), calls are cached with a
short TTL, run off the event loop, time-bounded, and fall back to the heuristic
order on any error or when no key is configured.
"""
import asyncio
import json
import time

import requests

from app.core.config import settings

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Small in-process TTL cache (single-instance friendly).
_cache: dict[str, tuple[float, list[str]]] = {}
_TTL = 600  # seconds


def enabled() -> bool:
    return bool(settings.RECS_USE_LLM and settings.GROQ_API_KEY)


def _cache_get(key: str) -> list[str] | None:
    v = _cache.get(key)
    if v and (time.time() - v[0]) < _TTL:
        return v[1]
    return None


def _cache_set(key: str, ids: list[str]) -> None:
    _cache[key] = (time.time(), ids)
    if len(_cache) > 500:  # keep the cache bounded
        oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:100]
        for k, _ in oldest:
            _cache.pop(k, None)


def _slim(p: dict) -> dict:
    """Compact candidate representation for the prompt (small token budget)."""
    spec = p.get("plant_spec") or {}
    return {
        "id": p["id"],
        "title": p.get("title"),
        "category": p.get("category_name") or "",
        "price": p.get("final_price") or p.get("price") or 0,
        "discount_pct": p.get("off_pct") or 0,
        "rating": p.get("rating") or 0,
        "in_stock": bool(p.get("in_stock", True)),
        "plant_type": spec.get("plant_type") or "",
        "sunlight": spec.get("sunlight") or "",
        "difficulty": spec.get("difficulty_level") or "",
        "pet_safe": spec.get("pet_safe", False),
        "air_purifying": spec.get("air_purifying", False),
    }


def _call_groq(payload: dict) -> str:
    resp = requests.post(
        _GROQ_URL,
        headers={
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.GROQ_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def rerank(
    context: str,
    candidates: list[dict],
    limit: int,
    cache_key: str | None = None,
) -> list[str] | None:
    """Return an ordered list of candidate ids (best first), or None to fall back."""
    if not enabled() or not candidates:
        return None
    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    valid = {c["id"] for c in candidates}
    system = (
        "You are the recommendation engine for a premium online plant nursery e-commerce app. "
        "Given a shopper's context and a list of candidate plants/products, rank them "
        "by how relevant they are to the shopper, most relevant first. Prefer in-stock "
        "items, complementary plants (e.g. pair indoor plants together, suggest pots with plants), "
        "similar care requirements, similar price range, and popular/bestselling picks. "
        "For plant care compatibility, consider sunlight needs, watering frequency, and difficulty level. "
        "Only use ids from the candidates — never invent ids. "
        'Respond ONLY as compact JSON: {"ranking": ["<id>", ...]}.'
    )
    user = (
        f"Shopper context:\n{context}\n\n"
        f"Candidate products (JSON):\n{json.dumps([_slim(c) for c in candidates], ensure_ascii=False)}\n\n"
        f"Return the {min(limit, len(candidates))} most relevant product ids, best first."
    )
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }

    try:
        content = await asyncio.to_thread(_call_groq, payload)
        data = json.loads(content)
        raw = data.get("ranking") or data.get("ids") or []
        ordered = [i for i in raw if isinstance(i, str) and i in valid]
        if not ordered:
            return None
        # Fill any gap with the engine's own order so the rail is always full.
        seen = set(ordered)
        for c in candidates:
            if c["id"] not in seen:
                ordered.append(c["id"])
                seen.add(c["id"])
        ordered = ordered[:limit]
        if cache_key:
            _cache_set(cache_key, ordered)
        return ordered
    except Exception:
        return None  # any failure -> heuristic fallback
