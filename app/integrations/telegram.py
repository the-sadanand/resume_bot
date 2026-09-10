"""Simple Telegram-only resume screening showcase.

No LLM, no external AI API, and no app.models dependency.
The bot extracts resume text and scores it against the job description
using transparent keyword matching.
"""
import re
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/integrations/telegram", tags=["Telegram"])
settings = get_settings()
logger = get_logger(__name__)

# Small, practical skill list for the showcase. Add skills here when needed.
SKILLS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "fastapi", "django", "flask", "react", "angular", "node.js", "nodejs",
    "docker", "kubernetes", "aws", "azure", "gcp", "git", "linux",
    "mysql", "postgresql", "mongodb", "redis", "sql", "nosql",
    "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy", "keras",
    "machine learning", "deep learning", "nlp", "computer vision", "data science",
    "rest api", "graphql", "microservices", "celery", "kafka", "spark",
]

# Per-user temporary showcase state. It intentionally avoids a database/model layer.
SESSIONS: dict[str, dict] = {}


def session_for(user_id: str) -> dict:
    return SESSIONS.setdefault(user_id, {"state": "idle", "jd": "", "resumes": []})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def contains_skill(text: str, skill: str) -> bool:
    text = normalize(text)
    skill = skill.lower()
    # Word boundaries work well for normal skills; simple substring handles phrases.
    if " " in skill or "." in skill or "+" in skill or "#" in skill:
        return skill in text
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", text))


def extract_skills(text: str) -> list[str]:
    return [skill for skill in SKILLS if contains_skill(text, skill)]


def extract_years(text: str) -> float:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", text.lower())
    return max((float(value) for value in matches), default=0.0)


def extract_candidate_name(text: str, filename: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:10]:
        if 2 <= len(line.split()) <= 5 and len(line) < 60:
            lower = line.lower()
            if not any(word in lower for word in ["resume", "curriculum", "email", "phone", "linkedin", "github"]):
                if not any(ch.isdigit() for ch in line):
                    return line
    return re.sub(r"[_-]+", " ", filename.rsplit(".", 1)[0]).strip() or "Candidate"


def extract_resume_text(file_bytes: bytes, filename: str) -> str:
    """Extract text from PDF or DOCX without any AI model."""
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        import fitz
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)

    if suffix == "docx":
        from docx import Document
        import io
        doc = Document(io.BytesIO(file_bytes))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        parts.append(cell.text.strip())
        return "\n".join(parts)

    raise ValueError("Only PDF and DOCX files are supported")


def score_resume(jd: str, resume: str) -> dict:
    jd_skills = extract_skills(jd)
    resume_skills = extract_skills(resume)
    matched = [skill for skill in jd_skills if skill in resume_skills]
    missing = [skill for skill in jd_skills if skill not in resume_skills]

    skills_score = (len(matched) / len(jd_skills) * 100) if jd_skills else 0.0

    required_years = extract_years(jd)
    resume_years = extract_years(resume)
    if required_years <= 0:
        experience_score = 100.0 if resume_years > 0 else 60.0
    else:
        experience_score = min(100.0, resume_years / required_years * 100)

    project_words = ["project", "developed", "built", "implemented"]
    project_score = min(100.0, 40.0 + sum(word in normalize(resume) for word in project_words) * 15.0)

    education_words = ["b.tech", "btech", "bachelor", "b.e", "m.tech", "mtech", "master", "degree"]
    education_score = 100.0 if any(word in normalize(resume) for word in education_words) else 40.0

    jd_match = skills_score
    completeness_fields = [
        bool(extract_candidate_name(resume, "candidate.pdf")),
        "@" in resume,
        bool(re.search(r"\b(?:experience|work)\b", resume, re.I)),
        bool(re.search(r"\b(?:education|b\.tech|bachelor|degree)\b", resume, re.I)),
        bool(resume_skills),
    ]
    completeness_score = sum(completeness_fields) / len(completeness_fields) * 100

    overall = (
        skills_score * 0.35
        + experience_score * 0.20
        + project_score * 0.15
        + education_score * 0.10
        + jd_match * 0.15
        + completeness_score * 0.05
    )

    if overall >= 85:
        recommendation = "STRONG MATCH"
    elif overall >= 70:
        recommendation = "GOOD MATCH"
    elif overall >= 55:
        recommendation = "MODERATE MATCH"
    else:
        recommendation = "WEAK MATCH"

    strengths = []
    gaps = []
    if matched:
        strengths.append("Good match on: " + ", ".join(matched[:5]))
    if experience_score >= 80:
        strengths.append("Experience level matches the job requirement")
    if resume_skills:
        strengths.append("Relevant technical skills found in the resume")
    if missing:
        gaps.append("Missing: " + ", ".join(missing[:5]))
    if required_years and resume_years < required_years:
        gaps.append(f"Experience found: {resume_years:g} years; required: {required_years:g} years")
    if not gaps:
        gaps.append("No major gaps detected by the keyword-based checker")

    return {
        "overall": overall,
        "skills": skills_score,
        "experience": experience_score,
        "projects": project_score,
        "education": education_score,
        "jd_match": jd_match,
        "completeness": completeness_score,
        "matched": matched,
        "missing": missing,
        "strengths": strengths,
        "gaps": gaps,
        "recommendation": recommendation,
    }


