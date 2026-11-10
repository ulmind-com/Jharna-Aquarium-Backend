import cloudinary
import cloudinary.uploader

from app.core.config import settings

_configured = False


def _ensure_config() -> bool:
    global _configured
    if _configured:
        return True
    if not (
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    ):
        return False
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    _configured = True
    return True


def upload_image(file_bytes: bytes, folder: str = "clothing") -> str:
    if not _ensure_config():
        raise RuntimeError("Cloudinary is not configured")
    result = cloudinary.uploader.upload(file_bytes, folder=folder)
    return result["secure_url"]


def upload_video(file_bytes: bytes, folder: str = "clothing/video") -> dict:
    """Upload a clip and derive a poster frame from it.

    Cloudinary needs resource_type="video" explicitly; the poster is the same
    asset requested as a .jpg, so the reel can show a still before playback
    without a second upload.
    """
    if not _ensure_config():
        raise RuntimeError("Cloudinary is not configured")
    result = cloudinary.uploader.upload_large(
        file_bytes,
        folder=folder,
        resource_type="video",
        chunk_size=6_000_000,
    )
    url = result["secure_url"]
    poster = url.rsplit(".", 1)[0] + ".jpg" if "." in url else None
    return {
        "url": url,
        "poster": poster,
        "duration": result.get("duration"),
        "bytes": result.get("bytes"),
    }
