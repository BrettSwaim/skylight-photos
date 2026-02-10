"""Main FastAPI application for Skylight Photos."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import get_config_value
from backend.media import MediaStore
from backend.routers import upload, media

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Skylight Photos",
    description="Photo/video upload service for Skylight MAX digital frame",
    version="1.0.0",
)

# Configure CORS (APK needs this)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup paths
project_root = Path(__file__).parent.parent
uploads_dir = project_root / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)

# Initialize media store
media_store = MediaStore(uploads_dir)

# Include routers
app.include_router(upload.router, prefix="/api")
app.include_router(media.router, prefix="/api")


@app.post("/api/verify-pin")
async def verify_pin(body: dict):
    """Check if a PIN is valid."""
    pin = body.get("pin", "")
    correct = get_config_value("pin", "1234")
    if pin == correct:
        return {"valid": True}
    return {"valid": False}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "skylight-photos",
        "version": "1.0.0",
        "media_count": media_store.count(),
    }


# Serve uploaded files directly (for development / direct access)
if uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

# Mount frontend (must be last)
frontend_path = project_root / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
