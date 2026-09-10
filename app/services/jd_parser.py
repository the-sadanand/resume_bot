"""
Job Description Parser Service
Extracts structured information from job description text
"""
import re
import logging
from typing import Optional

from app.models.job import ParsedJobDescription
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Skill-related section identifiers
REQUIRED_SECTION_PATTERNS = [
    r"required\s+(?:skills?|qualifications?|requirements?)",
    r"must\s+have",
    r"mandatory",
    r"essential\s+skills?",
]

PREFERRED_SECTION_PATTERNS = [
    r"preferred\s+(?:skills?|qualifications?)",
    r"nice\s+to\s+have",
    r"bonus",
    r"desired\s+skills?",
    r"good\s+to\s+have",
    r"optional",
    r"plus",
]

RESPONSIBILITIES_PATTERNS = [
    r"responsibilities",
    r"what\s+you(?:'ll)?\s+do",
    r"role\s+overview",
    r"key\s+responsibilities",
    r"job\s+duties",
    r"your\s+role",
]

EDUCATION_PATTERNS = [
    r"education(?:al)?\s+requirements?",
    r"academic\s+background",
    r"degree\s+requirements?",
    r"educational\s+qualifications?",
]

EXPERIENCE_PATTERNS = [
    r"experience\s+requirements?",
    r"years?\s+of\s+experience",
    r"work\s+experience",
]

YEARS_RE = re.compile(r"(\d+)\+?\s*years?", re.IGNORECASE)
TITLE_PATTERNS = [
    r"job\s+title\s*:?\s*(.+)",
    r"position\s*:?\s*(.+)",
    r"role\s*:?\s*(.+)",
]

# Technology keyword list (used for extraction)
TECH_KEYWORDS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust",
    "swift", "kotlin", "ruby", "php", "scala", "r", "matlab",
    "fastapi", "django", "flask", "spring", "springboot", "react", "angular", "vue",
    "nextjs", "nodejs", "express", "rails", "laravel", "symfony", ".net", "asp.net",
    "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins", "ci/cd",
    "github actions", "gitlab ci", "circleci",
    "aws", "azure", "gcp", "google cloud", "heroku", "digitalocean",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite", "oracle",
    "dynamodb", "cassandra", "neo4j",
    "kafka", "rabbitmq", "celery", "airflow",
    "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy", "keras", "hugging face",
    "git", "linux", "bash", "powershell", "unix",
    "rest", "graphql", "grpc", "microservices", "api", "soap",
    "html", "css", "tailwind", "bootstrap", "sass",
    "nginx", "apache", "gunicorn", "uvicorn",
    "machine learning", "deep learning", "nlp", "computer vision", "data science",
    "sql", "nosql", "spark", "hadoop", "databricks",
    "jira", "confluence", "agile", "scrum", "kanban",
]

DEGREE_KEYWORDS = [
    "bachelor", "master", "phd", "doctorate", "associate", "diploma",
    "b.s.", "m.s.", "b.e.", "m.e.", "b.tech", "m.tech", "mba", "b.sc", "m.sc",
]


