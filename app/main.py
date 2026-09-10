"""FastAPI application for the Telegram-only resume screening showcase."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.storage.database import init_db
from app.api.routes.health import router as health_router
from app.integrations.telegram import router as telegram_router

settings = get_settings()
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    init_db()
    for directory in [settings.temp_dir, settings.generated_dir, "data"]:
        os.makedirs(directory, exist_ok=True)
    logger.info("Telegram-only screening service is ready")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="AI Resume Screening & Ranking Bot",
    description="Telegram-only AI-assisted resume screening showcase.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(telegram_router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "health": "/health",
        "telegram_webhook": "/integrations/telegram/webhook",
    }
