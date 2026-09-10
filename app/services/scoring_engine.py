"""
Scoring Engine
Deterministic, transparent scoring system.
LLM is NEVER used to determine the final numerical score.
"""
import logging
import re
from typing import Optional

from app.models.resume import ParsedResume
from app.models.job import ParsedJobDescription
from app.models.screening import SectionScores, SkillMatchDetail
from app.services.skill_matcher import match_skills_exact, skill_coverage_score
from app.services.embedding_matcher import (
    semantic_skill_match,
    compute_jd_match_score,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Individual Section Scorers ────────────────────────────────────────────────

def score_skills(resume: ParsedResume, jd: ParsedJobDescription) -> tuple[float, SkillMatchDetail]:
    """
    Score skill match using:
    - Exact/normalized matching (primary)
    - Semantic matching (secondary boost)
    """
    # Exact match
    match_result = match_skills_exact(
        resume.skills,
        jd.required_skills,
        jd.preferred_skills,
    )

    # Semantic boost
    semantic_boost, _ = semantic_skill_match(
        resume.skills,
        jd.required_skills + jd.technologies,
    )
    semantic_boost_normalized = min(semantic_boost * 0.15, 15.0)  # max 15 point boost

    base_score = skill_coverage_score(resume.skills, jd.required_skills, jd.preferred_skills)
    final_score = min(100.0, base_score + semantic_boost_normalized)

    skill_detail = SkillMatchDetail(
        matched=match_result.matched,
        missing=match_result.missing,
        additional=match_result.additional,
        match_percentage=match_result.match_percentage,
    )
    return round(final_score, 1), skill_detail


def score_experience(resume: ParsedResume, jd: ParsedJobDescription) -> float:
    """
    Score experience based on:
    - Years of experience vs required years
    - Relevant job titles
    - Technology overlap in experience
    """
    required_years = jd.min_years_experience
    candidate_years = resume.total_years_experience

    # Years sub-score (50%)
    if required_years <= 0:
        years_score = 80.0  # No specific requirement
    elif candidate_years >= required_years * 1.5:
        years_score = 100.0
    elif candidate_years >= required_years:
        years_score = 90.0
    elif candidate_years >= required_years * 0.8:
        years_score = 75.0
    elif candidate_years >= required_years * 0.5:
        years_score = 55.0
    else:
        years_score = max(20.0, (candidate_years / required_years * 100) if required_years > 0 else 50.0)

    # Relevance sub-score (50%) — tech overlap in experience entries
    jd_tech_set = {s.lower() for s in jd.technologies + jd.required_skills}
    experience_tech = set()
    for exp in resume.experience:
        for tech in exp.technologies:
            experience_tech.add(tech.lower())
        # Also scan description
        desc_lower = exp.description.lower()
        for tech in jd_tech_set:
            if tech in desc_lower:
                experience_tech.add(tech)

    if jd_tech_set:
        overlap = len(experience_tech & jd_tech_set) / len(jd_tech_set)
        relevance_score = min(100.0, overlap * 150)  # amplified
    else:
        relevance_score = 70.0 if resume.experience else 30.0

    return round(years_score * 0.5 + relevance_score * 0.5, 1)


def score_projects(resume: ParsedResume, jd: ParsedJobDescription) -> float:
    """
    Score projects based on:
    - Number of relevant projects
    - Technology overlap
    - Description quality
    """
    if not resume.projects:
        return 30.0  # No projects listed

    jd_tech_set = {s.lower() for s in jd.technologies + jd.required_skills}
    relevant_count = 0
    tech_overlap_total = 0.0

    for project in resume.projects:
        project_techs = {t.lower() for t in project.technologies}
        # Also scan description
        for tech in jd_tech_set:
            if tech in project.description.lower():
                project_techs.add(tech)

        if project_techs & jd_tech_set:
            relevant_count += 1
            if jd_tech_set:
                tech_overlap_total += len(project_techs & jd_tech_set) / len(jd_tech_set)

    project_count = len(resume.projects)

    # Quantity score
    quantity_score = min(100.0, project_count * 20)  # 5 projects = full score

    # Relevance score
    relevance_score = (relevant_count / project_count * 100) if project_count > 0 else 0.0

    # Tech coverage
    tech_coverage = (tech_overlap_total / project_count * 150) if project_count > 0 else 0.0
    tech_coverage = min(100.0, tech_coverage)

    return round(quantity_score * 0.2 + relevance_score * 0.5 + tech_coverage * 0.3, 1)


def score_education(resume: ParsedResume, jd: ParsedJobDescription) -> float:
    """
    Score education based on:
    - Degree level match
    - Relevant field of study
    """
    if not resume.education:
        # Check if education is even required
        if not jd.education_requirements:
            return 70.0
        return 30.0

    # Determine highest degree
    degree_weights = {
        "phd": 5, "doctorate": 5,
        "master": 4, "mba": 4, "msc": 4, "m.tech": 4, "m.e": 4, "m.s": 4,
        "bachelor": 3, "bsc": 3, "b.tech": 3, "b.e": 3, "b.s": 3, "b.com": 3, "b.a": 3,
        "associate": 2, "diploma": 2,
    }

    highest_weight = 0
    for edu in resume.education:
        degree_lower = edu.degree.lower()
        for deg, weight in degree_weights.items():
            if deg in degree_lower:
                highest_weight = max(highest_weight, weight)

    # Map required education
    required_weight = 3  # Default: bachelor's
    for req in jd.education_requirements:
        req_lower = req.lower()
        for deg, weight in degree_weights.items():
            if deg in req_lower:
                required_weight = weight
                break

    if highest_weight >= required_weight:
        degree_score = 100.0
    elif highest_weight == required_weight - 1:
        degree_score = 75.0
    elif highest_weight > 0:
        degree_score = 50.0
    else:
        degree_score = 20.0

    # Field relevance (bonus)
    cs_fields = {"computer", "software", "data", "information", "it ", "engineering",
                 "mathematics", "statistics", "artificial intelligence", "machine learning"}
    field_bonus = 0
    for edu in resume.education:
        field = edu.field_of_study.lower() + edu.degree.lower()
        if any(f in field for f in cs_fields):
            field_bonus = 10
            break

    return round(min(100.0, degree_score + field_bonus), 1)


def score_jd_match(resume: ParsedResume, jd: ParsedJobDescription) -> float:
    """
    Score overall JD match using semantic + keyword analysis.
    """
    return compute_jd_match_score(
        resume_text=resume.raw_text,
        jd_text=jd.raw_text,
        resume_skills=resume.skills,
        jd_required=jd.required_skills,
        jd_keywords=jd.keywords,
    )


def score_completeness(resume: ParsedResume) -> float:
    """
    Score resume completeness — checks presence of key sections.
    """
    checks = {
        "name": bool(resume.name and resume.name != "Unknown"),
        "email": bool(resume.email),
        "phone": bool(resume.phone),
        "summary": bool(resume.summary),
        "skills": len(resume.skills) >= 5,
        "experience": len(resume.experience) >= 1,
        "education": len(resume.education) >= 1,
        "projects": len(resume.projects) >= 1,
        "certifications": bool(resume.certifications),
        "achievements": bool(resume.achievements),
    }

    weights = {
        "name": 15,
        "email": 10,
        "phone": 5,
        "summary": 10,
        "skills": 20,
        "experience": 20,
        "education": 10,
        "projects": 5,
        "certifications": 3,
        "achievements": 2,
    }

    total_weight = sum(weights.values())
    earned = sum(weights[k] for k, v in checks.items() if v)
    return round(earned / total_weight * 100, 1)


# ── Final Score Computation ───────────────────────────────────────────────────

def compute_overall_score(section_scores: SectionScores) -> float:
    """
    Compute weighted overall score.
    This is deterministic — no LLM involvement.
    """
    weights = settings.get_scoring_weights()
    total = (
        section_scores.skills * weights["skills"]
        + section_scores.experience * weights["experience"]
        + section_scores.projects * weights["projects"]
        + section_scores.education * weights["education"]
        + section_scores.jd_match * weights["jd_match"]
        + section_scores.completeness * weights["completeness"]
    ) / 100.0

    return round(min(100.0, total), 1)


def generate_strengths(
    resume: ParsedResume,
    jd: ParsedJobDescription,
    section_scores: SectionScores,
    skill_detail: SkillMatchDetail,
) -> list[str]:
    """Identify candidate strengths from scores and match data."""
    strengths = []

    if section_scores.skills >= 80:
        strengths.append(f"Strong skill alignment — matched {len(skill_detail.matched)} required skills")
    if section_scores.experience >= 80:
        years = resume.total_years_experience
        strengths.append(f"Solid professional experience ({years:.1f} years)")
    if section_scores.projects >= 75:
        strengths.append(f"Good project portfolio with {len(resume.projects)} relevant projects")
    if section_scores.education >= 85:
        if resume.education:
            strengths.append(f"Strong educational background: {resume.education[0].degree}")
    if section_scores.completeness >= 90:
        strengths.append("Well-structured and complete resume")
    if skill_detail.additional:
        extras = skill_detail.additional[:3]
        strengths.append(f"Additional skills beyond JD: {', '.join(extras)}")
    if resume.certifications:
        strengths.append(f"Professional certifications: {', '.join(resume.certifications[:2])}")
    if resume.achievements:
        strengths.append("Notable achievements listed")

    return strengths or ["Resume has been received and processed"]


def generate_gaps(
    resume: ParsedResume,
    jd: ParsedJobDescription,
    section_scores: SectionScores,
    skill_detail: SkillMatchDetail,
) -> list[str]:
    """Identify candidate gaps from scores and missing data."""
    gaps = []

    if skill_detail.missing:
        for skill in skill_detail.missing[:5]:
            gaps.append(f"Missing required skill: {skill}")
    if section_scores.experience < 60:
        gaps.append(
            f"Experience gap — {resume.total_years_experience:.1f} years vs "
            f"{jd.min_years_experience:.0f}+ required"
        )
    if section_scores.projects < 50:
        gaps.append("Limited or non-relevant project experience")
    if section_scores.education < 60:
        gaps.append("Education does not fully meet requirements")
    if not resume.summary:
        gaps.append("No professional summary provided")
    if not resume.certifications and section_scores.skills < 70:
        gaps.append("No certifications to supplement skill gaps")

    return gaps or ["No major gaps identified"]


def screen_resume(resume: ParsedResume, jd: ParsedJobDescription) -> tuple[SectionScores, SkillMatchDetail, float, list[str], list[str]]:
    """
    Full screening pipeline for one resume against a JD.
    Returns: (section_scores, skill_detail, overall_score, strengths, gaps)
    """
    skills_score, skill_detail = score_skills(resume, jd)
    experience_score = score_experience(resume, jd)
    projects_score = score_projects(resume, jd)
    education_score = score_education(resume, jd)
    jd_match_score = score_jd_match(resume, jd)
    completeness_score = score_completeness(resume)

    section_scores = SectionScores(
        skills=skills_score,
        experience=experience_score,
        projects=projects_score,
        education=education_score,
        jd_match=jd_match_score,
        completeness=completeness_score,
    )

    overall_score = compute_overall_score(section_scores)
    strengths = generate_strengths(resume, jd, section_scores, skill_detail)
    gaps = generate_gaps(resume, jd, section_scores, skill_detail)

    return section_scores, skill_detail, overall_score, strengths, gaps
