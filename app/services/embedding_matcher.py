"""
Embedding-based Semantic Matcher
Uses sentence-transformers for semantic similarity scoring
"""
import logging
from typing import Optional

try:
    import numpy as np
    _numpy_available = True
except ImportError:
    _numpy_available = False
    np = None

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()

# Lazy-load the model to avoid startup overhead
_model = None


def _get_model():
    """Lazy-load sentence transformer model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {settings.embedding_model}")
            _model = SentenceTransformer(settings.embedding_model)
            logger.info("Embedding model loaded successfully.")
        except ImportError:
            logger.warning("sentence-transformers not installed. Semantic matching disabled.")
            _model = "disabled"
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}. Semantic matching disabled.")
            _model = "disabled"
    return _model if _model != "disabled" else None


def compute_embeddings(texts: list[str]) -> Optional[object]:
    """Compute sentence embeddings for a list of texts."""
    if not _numpy_available:
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    except Exception as e:
        logger.warning(f"Embedding computation failed: {e}")
        return None


def cosine_similarity(a, b) -> float:
    """Compute cosine similarity between two unit vectors."""
    if not _numpy_available or np is None:
        return 0.0
    # Already normalized if using normalize_embeddings=True
    return float(np.dot(a, b))


def semantic_skill_match(
    resume_skills: list[str],
    jd_skills: list[str],
    threshold: Optional[float] = None,
) -> tuple[float, list[tuple[str, str, float]]]:
    """
    Semantic matching between resume skills and JD skills.
    Returns:
        - boost_score: 0-100 score boost based on semantic similarity
        - matched_pairs: list of (resume_skill, jd_skill, similarity) pairs
    """
    if not resume_skills or not jd_skills:
        return 0.0, []

    threshold = threshold or settings.semantic_similarity_threshold

    all_texts = resume_skills + jd_skills
    embeddings = compute_embeddings(all_texts)

    if embeddings is None:
        return 0.0, []

    resume_embs = embeddings[:len(resume_skills)]
    jd_embs = embeddings[len(resume_skills):]

    # For each JD skill, find best matching resume skill
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

    # Normalize to a 0-100 boost score
    if jd_skills:
        boost = (total_boost / len(jd_skills)) * 100
    else:
        boost = 0.0

    return round(boost, 1), matched_pairs


def semantic_text_similarity(text_a: str, text_b: str) -> float:
    """
    Compute semantic similarity between two text passages.
    Useful for comparing resume summary with job responsibilities.
    """
    if not text_a or not text_b:
        return 0.0

    embeddings = compute_embeddings([text_a, text_b])
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
    """
    Compute overall JD match score combining:
    - Text semantic similarity (40%)
    - Keyword presence (30%)
    - Skill semantic overlap (30%)
    """
    # Text similarity
    text_sim = semantic_text_similarity(
        resume_text[:2000],  # Use first 2000 chars for efficiency
        jd_text[:2000],
    )
    text_score = text_sim * 100

    # Keyword match
    resume_lower = resume_text.lower()
    matched_keywords = sum(1 for kw in jd_keywords if kw.lower() in resume_lower)
    kw_score = (matched_keywords / len(jd_keywords) * 100) if jd_keywords else 50.0

    # Skill semantic overlap
    skill_boost, _ = semantic_skill_match(resume_skills, jd_required)

    final = text_score * 0.4 + kw_score * 0.3 + skill_boost * 0.3
    return round(min(100.0, final), 1)
