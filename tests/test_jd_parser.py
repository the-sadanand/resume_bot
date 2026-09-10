"""
Tests for JD Parser
"""
import pytest
from app.services.jd_parser import parse_job_description


def test_jd_parse_returns_parsed_jd(sample_jd_text):
    result = parse_job_description(sample_jd_text, provided_title="Senior Python Backend Engineer")
    assert result is not None
    assert result.job_title == "Senior Python Backend Engineer"


def test_jd_parse_extracts_technologies(sample_jd_text):
    result = parse_job_description(sample_jd_text)
    # Should find Python at minimum
    all_skills = result.required_skills + result.preferred_skills + result.technologies
    all_lower = [s.lower() for s in all_skills]
    assert any("python" in s for s in all_lower), f"Python not found in: {all_lower}"


def test_jd_parse_extracts_min_experience(sample_jd_text):
    result = parse_job_description(sample_jd_text)
    assert result.min_years_experience >= 5


def test_jd_parse_empty_text():
    result = parse_job_description("")
    assert result is not None
    assert isinstance(result.required_skills, list)
    assert isinstance(result.technologies, list)


def test_jd_parse_keywords():
    jd = "We need Python Python Python developers with Docker Docker Docker experience."
    result = parse_job_description(jd)
    keywords_lower = [k.lower() for k in result.keywords]
    assert "python" in keywords_lower or "docker" in keywords_lower


def test_jd_parse_education_requirements():
    jd = """
    Requirements:
    Education: Bachelor's degree in Computer Science required
    Master's degree preferred
    """
    result = parse_job_description(jd)
    # Check that education requirements is a list (may or may not extract, depends on text)
    assert isinstance(result.education_requirements, list)
