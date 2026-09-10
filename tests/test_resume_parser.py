"""
Tests for Resume Parser (text extraction and structured parsing)
"""
import os
import pytest
import tempfile
from pathlib import Path


def create_docx_file(path: str, content_builder) -> str:
    """Helper to create a DOCX file for testing."""
    try:
        from docx import Document
        doc = Document()
        content_builder(doc)
        doc.save(path)
        return path
    except ImportError:
        pytest.skip("python-docx not installed")


def test_extract_text_from_docx(tmp_path):
    """Test DOCX text extraction."""
    try:
        from docx import Document
        from app.services.resume_parser import extract_text_from_docx

        docx_path = str(tmp_path / "test.docx")
        doc = Document()
        doc.add_paragraph("Alex Chen")
        doc.add_paragraph("alex@example.com")
        doc.add_paragraph("Python, FastAPI, Docker")
        doc.save(docx_path)

        text = extract_text_from_docx(docx_path)
        assert "Alex Chen" in text
        assert "Python" in text
    except ImportError:
        pytest.skip("python-docx not installed")


def test_extract_text_from_pdf(tmp_path):
    """Test PDF text extraction using PyMuPDF."""
    try:
        import fitz
        from app.services.resume_parser import extract_text_from_pdf

        # Create a simple PDF
        pdf_path = str(tmp_path / "test.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "John Smith\njohn@example.com\nPython, Docker, FastAPI")
        doc.save(pdf_path)
        doc.close()

        text = extract_text_from_pdf(pdf_path)
        assert "John Smith" in text
        assert "Python" in text
    except ImportError:
        pytest.skip("PyMuPDF not installed")


def test_parse_resume_from_docx(tmp_path):
    """Full resume parsing from DOCX."""
    try:
        from docx import Document
        from app.services.resume_parser import parse_resume

        docx_path = str(tmp_path / "candidate.docx")
        doc = Document()
        doc.add_heading("Sarah Johnson", 0)
        doc.add_paragraph("sarah.johnson@example.com | +1-555-0199")
        doc.add_heading("Summary", 2)
        doc.add_paragraph("Senior Python developer with 6 years experience.")
        doc.add_heading("Skills", 2)
        doc.add_paragraph("Python, FastAPI, Django, Docker, PostgreSQL, Redis, AWS, Git, Linux")
        doc.add_heading("Experience", 2)
        doc.add_heading("Senior Python Engineer — TechCorp (2019–2024)", 3)
        doc.add_paragraph("6 years experience with FastAPI and PostgreSQL")
        doc.add_heading("Projects", 2)
        doc.add_heading("API Gateway", 3)
        doc.add_paragraph("Technologies: Python, FastAPI, Docker, Redis")
        doc.add_heading("Education", 2)
        doc.add_paragraph("Bachelor of Science Computer Science University 2019")
        doc.save(docx_path)

        result = parse_resume(docx_path)

        assert result.name != ""
        assert result.email != ""
        assert len(result.skills) > 0
        assert any("python" in s.lower() for s in result.skills)
        assert isinstance(result.education, list)
        assert isinstance(result.experience, list)
        assert isinstance(result.projects, list)
    except ImportError:
        pytest.skip("python-docx not installed")


def test_parse_resume_handles_missing_sections(tmp_path):
    """Parser should gracefully handle missing sections."""
    try:
        from docx import Document
        from app.services.resume_parser import parse_resume

        docx_path = str(tmp_path / "minimal.docx")
        doc = Document()
        doc.add_heading("Jane Doe", 0)
        doc.add_paragraph("jane@example.com")
        doc.add_paragraph("Python developer")
        doc.save(docx_path)

        result = parse_resume(docx_path)

        # Should not raise an exception
        assert result is not None
        assert isinstance(result.skills, list)
        assert isinstance(result.experience, list)
        assert isinstance(result.projects, list)
        assert isinstance(result.education, list)
        assert isinstance(result.certifications, list)
    except ImportError:
        pytest.skip("python-docx not installed")


def test_extract_inline_skills():
    from app.services.resume_parser import _extract_inline_skills

    text = "Experience with Python, FastAPI, Docker, and PostgreSQL."
    skills = _extract_inline_skills(text)
    assert "python" in skills
    assert "docker" in skills


def test_extract_name_from_lines():
    from app.services.resume_parser import _extract_name

    lines = [
        "Alex Smith",
        "alex.smith@example.com",
        "+1-555-0100",
        "Senior Engineer",
    ]
    name = _extract_name(lines)
    assert name.lower() != "unknown"
    assert "alex" in name.lower() or "smith" in name.lower()


def test_normalize_skill_casing():
    from app.services.skill_matcher import normalize_skill
    assert normalize_skill("Python") == normalize_skill("python") == normalize_skill("PYTHON")


def test_invalid_file_extension_raises():
    from app.services.resume_parser import extract_text
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text("resume.txt")


def test_docx_with_tables(tmp_path):
    """Test that tables in DOCX are also extracted."""
    try:
        from docx import Document
        from app.services.resume_parser import extract_text_from_docx

        docx_path = str(tmp_path / "table_resume.docx")
        doc = Document()
        doc.add_paragraph("Table Resume Candidate")
        table = doc.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = "Skill"
        table.rows[0].cells[1].text = "Level"
        table.rows[1].cells[0].text = "Python"
        table.rows[1].cells[1].text = "Expert"
        doc.save(docx_path)

        text = extract_text_from_docx(docx_path)
        assert "Python" in text
    except ImportError:
        pytest.skip("python-docx not installed")
