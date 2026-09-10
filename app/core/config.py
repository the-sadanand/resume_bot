"""
AI Resume Screening & Ranking Bot
Core Configuration
"""
import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "Resume Screening Bot"
    app_version: str = "1.0.0"
    app_env: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # LLM Provider
    llm_provider: str = "none"  # none | ollama | openai
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # Telegram
    telegram_bot_token: str = ""

    # Discord
    discord_bot_token: str = ""

    # Google Chat
    google_chat_project_id: str = ""
    google_application_credentials: str = ""

    # WhatsApp Cloud API
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""

    # Database
    database_url: str = "sqlite:///./data/resume_screening.db"

    # Redis
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # File Handling
    max_file_size_mb: int = 10
    allowed_extensions: str = "pdf,docx"
    temp_dir: str = "./temp"
    generated_dir: str = "./generated"

    # Scoring Weights (should sum to 100)
    weight_skills: int = 35
    weight_experience: int = 20
    weight_projects: int = 15
    weight_education: int = 10
    weight_jd_match: int = 15
    weight_completeness: int = 5

    # Score Thresholds
    threshold_strong: int = 85
    threshold_good: int = 70
    threshold_moderate: int = 55

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    semantic_similarity_threshold: float = 0.65

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip().lower() for ext in self.allowed_extensions.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    def get_scoring_weights(self) -> dict:
        return {
            "skills": self.weight_skills,
            "experience": self.weight_experience,
            "projects": self.weight_projects,
            "education": self.weight_education,
            "jd_match": self.weight_jd_match,
            "completeness": self.weight_completeness,
        }

    def get_score_category(self, score: float) -> str:
        if score >= self.threshold_strong:
            return "Strong Match"
        elif score >= self.threshold_good:
            return "Good Match"
        elif score >= self.threshold_moderate:
            return "Moderate Match"
        else:
            return "Weak Match"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
