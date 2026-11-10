from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.deps import get_current_user, require_admin
from app.services.storage import upload_image, upload_video

router = APIRouter(prefix="/upload", tags=["upload"])

# Cloudinary's free tier caps a single video upload well below this; the limit
# is here so an oversized file fails fast with a clear message.
MAX_VIDEO_BYTES = 100 * 1024 * 1024


@router.post("/image", dependencies=[Depends(require_admin)])
async def upload_product_image(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    data = await file.read()
    try:
        url = upload_image(data, folder="clothing/products")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"url": url}


@router.post("/video", dependencies=[Depends(require_admin)])
async def upload_section_video(file: UploadFile = File(...)):
    """Admin: upload a clip for a video-backed home section.

    Returns the playable URL plus a poster frame derived from the same asset.
    """
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")
    data = await file.read()
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Video is larger than {MAX_VIDEO_BYTES // (1024 * 1024)}MB",
        )
    try:
        return upload_video(data, folder="clothing/sections")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/review-image", dependencies=[Depends(get_current_user)])
async def upload_review_image(file: UploadFile = File(...)):
    """Any signed-in customer can attach photos to a product review."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    data = await file.read()
    try:
        url = upload_image(data, folder="clothing/reviews")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"url": url}


@router.post("/user-image", dependencies=[Depends(get_current_user)])
async def upload_user_image(file: UploadFile = File(...)):
    """Any signed-in user can upload their profile picture."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    data = await file.read()
    try:
        url = upload_image(data, folder="clothing/users")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"url": url}
