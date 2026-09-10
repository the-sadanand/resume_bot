"""
Skill Matcher Service
Exact and normalized skill matching
"""
import re
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


# Normalization map for common technology aliases
SKILL_ALIASES: dict[str, str] = {
    # Languages
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "c sharp": "c#",
    "cplusplus": "c++",
    "cpp": "c++",

    # Frameworks / Libraries
    "fastapi": "fastapi",
    "flask": "flask",
    "django rest framework": "django",
    "drf": "django",
    "react.js": "react",
    "reactjs": "react",
    "react native": "react native",
    "vue.js": "vue",
    "vuejs": "vue",
    "angular.js": "angular",
    "angularjs": "angular",
    "node.js": "nodejs",
    "node js": "nodejs",
    "next.js": "nextjs",
    "next js": "nextjs",
    "express.js": "express",
    "expressjs": "express",
    "spring boot": "springboot",

    # Cloud
    "amazon web services": "aws",
    "google cloud platform": "gcp",
    "microsoft azure": "azure",
    "gke": "kubernetes",
    "eks": "kubernetes",
    "aks": "kubernetes",
    "k8s": "kubernetes",

    # Databases
    "postgres": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "mongo db": "mongodb",
    "elastic": "elasticsearch",
    "es": "elasticsearch",
    "dynamodb": "dynamodb",
    "dynamo db": "dynamodb",
    "mysql server": "mysql",
    "ms sql": "mssql",
    "microsoft sql server": "mssql",

    # ML
    "sklearn": "scikit-learn",
    "sk-learn": "scikit-learn",
    "torch": "pytorch",
    "tf": "tensorflow",
    "hf": "hugging face",
    "huggingface": "hugging face",

    # DevOps
    "ci/cd": "ci/cd",
    "cicd": "ci/cd",
    "github action": "github actions",
    "github-actions": "github actions",
    "gitlab-ci": "gitlab ci",

    # Other
    "agile methodology": "agile",
    "scrum methodology": "scrum",
    "oop": "object-oriented programming",
    "oops": "object-oriented programming",
    "object oriented": "object-oriented programming",
    "restful": "rest",
    "rest api": "rest",
    "restful api": "rest",
    "grpc": "grpc",
    "graphql api": "graphql",
}


def normalize_skill(skill: str) -> str:
    """Normalize a skill name for comparison."""
    cleaned = skill.lower().strip()
    # Remove special characters except common ones
    cleaned = re.sub(r"[^\w\s.#+\-/]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Apply aliases
    return SKILL_ALIASES.get(cleaned, cleaned)


class MatchResult(NamedTuple):
    matched: list[str]
    missing: list[str]
    additional: list[str]
    match_percentage: float


def match_skills_exact(
    resume_skills: list[str],
    jd_required: list[str],
    jd_preferred: list[str] = None,
) -> MatchResult:
    """
    Exact + normalized skill matching.
    Returns matched, missing, additional skills and match percentage.
    """
    jd_preferred = jd_preferred or []

    # Normalize all
    resume_normalized = {normalize_skill(s): s for s in resume_skills}
    jd_required_normalized = {normalize_skill(s): s for s in jd_required}
    jd_preferred_normalized = {normalize_skill(s): s for s in jd_preferred}

    all_jd_normalized = {**jd_required_normalized, **jd_preferred_normalized}

    matched_keys = set(resume_normalized.keys()) & set(all_jd_normalized.keys())
    missing_keys = set(jd_required_normalized.keys()) - matched_keys
    additional_keys = set(resume_normalized.keys()) - set(all_jd_normalized.keys())

    matched = [all_jd_normalized[k] for k in matched_keys]
    missing = [jd_required_normalized[k] for k in missing_keys]
    additional = [resume_normalized[k] for k in additional_keys]

    total = len(jd_required_normalized)
    match_pct = (len(matched_keys & set(jd_required_normalized.keys())) / total * 100) if total > 0 else 100.0

    return MatchResult(
        matched=sorted(matched),
        missing=sorted(missing),
        additional=sorted(additional),
        match_percentage=round(match_pct, 1),
    )


def skill_coverage_score(
    resume_skills: list[str],
    jd_required: list[str],
    jd_preferred: list[str] = None,
    semantic_boost: float = 0.0,
) -> float:
    """
    Calculate a 0-100 skills score.
    - Required skills have higher weight
    - Preferred skills provide a bonus
    - Semantic boost (from embedding matcher) adds additional credit
    """
    jd_preferred = jd_preferred or []
    if not jd_required and not jd_preferred:
        return 75.0  # No skills specified, moderate score

    result = match_skills_exact(resume_skills, jd_required, jd_preferred)

    # Base score from required skills (80% of score)
    req_total = len(jd_required)
    req_matched = len(set(normalize_skill(s) for s in result.matched)
                      & set(normalize_skill(s) for s in jd_required))
    req_score = (req_matched / req_total * 100) if req_total > 0 else 100.0

    # Bonus from preferred skills (20% of score)
    pref_total = len(jd_preferred)
    if pref_total > 0:
        pref_matched = len(set(normalize_skill(s) for s in result.matched)
                           & set(normalize_skill(s) for s in jd_preferred))
        pref_score = pref_matched / pref_total * 100
    else:
        pref_score = 0.0

    base_score = req_score * 0.80 + pref_score * 0.20

    # Add semantic boost (capped at 15 points)
    final_score = min(100.0, base_score + min(semantic_boost, 15.0))

    return round(final_score, 1)
