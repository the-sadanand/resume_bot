"""FastAPI application for the multi-channel resume screening showcase."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.storage.database import init_db
from app.api.routes.health import router as health_router
from app.integrations.telegram import router as telegram_router
from app.integrations.google_chat_rich import router as google_chat_rich_router
from app.integrations.multichannel import router as multichannel_router

settings = get_settings()
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    init_db()
    for directory in [settings.temp_dir, settings.generated_dir, "data"]:
        os.makedirs(directory, exist_ok=True)
    logger.info("Multi-channel screening service is ready")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="AI Resume Screening & Ranking Bot",
    description="Resume screening bot accessible through Telegram, Discord, Google Chat and WhatsApp.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(telegram_router)
# Register the rich Google Chat route first so it handles /screen with cards.
app.include_router(google_chat_rich_router)
app.include_router(multichannel_router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "health": "/health",
        "integrations": {
            "telegram": "/integrations/telegram/webhook",
            "discord": "/integrations/discord/interactions",
            "google_chat": "/integrations/google-chat/events",
            "whatsapp": "/integrations/whatsapp/webhook",
        },
    }
