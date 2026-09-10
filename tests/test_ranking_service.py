"""
Tests for Ranking Service
"""
import pytest
from app.services.ranking_service import rank_candidates, build_comparison_table, format_ranking_text
from app.models.screening import SectionScores, SkillMatchDetail, BatchScreeningResult


def make_candidate(name, overall_score, skills=80.0, experience=70.0, projects=75.0, education=80.0):
    return {
        "name": name,
        "analysis_id": f"ana_{name.lower().replace(' ', '_')}",
        "overall_score": overall_score,
        "section_scores": SectionScores(
            skills=skills,
            experience=experience,
            projects=projects,
            education=education,
            jd_match=70.0,
            completeness=90.0,
        ),
        "skill_match": SkillMatchDetail(
            matched=["python", "docker"],
            missing=["kubernetes"],
            match_percentage=66.7,
        ),
    }


def test_rank_candidates_sorted_descending():
    candidates = [
        make_candidate("Candidate C", 73.0),
        make_candidate("Candidate A", 87.0),
        make_candidate("Candidate B", 81.0),
    ]
    ranked = rank_candidates(candidates)
    assert ranked[0].candidate_name == "Candidate A"
    assert ranked[1].candidate_name == "Candidate B"
    assert ranked[2].candidate_name == "Candidate C"


def test_rank_candidates_assigns_ranks():
    candidates = [
        make_candidate("A", 90.0),
        make_candidate("B", 75.0),
        make_candidate("C", 60.0),
    ]
    ranked = rank_candidates(candidates)
    for i, rc in enumerate(ranked, start=1):
        assert rc.rank == i


def test_rank_candidates_recommendation():
    candidates = [
        make_candidate("Strong", 87.0),
        make_candidate("Good", 75.0),
        make_candidate("Moderate", 60.0),
        make_candidate("Weak", 45.0),
    ]
    ranked = rank_candidates(candidates)
    assert ranked[0].recommendation == "Strong Match"
    assert ranked[1].recommendation == "Good Match"
    assert ranked[2].recommendation == "Moderate Match"
    assert ranked[3].recommendation == "Weak Match"


def test_build_comparison_table():
    candidates = [
        make_candidate("A", 90.0),
        make_candidate("B", 75.0),
    ]
    ranked = rank_candidates(candidates)
    table = build_comparison_table(ranked)

    assert len(table) == 2
    assert table[0]["candidate"] == "A"
    assert table[0]["overall"] == 90.0
    assert "skills" in table[0]
    assert "experience" in table[0]


def test_format_ranking_text():
    candidates = [
        make_candidate("Alice Johnson", 87.0),
        make_candidate("Bob Smith", 75.0),
        make_candidate("Carol Davis", 62.0),
    ]
    ranked = rank_candidates(candidates)
    comparison_table = build_comparison_table(ranked)
    batch = BatchScreeningResult(
        batch_id="test_batch",
        job_title="Python Engineer",
        total_candidates=3,
        ranked_candidates=ranked,
        comparison_table=comparison_table,
    )
    text = format_ranking_text(batch, "Python Engineer")

    assert "Alice Johnson" in text
    assert "87" in text
    assert "RANKING" in text
    assert "COMPARISON" in text


def test_rank_single_candidate():
    candidates = [make_candidate("Solo", 80.0)]
    ranked = rank_candidates(candidates)
    assert len(ranked) == 1
    assert ranked[0].rank == 1


def test_rank_empty_candidates():
    ranked = rank_candidates([])
    assert ranked == []
