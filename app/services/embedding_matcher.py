"""Lightweight text similarity matcher for the Telegram showcase."""
import logging
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine_similarity

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def compute_embeddings(texts: list[str]) -> Optional[np.ndarray]:
    """Create lightweight TF-IDF vectors without downloading a transformer model."""
    if not texts:
        return None
    try:
        vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2))
        return vectorizer.fit_transform(texts).toarray()
    except ValueError:
        return None


def cosine_similarity(a, b) -> float:
    """Compute cosine similarity between two vectors."""
    try:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def semantic_skill_match(
    resume_skills: list[str],
    jd_skills: list[str],
    threshold: Optional[float] = None,
) -> tuple[float, list[tuple[str, str, float]]]:
    """Match skills using lightweight TF-IDF similarity."""
    if not resume_skills or not jd_skills:
        return 0.0, []

    threshold = threshold or settings.semantic_similarity_threshold
    embeddings = compute_embeddings(resume_skills + jd_skills)
    if embeddings is None:
        return 0.0, []

    resume_count = len(resume_skills)
    resume_embs = embeddings[:resume_count]
    jd_embs = embeddings[resume_count:]

    matched_pairs = []
    total_boost = 0.0

    for j_idx, jd_skill in enumerate(jd_skills):
        best_sim = 0.0
        best_resume_skill = ""
        for r_idx, resume_skill in enumerate(resume_skills):
            sim = cosine_similarity(resume_embs[r_idx], jd_embs[j_idx])
            if sim > best_sim:
                best_sim = sim
                best_resume_skill = resume_skill

        if best_sim >= threshold:
            matched_pairs.append((best_resume_skill, jd_skill, round(best_sim, 3)))
            total_boost += best_sim

    boost = (total_boost / len(jd_skills)) * 100
    return round(boost, 1), matched_pairs


def semantic_text_similarity(text_a: str, text_b: str) -> float:
    """Compute lightweight TF-IDF cosine similarity between two texts."""
    if not text_a or not text_b:
        return 0.0

    embeddings = compute_embeddings([text_a[:2000], text_b[:2000]])
    if embeddings is None:
        return 0.0

    return round(cosine_similarity(embeddings[0], embeddings[1]), 3)


def compute_jd_match_score(
    resume_text: str,
    jd_text: str,
    resume_skills: list[str],
    jd_required: list[str],
    jd_keywords: list[str],
) -> float:
    """Compute JD match from text similarity, keywords, and skill overlap."""
    text_score = semantic_text_similarity(resume_text, jd_text) * 100

    resume_lower = resume_text.lower()
    matched_keywords = sum(1 for kw in jd_keywords if kw.lower() in resume_lower)
    kw_score = (matched_keywords / len(jd_keywords) * 100) if jd_keywords else 50.0

    skill_boost, _ = semantic_skill_match(resume_skills, jd_required)

    final = text_score * 0.4 + kw_score * 0.3 + skill_boost * 0.3
    return round(min(100.0, final), 1)