def _find_section_text(text: str, patterns: list[str], stop_patterns: list[list[str]] = None) -> str:
    """Extract a section from JD text based on header patterns."""
    lines = text.splitlines()
    section_lines = []
    in_section = False

    stop_all = []
    if stop_patterns:
        for sp in stop_patterns:
            stop_all.extend(sp)

    combined = "|".join(patterns)
    stop_combined = "|".join(stop_all) if stop_all else None

    for line in lines:
        line_clean = line.strip().lower()
        if re.search(combined, line_clean, re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if stop_combined and re.search(stop_combined, line_clean, re.IGNORECASE):
                break
            section_lines.append(line)

    return "\n".join(section_lines)


def _extract_bullet_items(text: str) -> list[str]:
    """Extract bullet-point or numbered list items from text."""
    items = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("•●▪-–—*·1234567890.)> ").strip()
        if stripped and len(stripped) > 3:
            items.append(stripped)
    return items


def _extract_technologies(text: str) -> list[str]:
    """Extract technology mentions from text."""
    text_lower = text.lower()
    found = []
    for tech in TECH_KEYWORDS:
        if re.search(r"\b" + re.escape(tech) + r"\b", text_lower):
            found.append(tech)
    return found


def _extract_skills_from_text(text: str) -> list[str]:
    """Extract skills from unstructured text, including inline lists."""
    skills = []

    # Try comma-separated inline skill lists
    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        parts = re.split(r"[,;]", line_stripped)
        if len(parts) >= 3:
            for part in parts:
                p = part.strip().lstrip("•●▪-– ").strip()
                if p and len(p) < 60:
                    skills.append(p)
        else:
            p = line_stripped.lstrip("•●▪-– ").strip()
            if p and len(p) < 60:
                skills.append(p)

    # Also extract known tech keywords
    tech_found = _extract_technologies(text)
    all_skills = list(dict.fromkeys(skills + tech_found))  # preserve order, deduplicate
    return [s for s in all_skills if s]


def _extract_min_years(text: str) -> float:
    """Find the minimum years of experience required."""
    matches = YEARS_RE.findall(text)
    if matches:
        years = [int(m) for m in matches]
        return float(min(years))
    return 0.0


def _extract_keywords(text: str) -> list[str]:
    """Extract notable keywords from JD."""
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9+#.\-]{2,}\b", text)
    # Count frequency
    freq: dict[str, int] = {}
    for w in words:
        key = w.lower()
        freq[key] = freq.get(key, 0) + 1

    # Filter stopwords
    stopwords = {
        "the", "and", "for", "with", "are", "you", "our", "will", "your",
        "have", "that", "this", "from", "not", "but", "all", "any", "can",
        "also", "work", "team", "good", "role", "some", "into", "more",
        "what", "who", "its", "they", "them", "their", "able", "must",
        "should", "would", "could", "use", "using", "used", "working",
        "experience", "skills", "years", "required", "preferred",
    }

    keywords = [
        w for w, c in sorted(freq.items(), key=lambda x: -x[1])
        if w not in stopwords and c >= 2 and len(w) >= 3
    ]
    return keywords[:20]


def _guess_title(text: str) -> str:
    """Try to extract job title from beginning of JD."""
    first_lines = text.strip().splitlines()[:5]
    for line in first_lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Check for title: value format
        for pattern in TITLE_PATTERNS:
            m = re.search(pattern, stripped, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        # If short line at top, it might be the title
        if len(stripped) < 80 and stripped[0].isupper():
            return stripped
    return "Software Engineer"


def parse_job_description(text: str, provided_title: str = "") -> ParsedJobDescription:
    """
    Main entry point: parse a job description text and return structured data.
    """
    # Title
    job_title = provided_title or _guess_title(text)

    # Required skills section
    req_text = _find_section_text(
        text,
        REQUIRED_SECTION_PATTERNS,
        [PREFERRED_SECTION_PATTERNS, RESPONSIBILITIES_PATTERNS],
    )
    required_skills = _extract_skills_from_text(req_text)

    # Preferred skills section
    pref_text = _find_section_text(
        text,
        PREFERRED_SECTION_PATTERNS,
        [RESPONSIBILITIES_PATTERNS, EDUCATION_PATTERNS],
    )
    preferred_skills = _extract_skills_from_text(pref_text)

    # Responsibilities
    resp_text = _find_section_text(
        text,
        RESPONSIBILITIES_PATTERNS,
        [REQUIRED_SECTION_PATTERNS, EDUCATION_PATTERNS, EXPERIENCE_PATTERNS],
    )
    responsibilities = _extract_bullet_items(resp_text)

    # Education requirements
    edu_text = _find_section_text(text, EDUCATION_PATTERNS)
    education_requirements = _extract_bullet_items(edu_text)
    if not education_requirements:
        # Look for degree mentions in full text
        for line in text.splitlines():
            if any(d in line.lower() for d in DEGREE_KEYWORDS):
                education_requirements.append(line.strip())

    # Experience requirements
    exp_text = _find_section_text(text, EXPERIENCE_PATTERNS)
    experience_requirements = _extract_bullet_items(exp_text)
    if not experience_requirements:
        for line in text.splitlines():
            if YEARS_RE.search(line) and "experience" in line.lower():
                experience_requirements.append(line.strip())

    # Technologies
    technologies = _extract_technologies(text)

    # Keywords
    keywords = _extract_keywords(text)

    # If required_skills is empty, fall back to extracting from full text
    if not required_skills:
        required_skills = _extract_technologies(text)

    # Min years
    min_years = _extract_min_years(text)

    return ParsedJobDescription(
        job_title=job_title,
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        experience_requirements=experience_requirements,
        education_requirements=education_requirements,
        responsibilities=responsibilities,
        technologies=technologies,
        keywords=keywords,
        min_years_experience=min_years,
        raw_text=text,
    )
