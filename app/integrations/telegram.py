"""Telegram-only resume screening showcase with defensive validation and transparent scoring."""
import hashlib
import io
import re
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/integrations/telegram", tags=["Telegram"])
settings = get_settings()
logger = get_logger(__name__)

MAX_RESUMES = 10
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_TEXT_SIZE = 20000
MIN_JD_LENGTH = 80
MIN_RESUME_TEXT = 120
MAX_PAGES = 40

SKILLS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "fastapi", "django", "flask", "react", "angular", "node.js", "nodejs",
    "docker", "kubernetes", "aws", "azure", "gcp", "git", "linux", "mysql",
    "postgresql", "mongodb", "redis", "sql", "nosql", "tensorflow", "pytorch",
    "scikit-learn", "pandas", "numpy", "keras", "machine learning", "deep learning",
    "nlp", "computer vision", "data science", "rest api", "graphql", "microservices",
    "celery", "kafka", "spark", "mlflow", "prometheus", "solidity", "rag",
    "llm", "generative ai", "artificial intelligence", "gitlab", "jenkins"
]
AMBIGUOUS_SKILLS = {"go", "r", "c"}
SKILL_ALIASES = {
    "node.js": "node.js", "nodejs": "node.js", "react.js": "react", "reactjs": "react",
    "fast api": "fastapi", "scikit learn": "scikit-learn", "sklearn": "scikit-learn",
    "postgres": "postgresql", "postgresql": "postgresql", "restful api": "rest api",
    "restful apis": "rest api", "ml": "machine learning", "ai": "artificial intelligence",
    "gen ai": "generative ai", "genai": "generative ai"
}

COURSES = {
    "python": ("Python", "https://www.python.org/about/gettingstarted/"),
    "fastapi": ("FastAPI", "https://fastapi.tiangolo.com/tutorial/"),
    "docker": ("Docker", "https://docs.docker.com/get-started/"),
    "git": ("Git", "https://git-scm.com/docs/gittutorial"),
    "aws": ("AWS", "https://aws.amazon.com/training/"),
    "sql": ("SQL", "https://www.w3schools.com/sql/"),
    "pytorch": ("PyTorch", "https://pytorch.org/tutorials/"),
    "tensorflow": ("TensorFlow", "https://www.tensorflow.org/learn"),
    "scikit-learn": ("Scikit-learn", "https://scikit-learn.org/stable/getting_started.html"),
    "pandas": ("Pandas", "https://pandas.pydata.org/docs/getting_started/intro_tutorials/"),
    "numpy": ("NumPy", "https://numpy.org/learn/"),
    "machine learning": ("Machine Learning", "https://scikit-learn.org/stable/getting_started.html"),
    "react": ("React", "https://react.dev/learn"),
    "java": ("Java", "https://dev.java/learn/"),
    "javascript": ("JavaScript", "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide"),
    "kubernetes": ("Kubernetes", "https://kubernetes.io/docs/tutorials/"),
    "linux": ("Linux", "https://ubuntu.com/tutorials/command-line-for-beginners")
}

SESSIONS = {}


def session_for(uid):
    return SESSIONS.setdefault(uid, {"state": "idle", "jd": "", "resumes": [], "updated": datetime.utcnow()})


def normalize(text):
    text = text or ""
    return re.sub(r"\s+", " ", text.lower()).strip()


def canonical_skill(skill):
    return SKILL_ALIASES.get(skill.lower(), skill.lower())


