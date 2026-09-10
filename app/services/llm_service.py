"""
LLM Service
Abstraction layer for LLM-based analysis (explanations, insights only).
LLM does NOT determine numerical scores.
"""
import logging
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    """
    LLM abstraction that supports:
    - none (disabled)
    - ollama (local)
    - openai (OpenAI-compatible API)

    Used ONLY for generating:
    - Natural language explanations
    - Additional insights
    - Strengths/gaps narrative

    Never used to compute numerical scores.
    """

    def __init__(self):
        self.provider = settings.llm_provider.lower()
        self._client = None

    def _get_openai_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                )
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
        return self._client

    def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call Ollama local API."""
        try:
            import requests
            payload = {
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
            }
            response = requests.post(
                f"{settings.ollama_base_url}/api/generate",
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            logger.warning(f"Ollama call failed: {e}")
            return None

    def _call_openai(self, prompt: str) -> Optional[str]:
        """Call OpenAI-compatible API."""
        client = self._get_openai_client()
        if client is None:
            return None
        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "You are an HR assistant. Provide concise, professional insights about resume screening results."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"OpenAI call failed: {e}")
            return None

    def generate_insights(
        self,
        candidate_name: str,
        job_title: str,
        overall_score: float,
        matched_skills: list[str],
        missing_skills: list[str],
        years_experience: float,
    ) -> Optional[str]:
        """
        Generate natural language insights about a candidate.
        This is supplementary — the score is already computed deterministically.
        """
        if self.provider == "none":
            return None

        prompt = (
            f"Provide a brief 2-3 sentence professional analysis for:\n\n"
            f"Candidate: {candidate_name}\n"
            f"Job: {job_title}\n"
            f"Score: {overall_score}/100\n"
            f"Matched skills: {', '.join(matched_skills[:5])}\n"
            f"Missing skills: {', '.join(missing_skills[:3])}\n"
            f"Experience: {years_experience:.1f} years\n\n"
            f"Focus on actionable hiring insights. Be objective and professional."
        )

        if self.provider == "ollama":
            return self._call_ollama(prompt)
        elif self.provider == "openai":
            return self._call_openai(prompt)

        return None

    def is_available(self) -> bool:
        return self.provider in ("ollama", "openai")


# Singleton
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
