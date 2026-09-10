"""
Tests for Scoring Engine
"""
import pytest
from app.models.resume import ParsedResume, ExperienceEntry, ProjectEntry, EducationEntry
from app.models.job import ParsedJobDescription
from app.services.scoring_engine import (
    score_skills, score_experience, score_projects, score_education,
    score_completeness, compute_overall_score, screen_resume,
    generate_strengths, generate_gaps,
)
from app.models.screening import SectionScores


def make_strong_resume():
    return ParsedResume(
        name="Alex Chen",
        email="alex@example.com",
        phone="+1-555-0101",
        summary="Senior Python Backend Engineer with 7 years experience.",
        skills=["python", "fastapi", "docker", "postgresql", "redis", "kubernetes", "aws", "celery", "elasticsearch"],
        experience=[
            ExperienceEntry(
                title="Senior Backend Engineer",
                company="CloudScale",
                duration="2020-2024",
                years=5.0,
                technologies=["python", "fastapi", "docker", "postgresql", "redis"],
            ),
            ExperienceEntry(
                title="Backend Engineer",
                company="DataStream",
                duration="2018-2020",
                years=2.0,
                technologies=["django", "celery", "postgresql"],
            ),
        ],
        projects=[
            ProjectEntry(name="AutoScaler", technologies=["python", "kubernetes", "docker", "aws"]),
            ProjectEntry(name="RealtimeDB", technologies=["python", "fastapi", "postgresql", "redis"]),
        ],
        education=[EducationEntry(degree="Bachelor of Science in Computer Science", institution="State University", year="2017")],
        certifications=["AWS Certified Solutions Architect", "CKA"],
        achievements=["PyCon Speaker"],
        total_years_experience=7.0,
    )


def make_moderate_resume():
    return ParsedResume(
        name="James Miller",
        email="james@example.com",
        phone="+1-555-0202",
        summary="Full-stack developer with JavaScript background.",
        skills=["javascript", "nodejs", "react", "python", "flask", "mongodb", "docker"],
        experience=[
            ExperienceEntry(
                title="Full Stack Developer",
                company="DigitalEdge",
                duration="2022-2024",
                years=2.0,
                technologies=["javascript", "nodejs", "mongodb"],
            ),
        ],
        projects=[
            ProjectEntry(name="Task App", technologies=["python", "flask", "postgresql"]),
        ],
        education=[EducationEntry(degree="Bachelor of Science in Information Technology", year="2021")],
        total_years_experience=2.0,
    )


def make_jd():
    return ParsedJobDescription(
        job_title="Senior Python Backend Engineer",
        required_skills=["python", "fastapi", "docker", "postgresql", "redis"],
        preferred_skills=["kubernetes", "elasticsearch", "graphql"],
        technologies=["python", "fastapi", "docker", "postgresql", "redis", "kubernetes"],
        keywords=["python", "backend", "api", "docker"],
        min_years_experience=5.0,
        education_requirements=["Bachelor's in Computer Science"],
        experience_requirements=["5+ years Python"],
    )


def test_score_skills_strong_match():
    resume = make_strong_resume()
    jd = make_jd()
    score, skill_detail = score_skills(resume, jd)
    assert score >= 80.0, f"Expected >= 80, got {score}"
    assert len(skill_detail.matched) > 0


def test_score_skills_weak_match():
    resume = make_moderate_resume()
    jd = make_jd()
    score, skill_detail = score_skills(resume, jd)
    assert score < 60.0, f"Expected < 60, got {score}"


def test_score_experience_sufficient():
    resume = make_strong_resume()
    jd = make_jd()
    score = score_experience(resume, jd)
    assert score >= 70.0, f"Expected >= 70, got {score}"


def test_score_experience_insufficient():
    resume = make_moderate_resume()
    jd = make_jd()
    score = score_experience(resume, jd)
    assert score < 70.0, f"Expected < 70 for 2 years vs 5 required, got {score}"


def test_score_projects_with_projects():
    resume = make_strong_resume()
    jd = make_jd()
    score = score_projects(resume, jd)
    assert score >= 50.0, f"Expected >= 50, got {score}"


def test_score_projects_no_projects():
    resume = ParsedResume(name="Test", projects=[], skills=["python"])
    jd = make_jd()
    score = score_projects(resume, jd)
    assert score == 30.0  # No projects penalty


def test_score_education_matching():
    resume = make_strong_resume()
    jd = make_jd()
    score = score_education(resume, jd)
    assert score >= 70.0


def test_score_education_no_education():
    resume = ParsedResume(name="Test", education=[])
    jd = make_jd()
    score = score_education(resume, jd)
    assert score <= 50.0


def test_score_completeness_full_resume():
    resume = make_strong_resume()
    score = score_completeness(resume)
    assert score >= 80.0, f"Expected >= 80, got {score}"


def test_score_completeness_minimal_resume():
    resume = ParsedResume(name="Test")
    score = score_completeness(resume)
    assert score < 50.0


def test_compute_overall_score_weighted():
    section_scores = SectionScores(
        skills=80.0,
        experience=70.0,
        projects=75.0,
        education=85.0,
        jd_match=70.0,
        completeness=90.0,
    )
    overall = compute_overall_score(section_scores)
    # With weights 35/20/15/10/15/5:
    # 80*35 + 70*20 + 75*15 + 85*10 + 70*15 + 90*5 = 2800+1400+1125+850+1050+450 = 7675 / 100 = 76.75
    assert 70 <= overall <= 85, f"Expected 70-85, got {overall}"


def test_screen_resume_returns_all_fields():
    resume = make_strong_resume()
    jd = make_jd()
    section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)

    assert 0 <= overall_score <= 100
    assert isinstance(strengths, list)
    assert isinstance(gaps, list)
    assert section_scores.skills >= 0
    assert len(skill_detail.matched) > 0


def test_screen_resume_strong_candidate():
    resume = make_strong_resume()
    jd = make_jd()
    _, _, overall_score, _, _ = screen_resume(resume, jd)
    assert overall_score >= 70.0, f"Strong candidate expected >= 70, got {overall_score}"


def test_screen_resume_moderate_candidate():
    resume = make_moderate_resume()
    jd = make_jd()
    _, _, overall_score, _, _ = screen_resume(resume, jd)
    assert overall_score < 75.0, f"Moderate candidate expected < 75, got {overall_score}"


def test_generate_strengths():
    resume = make_strong_resume()
    jd = make_jd()
    section_scores, skill_detail, _, _, _ = screen_resume(resume, jd)
    strengths = generate_strengths(resume, jd, section_scores, skill_detail)
    assert len(strengths) > 0


def test_generate_gaps_missing_skills():
    resume = make_moderate_resume()
    jd = make_jd()
    section_scores, skill_detail, _, _, _ = screen_resume(resume, jd)
    gaps = generate_gaps(resume, jd, section_scores, skill_detail)
    assert len(gaps) > 0
