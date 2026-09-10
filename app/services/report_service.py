"""
Report Service
Formats screening results into text reports
"""
import logging
from datetime import datetime

from app.models.screening import ScreeningResult, BatchScreeningResult
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def format_single_report(result: ScreeningResult, job_title: str = "") -> str:
    """Format a single resume screening result as a text report."""
    category = settings.get_score_category(result.overall_score)

    lines = [
        "=" * 48,
        "RESUME SCREENING RESULT",
        "=" * 48,
        "",
        f"Candidate:        {result.candidate_name}",
        f"Job:              {job_title}" if job_title else "",
        f"Analysis ID:      {result.analysis_id}",
        f"Date:             {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "─" * 48,
        f"Overall Score:    {result.overall_score:.0f}/100",
        f"Recommendation:   {category}",
        "─" * 48,
        "",
        "SECTION SCORES",
        "─" * 32,
        f"  Skills          {result.section_scores.skills:.0f}/100",
        f"  Experience      {result.section_scores.experience:.0f}/100",
        f"  Projects        {result.section_scores.projects:.0f}/100",
        f"  Education       {result.section_scores.education:.0f}/100",
        f"  JD Match        {result.section_scores.jd_match:.0f}/100",
        f"  Completeness    {result.section_scores.completeness:.0f}/100",
        "",
    ]

    # Matched Skills
    lines.append("MATCHED SKILLS")
    lines.append("─" * 32)
    if result.skill_match.matched:
        for skill in result.skill_match.matched:
            lines.append(f"  ✓ {skill}")
    else:
        lines.append("  (none matched)")
    lines.append("")

    # Missing Skills
    lines.append("MISSING SKILLS")
    lines.append("─" * 32)
    if result.skill_match.missing:
        for skill in result.skill_match.missing:
            lines.append(f"  • {skill}")
    else:
        lines.append("  (none missing)")
    lines.append("")

    # Strengths
    lines.append("STRENGTHS")
    lines.append("─" * 32)
    for strength in result.strengths:
        lines.append(f"  ✦ {strength}")
    lines.append("")

    # Gaps
    lines.append("GAPS")
    lines.append("─" * 32)
    for gap in result.gaps:
        lines.append(f"  ⚠ {gap}")
    lines.append("")

    # LLM Insights (if available)
    if result.llm_insights:
        lines.append("AI INSIGHTS")
        lines.append("─" * 32)
        lines.append(result.llm_insights)
        lines.append("")

    lines.append("=" * 48)
    lines.append("⚠  This is an AI-assisted screening tool.")
    lines.append("   Not an autonomous hiring decision system.")
    lines.append("=" * 48)

    return "\n".join(l for l in lines if l is not None)


def format_batch_report(batch: BatchScreeningResult, job_title: str = "") -> str:
    """Format a batch screening result as a text report."""
    from app.services.ranking_service import format_ranking_text
    return format_ranking_text(batch, job_title or batch.job_title)


def generate_telegram_summary(result: ScreeningResult) -> str:
    """Short summary suitable for Telegram message."""
    category = settings.get_score_category(result.overall_score)
    matched = ", ".join(result.skill_match.matched[:5]) or "None"
    missing = ", ".join(result.skill_match.missing[:3]) or "None"

    return (
        f"📋 *Resume Screening Result*\n\n"
        f"👤 Candidate: {result.candidate_name}\n"
        f"🎯 Overall: *{result.overall_score:.0f}/100* — {category}\n\n"
        f"📊 *Section Scores*\n"
        f"  Skills: {result.section_scores.skills:.0f}\n"
        f"  Experience: {result.section_scores.experience:.0f}\n"
        f"  Projects: {result.section_scores.projects:.0f}\n"
        f"  Education: {result.section_scores.education:.0f}\n\n"
        f"✅ Matched: {matched}\n"
        f"❌ Missing: {missing}"
    )


def generate_discord_embed(result: ScreeningResult) -> dict:
    """Discord embed-compatible dict for screening result."""
    category = settings.get_score_category(result.overall_score)
    color = {
        "Strong Match": 0x00C851,
        "Good Match": 0x33B5E5,
        "Moderate Match": 0xFFBB33,
        "Weak Match": 0xFF4444,
    }.get(category, 0x888888)

    return {
        "title": f"Resume Screening: {result.candidate_name}",
        "description": f"**Overall Score: {result.overall_score:.0f}/100** — {category}",
        "color": color,
        "fields": [
            {"name": "Skills", "value": str(int(result.section_scores.skills)), "inline": True},
            {"name": "Experience", "value": str(int(result.section_scores.experience)), "inline": True},
            {"name": "Projects", "value": str(int(result.section_scores.projects)), "inline": True},
            {"name": "Education", "value": str(int(result.section_scores.education)), "inline": True},
            {"name": "JD Match", "value": str(int(result.section_scores.jd_match)), "inline": True},
            {"name": "Completeness", "value": str(int(result.section_scores.completeness)), "inline": True},
            {"name": "✅ Matched Skills", "value": "\n".join(result.skill_match.matched[:5]) or "None", "inline": False},
            {"name": "❌ Missing Skills", "value": "\n".join(result.skill_match.missing[:3]) or "None", "inline": False},
        ],
        "footer": {"text": "AI-assisted tool • Not an autonomous hiring decision system"},
    }
