"""
Tests for Chart Generation
"""
import os
import pytest
from pathlib import Path

from app.utils.chart_utils import (
    generate_overall_score_chart,
    generate_section_comparison_chart,
    generate_radar_chart,
)


@pytest.fixture
def sample_candidates():
    return [
        {"name": "Alice Johnson", "score": 87.0},
        {"name": "Bob Smith", "score": 75.0},
        {"name": "Carol Davis", "score": 62.0},
    ]


@pytest.fixture
def sample_section_candidates():
    return [
        {"name": "Alice Johnson", "skills": 90.0, "experience": 85.0, "projects": 88.0, "education": 80.0, "jd_match": 82.0},
        {"name": "Bob Smith", "skills": 75.0, "experience": 70.0, "projects": 72.0, "education": 78.0, "jd_match": 70.0},
        {"name": "Carol Davis", "skills": 60.0, "experience": 55.0, "projects": 65.0, "education": 70.0, "jd_match": 58.0},
    ]


def test_generate_overall_score_chart(sample_candidates, tmp_path):
    out = str(tmp_path / "test_scores.png")
    result = generate_overall_score_chart(sample_candidates, "Python Engineer", filename=out)
    assert os.path.exists(result)
    assert result.endswith(".png")
    assert os.path.getsize(result) > 1000  # Non-empty PNG


def test_generate_section_comparison_chart(sample_section_candidates, tmp_path):
    out = str(tmp_path / "test_comparison.png")
    result = generate_section_comparison_chart(sample_section_candidates, "Python Engineer", filename=out)
    assert os.path.exists(result)
    assert result.endswith(".png")
    assert os.path.getsize(result) > 1000


def test_generate_radar_chart(tmp_path):
    out = str(tmp_path / "test_radar.png")
    section_scores = {
        "skills": 88.0,
        "experience": 80.0,
        "projects": 85.0,
        "education": 90.0,
        "jd_match": 78.0,
        "completeness": 95.0,
    }
    result = generate_radar_chart("Alice Johnson", section_scores, filename=out)
    assert os.path.exists(result)
    assert result.endswith(".png")


def test_score_chart_single_candidate(tmp_path):
    out = str(tmp_path / "test_single.png")
    candidates = [{"name": "Solo Candidate", "score": 82.0}]
    result = generate_overall_score_chart(candidates, filename=out)
    assert os.path.exists(result)


def test_score_chart_many_candidates(tmp_path):
    out = str(tmp_path / "test_many.png")
    candidates = [{"name": f"Candidate {i}", "score": 90.0 - i * 5} for i in range(8)]
    result = generate_overall_score_chart(candidates, "Big Batch", filename=out)
    assert os.path.exists(result)
