"""
Resume Parser Service
Extracts text and structured information from PDF and DOCX files
Uses PyMuPDF for PDF and python-docx for DOCX
"""
import re
import os
import logging
from pathlib import Path
from typing import Optional

from app.models.resume import ParsedResume, EducationEntry, ExperienceEntry, ProjectEntry
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def extract_text_from_pdf(file_path: str) -> str:
    """Extract raw text from a PDF file using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        text_parts = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        raise ValueError(f"Failed to extract text from PDF: {e}")


def extract_text_from_docx(file_path: str) -> str:
    """Extract raw text from a DOCX file using python-docx."""
    try:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        paragraphs.append(cell.text.strip())
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        raise ValueError(f"Failed to extract text from DOCX: {e}")


def extract_text(file_path: str) -> str:
    """Extract text from PDF or DOCX file."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext == ".docx":
        return extract_text_from_docx(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


# ── Pattern helpers ──────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?"
    r"(?:\(?\d{2,4}\)?[\s\-.]?)?"
    r"\d{3,4}[\s\-.]?\d{3,4}"
    r"(?:[\s\-.]?\d{2,4})?"
)

SECTION_HEADERS = {
    "summary": ["summary", "objective", "profile", "about me", "about", "career objective", "professional summary"],
    "education": ["education", "academic background", "qualifications", "academic qualifications", "degrees"],
    "skills": ["skills", "technical skills", "core skills", "competencies", "expertise", "technologies", "tech stack"],
    "experience": ["experience", "work experience", "employment", "professional experience", "work history", "career history"],
    "projects": ["projects", "personal projects", "key projects", "project work"],
    "certifications": ["certifications", "certificates", "certifications & licenses", "courses"],
    "achievements": ["achievements", "awards", "honors", "accomplishments"],
}

EDUCATION_DEGREES = [
    "phd", "ph.d", "doctorate", "master", "mba", "msc", "m.tech", "m.e", "bachelor",
    "bsc", "b.tech", "b.e", "b.com", "b.a", "diploma", "associate",
]

YEAR_RE = re.compile(r"(19|20)\d{2}")
DURATION_RE = re.compile(
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"[\s,]+(?:19|20)\d{2})"
    r"\s*[\-–—to]+\s*"
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"[\s,]+(?:19|20)\d{2}|present|current|now)",
    re.IGNORECASE,
)
YEARS_EXPERIENCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", re.IGNORECASE)


def _detect_section(line: str) -> Optional[str]:
    """Return which section a header line belongs to, or None."""
    clean = line.strip().lower().rstrip(":")
    for section, keywords in SECTION_HEADERS.items():
        if clean in keywords:
            return section
    return None


def _extract_name(lines: list[str]) -> str:
    """Heuristically extract the candidate name from the top of the resume."""
    for line in lines[:10]:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip lines that look like emails, phones, URLs, or section headers
        if EMAIL_RE.search(stripped):
            continue
        if PHONE_RE.search(stripped) and len(stripped) < 20:
            continue
        if stripped.startswith("http"):
            continue
        if _detect_section(stripped):
            continue
        # Likely a name: 2-4 words, mostly alphabetic
        words = stripped.split()
        if 2 <= len(words) <= 5 and all(w.replace(".", "").isalpha() for w in words):
            return stripped.title()
    return "Unknown"


def _split_into_sections(text: str) -> dict[str, str]:
    """Split resume text into labeled sections."""
    lines = text.splitlines()
    sections: dict[str, list[str]] = {s: [] for s in SECTION_HEADERS}
    sections["header"] = []
    current_section = "header"

    for line in lines:
        detected = _detect_section(line)
        if detected:
            current_section = detected
        else:
            sections[current_section].append(line)

    return {k: "\n".join(v) for k, v in sections.items()}


def _parse_skills(skills_text: str) -> list[str]:
    """Extract skills from the skills section."""
    skills = []
    # Try comma or bullet-separated
    for delimiter in [",", "•", "●", "▪", "|", "\n", "/"]:
        parts = skills_text.split(delimiter)
        if len(parts) > 2:
            skills = [p.strip().strip("·-–—") for p in parts if p.strip()]
            break
    if not skills:
        skills = [s.strip() for s in skills_text.splitlines() if s.strip()]
    return [s for s in skills if s and len(s) < 60]


def _parse_education(education_text: str) -> list[EducationEntry]:
    """Parse education section."""
    entries = []
    lines = [l.strip() for l in education_text.splitlines() if l.strip()]
    current: dict = {}

    for line in lines:
        lower = line.lower()
        # Degree detection
        if any(d in lower for d in EDUCATION_DEGREES):
            if current:
                entries.append(EducationEntry(**current))
            current = {"degree": line.strip()}
        elif current:
            if not current.get("institution"):
                current["institution"] = line.strip()
            elif not current.get("year"):
                years = YEAR_RE.findall(line)
                if years:
                    current["year"] = years[-1]
                elif not current.get("field_of_study"):
                    current["field_of_study"] = line.strip()
    if current:
        entries.append(EducationEntry(**current))
    return entries


