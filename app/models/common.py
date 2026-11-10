from typing import Any
from datetime import datetime, timezone

from bson import ObjectId


def serialize(doc: dict | None) -> dict | None:
    """Convert Mongo document (_id ObjectId) into a JSON-friendly dict with `id`."""
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for k, v in doc.items():
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            s = v.isoformat()
            if s.endswith("+00:00"):
                s = s.replace("+00:00", "Z")
            out[k] = s
        elif isinstance(v, ObjectId):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def to_object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise ValueError(f"Invalid id: {value}")
    return ObjectId(value)