def contains_skill(text, skill):
    text = normalize(text)
    skill = skill.lower()
    if skill in AMBIGUOUS_SKILLS:
        if skill == "go":
            return bool(re.search(r"\b(?:golang|go\s+(?:programming|development|developer|language|modules|goroutines))\b", text))
        return False
    aliases = [skill]
    aliases += [k for k, v in SKILL_ALIASES.items() if v == skill]
    return any(bool(re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", text)) for a in aliases)


def extract_skills(text):
    found = []
    for skill in SKILLS:
        if contains_skill(text, skill):
            c = canonical_skill(skill)
            if c not in found:
                found.append(c)
    return found


def extract_years(text):
    text = normalize(text)
    values = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", text)]
    values += [float(x) / 12 for x in re.findall(r"(\d+)\s*\+?\s*months?", text)]
    for a, b in re.findall(r"(20\d{2})\s*(?:-|–|—|to)\s*(20\d{2}|present|current)", text):
        end = datetime.utcnow().year if b in {"present", "current"} else int(b)
        start = int(a)
        if end >= start:
            values.append(float(end - start))
    return max(values, default=0.0)


def extract_required_preferred_skills(jd):
    required, preferred = [], []
    mode = "required"
    for line in jd.splitlines():
        low = normalize(line)
        if any(x in low for x in ["nice to have", "preferred", "bonus", "optional", "good to have"]):
            mode = "preferred"
        elif any(x in low for x in ["required", "must have", "qualifications", "requirements", "must-have"]):
            mode = "required"
        for skill in extract_skills(line):
            target = preferred if mode == "preferred" else required
            if skill not in target:
                target.append(skill)
    all_skills = extract_skills(jd)
    for skill in all_skills:
        if skill not in required and skill not in preferred:
            required.append(skill)
    return required, preferred


def validate_jd(text):
    clean = (text or "").strip()
    if len(clean) < MIN_JD_LENGTH:
        return False, "The Job Description is too short. Please include the role, responsibilities, requirements, experience or skills."
    if len(clean) > MAX_TEXT_SIZE:
        return False, "The Job Description is too long. Please send a shorter JD under 20,000 characters."
    low = normalize(clean)
    role_signals = [
        "developer", "engineer", "analyst", "designer", "manager", "intern", "consultant",
        "scientist", "architect", "specialist", "administrator", "responsibilities", "qualifications",
        "requirements", "experience", "skills", "job description", "role", "hiring", "candidate",
        "job responsibilities", "what you will do", "what we're looking for", "what we are looking for"
    ]
    signal_count = sum(1 for x in role_signals if re.search(r"\b" + re.escape(x) + r"\b", low) or x in low)
    skills = extract_skills(clean)
    action_signals = sum(x in low for x in ["develop", "build", "design", "maintain", "implement", "work with", "responsible for"])
    if signal_count < 2 and not skills:
        return False, "This does not look like a Job Description. Please send the actual job role, responsibilities, requirements or skills."
    if not skills and signal_count < 3 and action_signals == 0:
        return False, "I could not identify enough job requirements. Please include relevant skills, responsibilities or qualifications."
    return True, ""


def extract_candidate_name(text, filename):
    blocked = ["resume", "curriculum", "email", "phone", "linkedin", "github", "profile", "objective", "summary", "experience", "education", "skills"]
    for line in [x.strip() for x in text.splitlines() if x.strip()][:15]:
        low = line.lower()
        words = line.split()
        if 2 <= len(words) <= 5 and len(line) < 60 and not any(x in low for x in blocked) and not any(c.isdigit() for c in line) and "@" not in line and not re.search(r"https?://|www\.", low):
            return line
    base = filename.rsplit(".", 1)[0]
    base = re.sub(r"[_-]+", " ", base).strip()
    return base if base and base.lower() not in {"resume", "cv", "curriculum vitae", "final resume"} else "Candidate"


def extract_document_text(data, filename):
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.page_count > MAX_PAGES:
                raise ValueError(f"Document has too many pages. Maximum supported is {MAX_PAGES} pages.")
            return "\n".join(p.get_text() for p in doc)
    if suffix == "docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        parts.append(cell.text.strip())
        return "\n".join(parts)
    raise ValueError("Only PDF and DOCX files can be read.")


def validate_resume(text, filename):
    clean = (text or "").strip()
    if len(clean) < MIN_RESUME_TEXT:
        return False, "This file has too little readable text. It may be scanned/image-only. Please upload a text-based PDF or DOCX resume."
    if len(clean) > MAX_TEXT_SIZE * 3:
        return False, "This resume is unusually large. Please upload a concise resume under 40 pages."
    low = normalize(clean)
    signals = sum([
        bool(re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", clean, re.I)),
        bool(re.search(r"\b(?:education|degree|b\.tech|btech|bachelor|m\.tech|master|mba|mca)\b", low)),
        bool(re.search(r"\b(?:experience|employment|work history|professional experience|internship)\b", low)),
        bool(extract_skills(clean)),
        bool(re.search(r"\b(?:project|projects|achievements|certifications)\b", low)),
        len(clean.split()) >= 80
    ])
    if signals < 3:
        return False, "This file does not look like a complete resume. Please upload a resume containing contact, education, experience, skills or project information."
    return True, ""


def degree_level(text):
    low = normalize(text)
    if re.search(r"\b(?:ph\.d|phd|doctorate)\b", low): return 5
    if re.search(r"\b(?:m\.tech|mtech|m\.e\b|master|mba|mca)\b", low): return 4
    if re.search(r"\b(?:b\.tech|btech|b\.e\b|bachelor|bsc|bca)\b", low): return 3
    if re.search(r"\b(?:diploma|associate)\b", low): return 2
    return 0


def education_field(text):
    low = normalize(text)
    fields = [
        "computer science", "information technology", "software", "artificial intelligence", "machine learning",
        "data science", "electronics", "electrical", "mechanical", "civil", "business", "finance", "marketing"
    ]
    return next((x for x in fields if x in low), "")


def education_score(jd, resume):
    jd_level, resume_level = degree_level(jd), degree_level(resume)
    jd_field, resume_field = education_field(jd), education_field(resume)
    if not jd_level:
        score = 100.0 if resume_level else 60.0
        note = "No specific degree requirement detected"
    elif resume_level >= jd_level:
        score = 100.0
        note = "Education level meets the JD"
    elif resume_level == jd_level - 1:
        score = 55.0
        note = "Education is below the stated JD level"
    else:
        score = 25.0
        note = "Required education level not clearly found"
    if jd_field and resume_field:
        if jd_field == resume_field:
            score = min(100.0, score + 5)
            note += "; field matches"
        else:
            score = max(0.0, score - 15)
            note += f"; field mismatch ({resume_field} vs {jd_field})"
    return score, note


def project_score(jd, resume):
    jd_skills = set(extract_skills(jd))
    if not jd_skills:
        return 60.0, []
    lines = resume.splitlines()
    project_lines, in_project = [], False
    headings = ["experience", "education", "certification", "skills", "achievements", "internship"]
    for line in lines:
        low = normalize(line)
        if any(x in low for x in ["projects", "project experience", "personal projects", "academic projects"]):
            in_project = True
            continue
        if in_project and any(x in low for x in headings) and len(low.split()) <= 4:
            in_project = False
        if in_project and line.strip():
            project_lines.append(line)
    project_text = " ".join(project_lines)
    project_skills = set(extract_skills(project_text))
    overlap = len(jd_skills & project_skills) / len(jd_skills) if jd_skills else 0
    evidence = sum(bool(re.search(r"\b(?:built|developed|implemented|created|deployed|designed|trained|automated)\b", x, re.I)) for x in project_lines)
    score = min(100.0, 25.0 + overlap * 65.0 + min(evidence, 2) * 5.0) if project_lines else 20.0
    return score, sorted(jd_skills & project_skills)


def score_resume(jd, resume):
    jd_skills = extract_skills(jd)
    resume_skills = extract_skills(resume)
    required, preferred = extract_required_preferred_skills(jd)
    matched = [s for s in jd_skills if s in resume_skills]
    missing = [s for s in jd_skills if s not in resume_skills]
    skills = len(matched) / len(jd_skills) * 100 if jd_skills else 50.0
    required_matched = [s for s in required if s in resume_skills]
    preferred_matched = [s for s in preferred if s in resume_skills]
    req_pct = len(required_matched) / len(required) * 100 if required else 100.0
    pref_pct = len(preferred_matched) / len(preferred) * 100 if preferred else 100.0
    jd_match = req_pct * 0.80 + pref_pct * 0.20
    required_years = extract_years(jd)
    resume_years = extract_years(resume)
    if required_years:
        experience = min(100.0, resume_years / required_years * 100) if resume_years else 0.0
    else:
        experience = 100.0 if resume_years else 60.0
    projects, project_matches = project_score(jd, resume)
    education, education_note = education_score(jd, resume)
    completeness = sum([
        bool(re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", resume, re.I)),
        bool(re.search(r"\b(?:experience|employment|work history|internship)\b", resume, re.I)),
        bool(re.search(r"\b(?:education|degree|b\.tech|btech|bachelor)\b", resume, re.I)),
        bool(resume_skills),
        bool(re.search(r"\b(?:project|projects)\b", resume, re.I))
    ]) / 5 * 100
    overall = skills*.35 + experience*.20 + projects*.15 + education*.10 + jd_match*.15 + completeness*.05
    rec = "STRONG MATCH" if overall >= 85 else "GOOD MATCH" if overall >= 70 else "MODERATE MATCH" if overall >= 55 else "WEAK MATCH"
    evidence_count = sum([bool(matched), bool(resume_years), bool(project_matches), bool(resume_skills), completeness >= 60])
    confidence = "HIGH" if evidence_count >= 4 and completeness >= 80 else "MEDIUM" if evidence_count >= 2 else "LOW"
    strengths, gaps = [], []
    if matched: strengths.append("Skills matched: " + ", ".join(matched[:6]))
    if required_matched: strengths.append("Required skills matched: " + ", ".join(required_matched[:5]))
    if project_matches: strengths.append("Relevant project evidence: " + ", ".join(project_matches[:5]))
    if required_years and resume_years >= required_years: strengths.append("Experience requirement is met")
    if missing: gaps.append("Missing skills: " + ", ".join(missing[:6]))
    missing_required = [s for s in required if s not in resume_skills]
    if missing_required: gaps.append("Required skills missing: " + ", ".join(missing_required[:6]))
    missing_preferred = [s for s in preferred if s not in resume_skills]
    if missing_preferred: gaps.append("Preferred skills missing: " + ", ".join(missing_preferred[:5]))
    if required_years and resume_years < required_years: gaps.append(f"Experience: {resume_years:g} years found vs {required_years:g} required")
    if education < 80: gaps.append(education_note)
    if not gaps: gaps.append("No major gaps detected")
    explanation = [
        f"Skills 35%: {skills:.0f} × 0.35 = {skills*.35:.1f}",
        f"Experience 20%: {experience:.0f} × 0.20 = {experience*.20:.1f}",
        f"Projects 15%: {projects:.0f} × 0.15 = {projects*.15:.1f}",
        f"Education 10%: {education:.0f} × 0.10 = {education*.10:.1f}",
        f"JD Requirements 15%: {jd_match:.0f} × 0.15 = {jd_match*.15:.1f}",
        f"Completeness 5%: {completeness:.0f} × 0.05 = {completeness*.05:.1f}"
    ]
    return {"overall": overall, "skills": skills, "experience": experience, "projects": projects, "education": education, "jd_match": jd_match, "completeness": completeness, "matched": matched, "missing": missing, "required": required, "preferred": preferred, "required_matched": required_matched, "preferred_matched": preferred_matched, "strengths": strengths, "gaps": gaps, "recommendation": rec, "confidence": confidence, "explanation": explanation, "project_matches": project_matches}


def bar(value, width=12):
    filled = round(max(0, min(100, value)) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def courses(missing):
    out = []
    for skill in missing:
        if skill in COURSES and COURSES[skill] not in out:
            out.append(COURSES[skill])
        if len(out) >= 4: break
    return out


def format_result(candidate, r, rank=None, total=None):
    lines = [
        "━━━━━━━━━━━━━━━━━━━━", "🤖 RESUME INSIGHT", "━━━━━━━━━━━━━━━━━━━━", "",
        f"👤 {candidate}",
        (f"🏆 RANK #{rank}/{total}" if rank and total else ""),
        f"🎯 OVERALL MATCH: {r['overall']:.1f}/100",
        f"📌 {r['recommendation']}", f"🔎 Evidence Confidence: {r['confidence']}", "",
        "📊 MATCH BREAKDOWN", "",
        f"Skills       {bar(r['skills'])} {r['skills']:.0f}%",
        f"Experience   {bar(r['experience'])} {r['experience']:.0f}%",
        f"Projects     {bar(r['projects'])} {r['projects']:.0f}%",
        f"Education    {bar(r['education'])} {r['education']:.0f}%",
        f"JD Match     {bar(r['jd_match'])} {r['jd_match']:.0f}%",
        f"Completeness {bar(r['completeness'])} {r['completeness']:.0f}%", "",
        "💻 SKILL CHECK"
    ]
    for s in r["required"][:10]: lines.append(f"{'✅' if s in r['required_matched'] else '❌'} {s} — REQUIRED")
    for s in r["preferred"][:8]: lines.append(f"{'🟢' if s in r['preferred_matched'] else '⚪'} {s} — PREFERRED")
    lines += ["", "💪 STRENGTHS"] + [f"• {x}" for x in r["strengths"][:3]]
    lines += ["", "⚠️ GAPS"] + [f"• {x}" for x in r["gaps"][:4]]
    lines += ["", "🧮 SCORE EXPLANATION"] + [f"• {x}" for x in r["explanation"]]
    recs = courses(r["missing"])
    if recs:
        lines += ["", "🎓 LEARNING RECOMMENDATIONS"] + [f"• {n}: {u}" for n, u in recs]
    lines += ["", "📌 FINAL VERDICT", r["recommendation"], "━━━━━━━━━━━━━━━━━━━━"]
    return "\n".join(x for x in lines if x != "")


def comparison_chart(results):
    from PIL import Image, ImageDraw, ImageFont
    W, H = 900, 120 + 95 * len(results)
    image = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    small = ImageFont.load_default(size=18)
    draw.text((35, 25), "RESUME MATCH COMPARISON", fill="black", font=font)
    for i, (name, r) in enumerate(results):
        y = 95 + i * 95
        draw.text((35, y), f"#{i+1} {name[:28]}", fill="black", font=small)
        x, bw = 300, 500
        draw.rectangle((x, y, x+bw, y+30), outline="black", width=2)
        fill = int(bw * r["overall"] / 100)
        if fill: draw.rectangle((x, y, x+fill, y+30), fill="black")
        draw.text((815, y+5), f"{r['overall']:.0f}%", fill="black", font=small)
    out = io.BytesIO(); image.save(out, format="PNG"); return out.getvalue()


async def send_message(chat_id, text):
    if not settings.telegram_bot_token: return False
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage", json={"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True})
            if r.status_code != 200:
                logger.error(f"Telegram send status={r.status_code}")
            return r.status_code == 200
    except Exception as exc:
        logger.error(f"Telegram send failed: {type(exc).__name__}")
        return False


async def send_photo(chat_id, data, caption=""):
    if not settings.telegram_bot_token: return False
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto", data={"chat_id": chat_id, "caption": caption[:1024]}, files={"photo": ("comparison.png", data, "image/png")})
            if r.status_code != 200:
                logger.error(f"Telegram photo status={r.status_code}")
            return r.status_code == 200
    except Exception as exc:
        logger.error(f"Telegram photo failed: {type(exc).__name__}")
        return False


async def download_file(file_id):
    if not settings.telegram_bot_token: return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            meta = await client.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile", params={"file_id": file_id})
            meta.raise_for_status()
            result = meta.json().get("result", {})
            path = result.get("file_path")
            if not path: return None
            r = await client.get(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{path}")
            r.raise_for_status()
            return r.content
    except Exception as exc:
        logger.error(f"Telegram download failed: {type(exc).__name__}")
        return None


def reset_session(session):
    session.update({"state": "idle", "jd": "", "resumes": [], "updated": datetime.utcnow()})


def is_command(text, command):
    return text.lower() == command or text.lower().startswith(command + " ")


async def handle_jd_document(chat_id, document, session):
    filename = document.get("file_name", "document.pdf")
    if not filename.lower().endswith((".pdf", ".docx")):
        await send_message(chat_id, "❌ I need the Job Description as text, PDF, or DOCX.\n\n📋 Send a JD file (.pdf/.docx) or paste the JD text.")
        return
    size = int(document.get("file_size", 0) or 0)
    if size > MAX_FILE_SIZE:
        await send_message(chat_id, "❌ JD file is too large. Maximum size is 10 MB.")
        return
    await send_message(chat_id, "🔎 I received the file. Checking whether it is a valid Job Description...")
    data = await download_file(document.get("file_id"))
    if not data:
        await send_message(chat_id, "❌ I could not download that file. Please try again.")
        return
    if len(data) > MAX_FILE_SIZE:
        await send_message(chat_id, "❌ JD file is too large. Maximum size is 10 MB.")
        return
    try:
        text = extract_document_text(data, filename)
        valid, reason = validate_jd(text)
        if not valid:
            await send_message(chat_id, "❌ This document does not look like a valid Job Description.\n\n" + reason + "\n\n📋 Please send the actual JD.")
            return
        session["jd"], session["state"], session["updated"] = text, "awaiting_resumes", datetime.utcnow()
        required, preferred = extract_required_preferred_skills(text)
        await send_message(chat_id, "✅ Job Description accepted from file.\n\n🎯 Required: " + (", ".join(required[:15]) if required else "None detected") + "\n🟢 Preferred: " + (", ".join(preferred[:10]) if preferred else "None detected") + "\n\n📎 Upload up to 10 PDF/DOCX resumes, then send /screen.")
    except Exception as exc:
        logger.error(f"JD file parsing failed: {type(exc).__name__}")
        await send_message(chat_id, "❌ I could not read this JD file. If it is scanned/image-only, please paste the JD text instead.")


@router.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    message = update.get("message") or update.get("edited_message")
    if not message or not message.get("chat") or not message.get("from"):
        return {"ok": True}
    chat_id, user_id = str(message["chat"]["id"]), str(message["from"]["id"])
    text = (message.get("text") or "").strip()
    document = message.get("document")
    session = session_for(user_id)
    session["updated"] = datetime.utcnow()

    if is_command(text, "/start") or is_command(text, "/help"):
        await send_message(chat_id, "👋 Resume Screening Bot\n\n/analyze — start screening\n/screen — rank uploaded resumes\n/reset — start over\n/help — show help\n\n📊 Validates JD/resumes, detects required vs preferred skills, scores candidates, ranks them and explains the score.")
        return {"ok": True}
    if is_command(text, "/reset"):
        reset_session(session)
        await send_message(chat_id, "✅ Reset complete.\n\nUse /analyze to start a new screening.")
        return {"ok": True}
    if is_command(text, "/analyze"):
        reset_session(session)
        session["state"] = "awaiting_jd"
        await send_message(chat_id, "📋 STEP 1/2 — Job Description\n\nPaste the complete JD here, or send a PDF/DOCX JD.\n\n💡 If you accidentally send a resume here, I will tell you instead of silently ignoring it.")
        return {"ok": True}

    if session["state"] == "awaiting_jd":
        if document:
            await handle_jd_document(chat_id, document, session)
            return {"ok": True}
        if text:
            if text.startswith("/"):
                await send_message(chat_id, "📋 I am waiting for the Job Description.\n\nPaste the JD text or send a PDF/DOCX file. Use /reset to start over.")
                return {"ok": True}
            valid, reason = validate_jd(text)
            if not valid:
                await send_message(chat_id, "❌ INVALID JOB DESCRIPTION\n\n" + reason + "\n\n📋 Please send the actual JD again.")
                return {"ok": True}
            session["jd"], session["state"] = text, "awaiting_resumes"
            required, preferred = extract_required_preferred_skills(text)
            await send_message(chat_id, "✅ JOB DESCRIPTION ACCEPTED\n\n🎯 Required: " + (", ".join(required[:15]) if required else "None detected") + "\n🟢 Preferred: " + (", ".join(preferred[:10]) if preferred else "None detected") + "\n\n📎 STEP 2/2 — Upload up to 10 PDF/DOCX resumes.\nWhen finished, send /screen.")
            return {"ok": True}
        await send_message(chat_id, "📋 I am waiting for the Job Description. Please paste the JD or send a PDF/DOCX file.")
        return {"ok": True}

    if session["state"] == "awaiting_resumes":
        if document:
            if len(session["resumes"]) >= MAX_RESUMES:
                await send_message(chat_id, f"❌ Maximum {MAX_RESUMES} resumes reached.\n\nSend /screen to rank them or /reset to start again.")
                return {"ok": True}
            filename = document.get("file_name", "resume.pdf")
            if not filename.lower().endswith((".pdf", ".docx")):
                await send_message(chat_id, "❌ Unsupported file type.\n\nPlease upload a PDF or DOCX resume.")
                return {"ok": True}
            size = int(document.get("file_size", 0) or 0)
            if size > MAX_FILE_SIZE:
                await send_message(chat_id, "❌ Resume is too large. Maximum file size is 10 MB.")
                return {"ok": True}
            await send_message(chat_id, f"🔎 Checking {filename}...")
            data = await download_file(document.get("file_id"))
            if not data:
                await send_message(chat_id, "❌ I could not download this resume. Please try again.")
                return {"ok": True}
            if len(data) > MAX_FILE_SIZE:
                await send_message(chat_id, "❌ Resume is too large. Maximum file size is 10 MB.")
                return {"ok": True}
            file_hash = hashlib.sha256(data).hexdigest()
            if any(r.get("hash") == file_hash for r in session["resumes"]):
                await send_message(chat_id, "⚠️ Duplicate resume detected.\n\nThis exact file was already uploaded. Please send a different resume.")
                return {"ok": True}
            try:
                resume_text = extract_document_text(data, filename)
                valid, reason = validate_resume(resume_text, filename)
                if not valid:
                    await send_message(chat_id, "❌ RESUME REJECTED\n\n" + reason)
                    return {"ok": True}
                candidate = extract_candidate_name(resume_text, filename)
                session["resumes"].append({"name": candidate, "text": resume_text, "hash": file_hash})
                await send_message(chat_id, f"✅ Resume accepted: {candidate}\n💻 Skills found: {len(extract_skills(resume_text))}\n📎 {len(session['resumes'])}/{MAX_RESUMES} resumes uploaded\n\nSend another resume or /screen.")
            except Exception as exc:
                logger.error(f"Resume parsing failed: {type(exc).__name__}")
                await send_message(chat_id, "❌ I could not read this resume.\n\nTry a text-based PDF/DOCX under 40 pages, or upload another resume.")
            return {"ok": True}
        if text.startswith("/") and not is_command(text, "/screen"):
            await send_message(chat_id, "📎 I am waiting for resumes. Upload PDF/DOCX files, or send /screen when finished.\n\nUse /reset to start over.")
            return {"ok": True}
        if is_command(text, "/screen"):
            if not session["resumes"]:
                await send_message(chat_id, "❌ No valid resumes uploaded yet.\n\nPlease upload at least one PDF/DOCX resume before /screen.")
                return {"ok": True}
            await send_message(chat_id, f"⏳ Screening {len(session['resumes'])} resume(s)...\n\nI am calculating the match score, evidence and ranking.")
            try:
                results = [(r["name"], score_resume(session["jd"], r["text"])) for r in session["resumes"]]
                results.sort(key=lambda x: x[1]["overall"], reverse=True)
                if len(results) > 1:
                    try:
                        await send_photo(chat_id, comparison_chart(results), "📊 Candidate comparison — ranked by overall match")
                    except Exception as exc:
                        logger.error(f"Chart generation failed: {type(exc).__name__}")
                for i, (candidate, result) in enumerate(results, 1):
                    await send_message(chat_id, format_result(candidate, result, i if len(results) > 1 else None, len(results) if len(results) > 1 else None))
                await send_message(chat_id, "✅ Screening complete.\n\nUse /analyze for a new JD or /reset to clear the session.")
            except Exception as exc:
                logger.error(f"Screening failed: {type(exc).__name__}")
                await send_message(chat_id, "❌ Screening could not be completed.\n\nPlease try /reset and start again with a valid JD and resumes.")
            reset_session(session)
            return {"ok": True}
        if text:
            await send_message(chat_id, "📎 Resume upload stage\n\nPlease upload PDF/DOCX resumes. When finished, send /screen.\n\nIf you meant to change the JD, use /reset and /analyze.")
            return {"ok": True}
        await send_message(chat_id, "📎 Please upload a PDF/DOCX resume or send /screen.")
        return {"ok": True}

    if session["state"] == "idle":
        await send_message(chat_id, "👋 No active screening.\n\nUse /analyze to start, then send the JD and upload resumes.")
    return {"ok": True}