def _estimate_years(duration_str: str) -> float:
    """Estimate years of experience from a duration string."""
    matches = YEARS_EXPERIENCE_RE.findall(duration_str)
    if matches:
        return float(matches[0])
    # Try date range
    dur_match = DURATION_RE.search(duration_str)
    if dur_match:
        try:
            from dateutil import parser as dateparser
            start = dateparser.parse(dur_match.group(1), default=None)
            end_str = dur_match.group(2)
            if end_str.lower() in ("present", "current", "now"):
                from datetime import date
                end = date.today()
            else:
                end = dateparser.parse(end_str, default=None).date()
            if start:
                return round((end - start.date()).days / 365.25, 1)
        except Exception:
            pass
    return 0.0


def _parse_experience(experience_text: str) -> tuple[list[ExperienceEntry], float]:
    """Parse experience section. Returns (entries, total_years)."""
    entries = []
    lines = [l.strip() for l in experience_text.splitlines() if l.strip()]
    current: dict = {}
    total_years = 0.0

    for line in lines:
        # Check for duration
        years_match = YEARS_EXPERIENCE_RE.search(line)
        dur_match = DURATION_RE.search(line)

        if dur_match or (years_match and len(line) < 60):
            if current and not current.get("duration"):
                current["duration"] = line
                current["years"] = _estimate_years(line)
                total_years += current["years"]
        elif len(line) < 80 and any(kw in line.lower() for kw in [
            "engineer", "developer", "manager", "lead", "analyst", "architect",
            "consultant", "scientist", "intern", "associate", "director", "head"
        ]):
            if current:
                entries.append(ExperienceEntry(**current))
            current = {"title": line.strip(), "description": ""}
        elif current:
            desc = current.get("description", "")
            current["description"] = (desc + "\n" + line).strip()
            # Extract technologies from lines with tech keywords
            techs = _extract_inline_skills(line)
            existing_techs = current.get("technologies", [])
            current["technologies"] = list(set(existing_techs + techs))

    if current:
        entries.append(ExperienceEntry(**current))

    return entries, total_years


def _parse_projects(projects_text: str) -> list[ProjectEntry]:
    """Parse projects section."""
    projects = []
    lines = [l.strip() for l in projects_text.splitlines() if l.strip()]
    current: dict = {}

    for line in lines:
        if len(line) < 80 and not line.startswith(("•", "-", "–", "▪")):
            if current:
                projects.append(ProjectEntry(**current))
            current = {"name": line.strip(), "description": "", "technologies": []}
        elif current:
            desc = current.get("description", "")
            current["description"] = (desc + " " + line).strip()
            techs = _extract_inline_skills(line)
            current["technologies"] = list(set(current.get("technologies", []) + techs))

    if current:
        projects.append(ProjectEntry(**current))
    return projects


# Common technology keywords for inline extraction
TECH_KEYWORDS = {
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang",
    "rust", "swift", "kotlin", "ruby", "php", "scala", "r",
    "fastapi", "django", "flask", "spring", "react", "angular", "vue", "nextjs",
    "nodejs", "express", "rails",
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "github actions",
    "aws", "azure", "gcp", "google cloud",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite",
    "kafka", "rabbitmq", "celery",
    "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy", "keras",
    "git", "linux", "bash", "powershell",
    "rest", "graphql", "grpc", "microservices", "api",
    "html", "css", "tailwind", "bootstrap",
    "nginx", "apache", "gunicorn", "uvicorn",
}


def _extract_inline_skills(text: str) -> list[str]:
    """Extract technology mentions from arbitrary text."""
    text_lower = text.lower()
    found = []
    for tech in TECH_KEYWORDS:
        if re.search(r"\b" + re.escape(tech) + r"\b", text_lower):
            found.append(tech)
    return found


def parse_resume(file_path: str) -> ParsedResume:
    """
    Main entry point: parse a resume file and return structured data.
    Privacy: raw_text is stored but should not be logged.
    """
    raw_text = extract_text(file_path)
    lines = raw_text.splitlines()
    sections = _split_into_sections(raw_text)

    name = _extract_name(lines)

    # Email
    email_match = EMAIL_RE.search(raw_text)
    email = email_match.group(0) if email_match else ""

    # Phone (first match after email region)
    phone = ""
    for line in lines[:15]:
        pm = PHONE_RE.search(line)
        if pm and "@" not in line:
            candidate = pm.group(0).strip()
            if len(candidate) >= 7:
                phone = candidate
                break

    # Skills
    skills = _parse_skills(sections.get("skills", ""))
    # Supplement with inline skills from whole document
    inline_skills = _extract_inline_skills(raw_text)
    all_skills = list({s.lower(): s for s in skills + inline_skills}.values())

    # Education
    education = _parse_education(sections.get("education", ""))

    # Experience
    experience, total_years = _parse_experience(sections.get("experience", ""))

    # Projects
    projects = _parse_projects(sections.get("projects", ""))

    # Certifications
    cert_text = sections.get("certifications", "")
    certifications = [l.strip().lstrip("•-–▪ ") for l in cert_text.splitlines() if l.strip()]

    # Achievements
    ach_text = sections.get("achievements", "")
    achievements = [l.strip().lstrip("•-–▪ ") for l in ach_text.splitlines() if l.strip()]

    # Summary
    summary = sections.get("summary", "").strip()[:500]

    return ParsedResume(
        name=name,
        email=email,
        phone=phone,
        summary=summary,
        education=education,
        skills=all_skills,
        experience=experience,
        projects=projects,
        certifications=certifications,
        achievements=achievements,
        raw_text=raw_text,
        total_years_experience=total_years,
    )
