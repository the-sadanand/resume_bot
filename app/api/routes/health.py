"""
Health Check Route
"""
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime

from app.core.config import get_settings

router = APIRouter(tags=["Health"])
settings = get_settings()


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    timestamp: str
    llm_provider: str


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Application health check endpoint."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.utcnow().isoformat() + "Z",
        llm_provider=settings.llm_provider,
    )