def format_result(candidate: str, result: dict) -> str:
    return (
        "📄 RESUME SCREENING RESULT\n\n"
        f"Candidate: {candidate}\n"
        f"Overall Score: {result['overall']:.1f}/100\n"
        f"Recommendation: {result['recommendation']}\n\n"
        "📊 SCORE BREAKDOWN\n"
        f"• Skills Match: {result['skills']:.1f}%\n"
        f"• Experience Match: {result['experience']:.1f}%\n"
        f"• Project Match: {result['projects']:.1f}%\n"
        f"• Education Match: {result['education']:.1f}%\n"
        f"• JD Requirement: {result['jd_match']:.1f}%\n"
        f"• Resume Completeness: {result['completeness']:.1f}%\n\n"
        "✅ MATCHED SKILLS\n"
        f"{', '.join(result['matched'][:10]) if result['matched'] else 'None found'}\n\n"
        "❌ MISSING SKILLS\n"
        f"{', '.join(result['missing'][:10]) if result['missing'] else 'None'}\n\n"
        "💪 STRENGTHS\n"
        + "\n".join(f"• {item}" for item in result["strengths"][:4])
        + "\n\n⚠️ GAPS\n"
        + "\n".join(f"• {item}" for item in result["gaps"][:4])
        + "\n\n📌 FINAL RECOMMENDATION\n"
        + result["recommendation"]
    )


async def send_message(chat_id: str, text: str) -> bool:
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured")
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            return response.status_code == 200
    except Exception as exc:
        logger.error(f"Telegram send failed: {type(exc).__name__}")
        return False


async def download_file(file_id: str) -> Optional[bytes]:
    if not settings.telegram_bot_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            meta = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                params={"file_id": file_id},
            )
            meta.raise_for_status()
            path = meta.json()["result"]["file_path"]
            response = await client.get(
                f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{path}"
            )
            response.raise_for_status()
            return response.content
    except Exception as exc:
        logger.error(f"Telegram download failed: {type(exc).__name__}")
        return None


@router.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = str(message["chat"]["id"])
    user_id = str(message["from"]["id"])
    text = message.get("text", "").strip()
    document = message.get("document")
    session = session_for(user_id)

    if text.startswith("/start") or text.startswith("/help"):
        await send_message(
            chat_id,
            "👋 Resume Screening Bot\n\n"
            "/analyze - start screening\n"
            "/screen - analyze uploaded resumes\n"
            "/reset - start over\n\n"
            "1. Send a Job Description\n"
            "2. Upload PDF/DOCX resume(s)\n"
            "3. Send /screen\n\n"
            "The score is transparent keyword-based matching; no OpenAI API is required."
        )
        return {"ok": True}

    if text.startswith("/reset"):
        session.update({"state": "idle", "jd": "", "resumes": []})
        await send_message(chat_id, "✅ Reset complete. Use /analyze to start.")
        return {"ok": True}

    if text.startswith("/analyze"):
        session.update({"state": "awaiting_jd", "jd": "", "resumes": []})
        await send_message(chat_id, "📋 Send the Job Description text now.")
        return {"ok": True}

    if session["state"] == "awaiting_jd" and text and not text.startswith("/"):
        session["jd"] = text
        session["state"] = "awaiting_resumes"
        skills = extract_skills(text)
        await send_message(
            chat_id,
            "✅ Job Description received\n\n"
            f"Detected skills: {', '.join(skills[:10]) if skills else 'None'}\n\n"
            "📎 Upload one or more PDF/DOCX resumes.\n"
            "When finished, send /screen."
        )
        return {"ok": True}

    if session["state"] == "awaiting_resumes":
        if document:
            filename = document.get("file_name", "resume.pdf")
            if not filename.lower().endswith((".pdf", ".docx")):
                await send_message(chat_id, "❌ Only PDF and DOCX files are supported.")
                return {"ok": True}

            file_bytes = await download_file(document["file_id"])
            if not file_bytes:
                await send_message(chat_id, "❌ Could not download the resume. Try again.")
                return {"ok": True}

            try:
                resume_text = extract_resume_text(file_bytes, filename)
                if not resume_text.strip():
                    raise ValueError("No text found")
                candidate = extract_candidate_name(resume_text, filename)
                session["resumes"].append({"name": candidate, "text": resume_text})
                await send_message(
                    chat_id,
                    f"✅ Resume received: {candidate}\n"
                    f"Skills found: {len(extract_skills(resume_text))}\n\n"
                    "Send another resume or /screen."
                )
            except Exception as exc:
                logger.error(f"Resume parsing failed: {type(exc).__name__}")
                await send_message(chat_id, "❌ Could not read this resume. Try another PDF/DOCX.")
            return {"ok": True}

        if text.startswith("/screen"):
            if not session["resumes"]:
                await send_message(chat_id, "❌ Upload at least one resume first.")
                return {"ok": True}

            await send_message(chat_id, f"⏳ Screening {len(session['resumes'])} resume(s)...")
            results = []
            for resume in session["resumes"]:
                result = score_resume(session["jd"], resume["text"])
                results.append((resume["name"], result))
            results.sort(key=lambda item: item[1]["overall"], reverse=True)

            for index, (candidate, result) in enumerate(results, start=1):
                prefix = f"🏆 RANK #{index}\n\n" if len(results) > 1 else ""
                await send_message(chat_id, prefix + format_result(candidate, result))

            session.update({"state": "idle", "jd": "", "resumes": []})
            return {"ok": True}

    if session["state"] == "idle":
        await send_message(chat_id, "Use /analyze to start resume screening.")

    return {"ok": True}
