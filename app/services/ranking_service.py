"""
Ranking Service
Ranks and compares multiple candidates by score
"""
import logging
from typing import Optional

from app.models.screening import RankedCandidate, BatchScreeningResult, SectionScores, SkillMatchDetail
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def rank_candidates(
    candidates: list[dict],  # list of {name, analysis_id, overall_score, section_scores, skill_match}
) -> list[RankedCandidate]:
    """
    Rank candidates by overall score (descending).
    Returns a sorted list of RankedCandidate objects.
    """
    sorted_candidates = sorted(candidates, key=lambda c: c["overall_score"], reverse=True)

    ranked = []
    for rank, candidate in enumerate(sorted_candidates, start=1):
        scored = candidate["overall_score"]
        recommendation = settings.get_score_category(scored)

        ranked.append(RankedCandidate(
            rank=rank,
            candidate_name=candidate["name"],
            overall_score=candidate["overall_score"],
            recommendation=recommendation,
            section_scores=candidate["section_scores"],
            skill_match=candidate["skill_match"],
            analysis_id=candidate["analysis_id"],
        ))

    return ranked


def build_comparison_table(ranked: list[RankedCandidate]) -> list[dict]:
    """Build a comparison table with all section scores."""
    table = []
    for rc in ranked:
        table.append({
            "rank": rc.rank,
            "candidate": rc.candidate_name,
            "overall": rc.overall_score,
            "skills": rc.section_scores.skills,
            "experience": rc.section_scores.experience,
            "projects": rc.section_scores.projects,
            "education": rc.section_scores.education,
            "jd_match": rc.section_scores.jd_match,
            "completeness": rc.section_scores.completeness,
            "recommendation": rc.recommendation,
        })
    return table


def format_ranking_text(
    batch_result: "BatchScreeningResult",
    job_title: str,
) -> str:
    """
    Format batch results as a human-readable text report.
    """
    lines = [
        "=" * 48,
        "RESUME RANKING",
        "=" * 48,
        f"Job: {job_title}",
        f"Total Candidates: {batch_result.total_candidates}",
        "",
        "─" * 48,
        "RANKING",
        "─" * 48,
    ]

    for rc in batch_result.ranked_candidates:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rc.rank, f"{rc.rank}.")
        lines.append(f"{medal} {rc.candidate_name} — {rc.overall_score}/100 ({rc.recommendation})")

    lines.extend([
        "",
        "─" * 48,
        "DETAILED COMPARISON",
        "─" * 48,
    ])

    # Header
    header = f"{'Candidate':<20} {'Skills':>7} {'Exp':>5} {'Proj':>5} {'Edu':>5} {'JD':>5} {'Overall':>8}"
    lines.append(header)
    lines.append("-" * 55)

    for row in batch_result.comparison_table:
        line = (
            f"{row['candidate'][:18]:<20} "
            f"{row['skills']:>7.0f} "
            f"{row['experience']:>5.0f} "
            f"{row['projects']:>5.0f} "
            f"{row['education']:>5.0f} "
            f"{row['jd_match']:>5.0f} "
            f"{row['overall']:>8.1f}"
        )
        lines.append(line)

    return "\n".join(lines)
