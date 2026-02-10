"""
Skylight Photos — Self-hosted photo uploader for Skylight frames.
Sends photos as email attachments to bypass the Plus subscription.
"""

import asyncio
import io
import os
import ssl
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

import config

app = FastAPI(title="Skylight Photos")

STATIC_DIR = Path(__file__).parent / "static"


def resize_image(data: bytes, max_dim: int = 1920) -> bytes:
    """Resize image if larger than max_dim, preserving aspect ratio. Returns JPEG bytes."""
    img = Image.open(io.BytesIO(data))

    # Convert HEIC/RGBA/palette to RGB
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    # Auto-rotate based on EXIF
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)

    # Resize if needed
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


async def send_photo_email(
    photo_data: bytes,
    filename: str,
    caption: str | None = None,
    frame_email: str | None = None,
):
    """Send a photo as an email attachment to the Skylight frame."""
    target = frame_email or config.FRAME_EMAIL

    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = target
    msg["Subject"] = caption or "Photo"

    # Skylight uses the email body as caption if present
    msg.set_content(caption or "")

    # Attach the photo
    maintype, subtype = "image", "jpeg"
    if filename.lower().endswith(".png"):
        subtype = "png"
    elif filename.lower().endswith(".gif"):
        subtype = "gif"

    msg.add_attachment(
        photo_data,
        maintype=maintype,
        subtype=subtype,
        filename=filename,
    )

    # Use permissive TLS for internal mail server (self-signed cert on IP)
    tls_context = ssl.create_default_context()
    tls_context.check_hostname = False
    tls_context.verify_mode = ssl.CERT_NONE

    await aiosmtplib.send(
        msg,
        hostname=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=config.SMTP_USER,
        password=config.SMTP_PASS,
        start_tls=config.SMTP_TLS,
        tls_context=tls_context,
    )


@app.post("/api/upload")
async def upload_photos(
    photos: list[UploadFile] = File(...),
    caption: str = Form(default=""),
    frame_email: str = Form(default=""),
):
    """Upload one or more photos to the Skylight frame."""
    results = []
    errors = []

    for photo in photos:
        # Validate extension
        ext = Path(photo.filename or "photo.jpg").suffix.lower()
        if ext not in config.ALLOWED_EXTENSIONS:
            errors.append({"file": photo.filename, "error": f"Unsupported format: {ext}"})
            continue

        # Read and validate size
        data = await photo.read()
        if len(data) > config.MAX_FILE_SIZE:
            errors.append({"file": photo.filename, "error": "File too large (max 25MB)"})
            continue

        if len(data) == 0:
            errors.append({"file": photo.filename, "error": "Empty file"})
            continue

        try:
            # Resize to reasonable dimensions and convert to JPEG
            processed = resize_image(data)
            out_filename = Path(photo.filename or "photo.jpg").stem + ".jpg"

            await send_photo_email(
                processed,
                out_filename,
                caption=caption or None,
                frame_email=frame_email or None,
            )
            results.append({"file": photo.filename, "status": "sent"})
        except Exception as e:
            errors.append({"file": photo.filename, "error": str(e)})

    if not results and errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    return JSONResponse({"sent": len(results), "failed": len(errors), "results": results, "errors": errors})


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve frontend
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
