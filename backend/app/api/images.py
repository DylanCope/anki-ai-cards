"""Image upload endpoint.

An uploaded image is stored as an opaque `ImageAsset` row, referenced only by
id from then on — the agent never sees the actual image bytes (mirroring how
it never "hears" a generated audio clip, see app.models.ImageAsset). Search-
and generate-sourced `ImageAsset` rows are written by their respective tools
(tasks 36-37), not this endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlmodel import Session

from app.auth import require_auth
from app.models import ImageAsset, get_engine

router = APIRouter(prefix="/api/images", tags=["images"])


@router.post("")
async def upload_image(
    file: UploadFile, email: str = Depends(require_auth)
) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    data = await file.read()
    engine = get_engine()
    with Session(engine) as session:
        image = ImageAsset(content_type=file.content_type, data=data, source="upload")
        session.add(image)
        session.commit()
        session.refresh(image)
        image_id = image.id

    return {"image_id": image_id}
