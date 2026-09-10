"""
FastAPI Application Entry Point
AI Resume Screening & Ranking Bot
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.storage.database import init_db

# Import routers
from app.api.routes.health import router as health_router
from app.api.routes.resumes import router as resumes_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.screening import router as screening_router

# Platform adapters
from app.integrations.telegram import router as telegram_router
from app.integrations.whatsapp import router as whatsapp_router
from app.integrations.google_chat import router as google_chat_router
from app.integrations.discord import router as discord_router, start_discord_bot

settings = get_settings()

# Set up logging before anything else
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Initialize database
    init_db()

    # Create required directories
    for directory in [settings.temp_dir, settings.generated_dir, "data"]:
        os.makedirs(directory, exist_ok=True)

    # Start Discord bot if token is configured
    discord_task = None
    if settings.discord_bot_token:
        logger.info("Starting Discord bot...")
        try:
            discord_task = asyncio.create_task(start_discord_bot())
        except Exception as e:
            logger.warning(f"Discord bot start failed: {e}")

    logger.info(f"Server ready on {settings.host}:{settings.port}")
    logger.info(f"LLM Provider: {settings.llm_provider}")
    logger.info("Swagger UI: http://localhost:8000/docs")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if discord_task and not discord_task.done():
        discord_task.cancel()


# Create FastAPI app
app = FastAPI(
    title="AI Resume Screening & Ranking Bot",
    description=(
        "An AI-powered resume screening system that analyzes resumes against job descriptions.\n\n"
        "**Features:**\n"
        "- PDF and DOCX resume parsing\n"
        "- JD parsing and requirement extraction\n"
        "- Semantic + exact skill matching\n"
        "- Transparent scoring engine (deterministic, explainable)\n"
        "- Candidate ranking and comparison\n"
        "- Platform adapters: Telegram, WhatsApp, Google Chat, Discord\n\n"
        "**Ethical Note:**\n"
        "This is an AI-assisted screening tool. It does NOT make autonomous hiring decisions.\n"
        "Scores are based on job-relevant qualifications only.\n"
        "No bias based on gender, religion, race, or other personal characteristics."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount generated files for static serving (charts)
os.makedirs(settings.generated_dir, exist_ok=True)
app.mount("/generated", StaticFiles(directory=settings.generated_dir), name="generated")

# Include routers
app.include_router(health_router)
app.include_router(resumes_router)
app.include_router(jobs_router)
app.include_router(screening_router)

# Platform adapters
app.include_router(telegram_router)
app.include_router(whatsapp_router)
app.include_router(google_chat_router)
app.include_router(discord_router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "note": "AI-assisted screening tool. Not an autonomous hiring decision system.",
    }
