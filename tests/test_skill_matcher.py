"""
Tests for Skill Matcher
"""
import pytest
from app.services.skill_matcher import (
    normalize_skill, match_skills_exact, skill_coverage_score
)


def test_normalize_skill_lowercase():
    assert normalize_skill("Python") == "python"
    assert normalize_skill("PYTHON") == "python"


def test_normalize_skill_aliases():
    assert normalize_skill("k8s") == "kubernetes"
    assert normalize_skill("postgres") == "postgresql"
    assert normalize_skill("node.js") == "nodejs"
    assert normalize_skill("reactjs") == "react"
    assert normalize_skill("sklearn") == "scikit-learn"


def test_match_skills_exact_perfect():
    resume = ["Python", "FastAPI", "Docker", "PostgreSQL"]
    jd_required = ["python", "fastapi", "docker", "postgresql"]
    result = match_skills_exact(resume, jd_required)
    assert result.match_percentage == 100.0
    assert len(result.missing) == 0


def test_match_skills_exact_partial():
    resume = ["Python", "FastAPI"]
    jd_required = ["python", "fastapi", "docker", "postgresql"]
    result = match_skills_exact(resume, jd_required)
    assert result.match_percentage == 50.0
    assert len(result.missing) == 2


def test_match_skills_with_aliases():
    resume = ["k8s", "postgres", "node.js"]
    jd_required = ["kubernetes", "postgresql", "nodejs"]
    result = match_skills_exact(resume, jd_required)
    assert result.match_percentage == 100.0


def test_match_skills_empty_resume():
    result = match_skills_exact([], ["python", "docker"])
    assert result.match_percentage == 0.0
    assert len(result.missing) == 2


def test_match_skills_empty_jd():
    result = match_skills_exact(["python", "docker"], [])
    # No requirements = 100% satisfied
    assert result.match_percentage == 100.0


def test_skill_coverage_score_high():
    resume = ["python", "fastapi", "docker", "postgresql", "redis", "aws", "kubernetes"]
    jd_required = ["python", "fastapi", "docker", "postgresql"]
    score = skill_coverage_score(resume, jd_required)
    assert score >= 80.0


def test_skill_coverage_score_low():
    resume = ["javascript", "react", "nodejs"]
    jd_required = ["python", "fastapi", "docker", "postgresql", "redis"]
    score = skill_coverage_score(resume, jd_required)
    assert score < 30.0


def test_skill_coverage_score_with_preferred():
    resume = ["python", "fastapi", "elasticsearch"]
    jd_required = ["python", "fastapi"]
    jd_preferred = ["elasticsearch", "graphql"]
    score = skill_coverage_score(resume, jd_required, jd_preferred)
    assert score >= 80.0
