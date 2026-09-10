"""Telegram-only resume screening showcase with validation and transparent scoring."""
import hashlib
import io
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/integrations/telegram", tags=["Telegram"])
settings = get_settings()
logger = get_logger(__name__)

MAX_RESUMES = 10
MAX_FILE_SIZE = 10 * 1024 * 1024
MIN_JD_LENGTH = 80
MIN_RESUME_TEXT = 120

SKILLS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "fastapi", "django", "flask", "react", "angular", "node.js", "nodejs",
    "docker", "kubernetes", "aws", "azure", "gcp", "git", "linux", "mysql",
    "postgresql", "mongodb", "redis", "sql", "nosql", "tensorflow", "pytorch",
    "scikit-learn", "pandas", "numpy", "keras", "machine learning", "deep learning",
    "nlp", "computer vision", "data science", "rest api", "graphql", "microservices",
    "celery", "kafka", "spark"
]
AMBIGUOUS_SKILLS = {"go", "r", "c"}

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

SESSIONS: dict[str, dict] = {}


def session_for(uid):
    return SESSIONS.setdefault(uid, {"state": "idle", "jd": "", "resumes": []})


def normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def contains_skill(text, skill):
    text, skill = normalize(text), skill.lower()
    if skill in AMBIGUOUS_SKILLS:
        if skill == "go":
            return bool(re.search(r"\b(?:golang|go\s+(?:programming|development|developer|language|modules|goroutines))\b", text))
        return False
    if " " in skill or "." in skill or "+" in skill or "#" in skill:
        return skill in text
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", text))


def extract_skills(text):
    return [s for s in SKILLS if contains_skill(text, s)]


def extract_years(text):
    text = normalize(text)
    values = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", text)]
    values += [float(x) / 12 for x in re.findall(r"(\d+)\s*\+?\s*months?", text)]
    return max(values, default=0.0)


def extract_required_preferred_skills(jd):
    required = []
    preferred = []
    lines = jd.splitlines()
    mode = "required"
    for line in lines:
        low = line.lower()
        if any(x in low for x in ["nice to have", "preferred", "bonus", "optional", "good to have"]):
            mode = "preferred"
        elif any(x in low for x in ["required", "must have", "qualifications", "requirements"]):
            mode = "required"
        for skill in extract_skills(line):
            if mode == "preferred" and skill not in preferred:
                preferred.append(skill)
            elif skill not in required:
                required.append(skill)
    all_skills = extract_skills(jd)
    if not required:
        required = [s for s in all_skills if s not in preferred]
    return required, preferred


def validate_jd(text):
    clean = text.strip()
    if len(clean) < MIN_JD_LENGTH:
        return False, "The Job Description is too short. Please send the complete JD with role, responsibilities, skills or qualifications."
    low = normalize(clean)
    role_signals = [
        "developer", "engineer", "analyst", "designer", "manager", "intern", "consultant",
        "scientist", "architect", "specialist", "administrator", "responsibilities", "qualifications",
        "requirements", "experience", "skills", "job description", "role"
    ]
    signal_count = sum(1 for x in role_signals if re.search(r"\b" + re.escape(x) + r"\b", low))
    skills = extract_skills(clean)
    if signal_count < 2 and not skills:
        return False, "This does not look like a valid Job Description. Include a job role plus responsibilities, requirements, experience or skills."
    if not skills and signal_count < 3:
        return False, "I could not identify enough job requirements. Please include at least one relevant skill and more role details."
    return True, ""


def extract_candidate_name(text, filename):
    blocked = ["resume", "curriculum", "email", "phone", "linkedin", "github", "profile", "objective", "summary"]
    for line in [x.strip() for x in text.splitlines() if x.strip()][:12]:
        low = line.lower()
        if 2 <= len(line.split()) <= 5 and len(line) < 60 and not any(x in low for x in blocked) and not any(c.isdigit() for c in line) and "@" not in line:
            return line
    return re.sub(r"[_-]+", " ", filename.rsplit(".", 1)[0]).strip() or "Candidate"


def extract_resume_text(data, filename):
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
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
    raise ValueError("Only PDF and DOCX files are supported")


def validate_resume(text, filename):
    clean = text.strip()
    if len(clean) < MIN_RESUME_TEXT:
        return False, "This resume contains too little readable text. Please upload a text-based PDF or DOCX resume."
    low = normalize(clean)
    signals = sum([
        bool(re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)),
        bool(re.search(r"\b(?:education|degree|b\.tech|btech|bachelor|m\.tech|master)\b", low)),
        bool(re.search(r"\b(?:experience|employment|work history|professional experience)\b", low)),
        bool(extract_skills(clean)),
        len(clean.split()) >= 80
    ])
    if signals < 3:
        return False, "This file does not look like a complete resume. Please upload a resume containing contact, education, experience, skills or project information."
    return True, ""


def degree_level(text):
    low = normalize(text)
    if any(x in low for x in ["ph.d", "phd", "doctorate"]): return 5
    if any(x in low for x in ["m.tech", "mtech", "m.e", "master", "mba", "mca"]): return 4
    if any(x in low for x in ["b.tech", "btech", "b.e", "bachelor", "bsc", "bca"]): return 3
    if any(x in low for x in ["diploma", "associate"]): return 2
    return 0


def education_score(jd, resume):
    jd_level, resume_level = degree_level(jd), degree_level(resume)
    if not jd_level:
        return 100.0 if resume_level else 60.0, "No specific degree requirement detected"
    if resume_level >= jd_level:
        return 100.0, "Education level meets the JD"
    if resume_level == jd_level - 1:
        return 55.0, "Education is below the stated JD level"
    return 25.0, "Required education level not clearly found"


def project_score(jd, resume):
    jd_skills = set(extract_skills(jd))
    if not jd_skills:
        return 60.0, []
    lines = resume.splitlines()
    project_lines = []
    in_project_section = False
    for line in lines:
        low = line.lower().strip()
        if any(x in low for x in ["projects", "project experience", "personal projects", "academic projects"]):
            in_project_section = True
            continue
        if in_project_section and any(x in low for x in ["experience", "education", "certification", "skills", "achievements"]):
            in_project_section = False
        if in_project_section and line.strip():
            project_lines.append(line)
    project_text = " ".join(project_lines) if project_lines else resume
    project_skills = set(extract_skills(project_text))
    overlap = len(jd_skills & project_skills) / len(jd_skills) if jd_skills else 0
    evidence = sum(bool(re.search(r"\b(?:built|developed|implemented|created|deployed|designed)\b", x, re.I)) for x in project_lines)
    score = min(100.0, 35.0 + overlap * 55.0 + min(evidence, 2) * 5.0)
    return score, sorted(jd_skills & project_skills)


def score_resume(jd, resume):
    jd_skills = extract_skills(jd)
    resume_skills = extract_skills(resume)
    required, preferred = extract_required_preferred_skills(jd)
    matched = [s for s in jd_skills if s in resume_skills]
    missing = [s for s in jd_skills if s not in resume_skills]

    skills = len(matched) / len(jd_skills) * 100 if jd_skills else 0.0
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
        bool(re.search(r"\b(?:experience|employment|work history)\b", resume, re.I)),
        bool(re.search(r"\b(?:education|degree|b\.tech|btech|bachelor)\b", resume, re.I)),
        bool(resume_skills),
        bool(re.search(r"\b(?:project|projects)\b", resume, re.I))
    ]) / 5 * 100

    overall = skills * .35 + experience * .20 + projects * .15 + education * .10 + jd_match * .15 + completeness * .05
    rec = "STRONG MATCH" if overall >= 85 else "GOOD MATCH" if overall >= 70 else "MODERATE MATCH" if overall >= 55 else "WEAK MATCH"

    evidence_count = sum([
        bool(matched),
        bool(resume_years),
        bool(project_matches),
        bool(resume_skills),
        completeness >= 60
    ])
    confidence = "HIGH" if evidence_count >= 4 and completeness >= 80 else "MEDIUM" if evidence_count >= 2 else "LOW"

    strengths, gaps = [], []
    if matched: strengths.append("Skills matched: " + ", ".join(matched[:6]))
    if required_matched: strengths.append("Required skills matched: " + ", ".join(required_matched[:5]))
    if project_matches: strengths.append("Relevant project evidence: " + ", ".join(project_matches[:5]))
    if required_years and resume_years >= required_years: strengths.append("Experience requirement is met")
    if missing: gaps.append("Missing skills: " + ", ".join(missing[:6]))
    if required and len(required_matched) < len(required): gaps.append("Required skills missing: " + ", ".join([s for s in required if s not in resume_skills][:6]))
    if preferred and len(preferred_matched) < len(preferred): gaps.append("Preferred skills missing: " + ", ".join([s for s in preferred if s not in resume_skills][:5]))
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
    return {
        "overall": overall, "skills": skills, "experience": experience, "projects": projects,
        "education": education, "jd_match": jd_match, "completeness": completeness,
        "matched": matched, "missing": missing, "required": required, "preferred": preferred,
        "required_matched": required_matched, "preferred_matched": preferred_matched,
        "strengths": strengths, "gaps": gaps, "recommendation": rec,
        "confidence": confidence, "explanation": explanation, "project_matches": project_matches
    }


def bar(value, width=12):
    filled = round(max(0, min(100, value)) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def courses(missing):
    out = []
    for skill in missing:
        if skill in COURSES and COURSES[skill] not in out:
            out.append(COURSES[skill])
        if len(out) >= 4:
            break
    return out


def format_result(candidate, r):
    lines = [
        "━━━━━━━━━━━━━━━━━━━━", "🤖 RESUME INSIGHT", "━━━━━━━━━━━━━━━━━━━━", "",
        f"👤 {candidate}", f"🎯 OVERALL MATCH: {r['overall']:.1f}/100",
        f"📌 {r['recommendation']}", f"🔎 Evidence Confidence: {r['confidence']}", "",
        "📊 CATEGORY STRENGTH", "",
        f"Skills       {bar(r['skills'])} {r['skills']:.0f}%",
        f"Experience   {bar(r['experience'])} {r['experience']:.0f}%",
        f"Projects     {bar(r['projects'])} {r['projects']:.0f}%",
        f"Education    {bar(r['education'])} {r['education']:.0f}%",
        f"JD Match     {bar(r['jd_match'])} {r['jd_match']:.0f}%",
        f"Completeness {bar(r['completeness'])} {r['completeness']:.0f}%", "",
        "💻 SKILL STRENGTH", ""
    ]
    for s in r["required_matched"][:8]: lines.append(f"✅ {s:<18} {bar(100)}  REQUIRED ✓")
    for s in r["required"]:
        if s not in r["required_matched"][:8]: lines.append(f"❌ {s:<18} {bar(0)}  REQUIRED ✗")
    for s in r["preferred_matched"][:6]: lines.append(f"🟢 {s:<18} {bar(100)}  PREFERRED ✓")
    for s in r["preferred"]:
        if s not in r["preferred_matched"][:6]: lines.append(f"⚪ {s:<18} {bar(0)}  PREFERRED ✗")
    lines += ["", "💪 STRENGTHS"] + [f"• {x}" for x in r["strengths"][:3]]
    lines += ["", "⚠️ GAPS"] + [f"• {x}" for x in r["gaps"][:4]]
    lines += ["", "🧮 SCORE EXPLANATION"] + [f"• {x}" for x in r["explanation"]]
    recs = courses(r["missing"])
    if recs:
        lines += ["", "🎓 RECOMMENDED LEARNING"] + [f"• {n}: {u}" for n, u in recs]
    lines += ["", "📌 FINAL VERDICT", r["recommendation"], "━━━━━━━━━━━━━━━━━━━━"]
    return "\n".join(lines)


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
            r = await client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage", json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
            return r.status_code == 200
    except Exception as exc:
        logger.error(f"Telegram send failed: {type(exc).__name__}"); return False


async def send_photo(chat_id, data, caption=""):
    if not settings.telegram_bot_token: return False
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto", data={"chat_id": chat_id, "caption": caption}, files={"photo": ("comparison.png", data, "image/png")})
            return r.status_code == 200
    except Exception as exc:
        logger.error(f"Telegram photo failed: {type(exc).__name__}"); return False


async def download_file(file_id):
    if not settings.telegram_bot_token: return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            meta = await client.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile", params={"file_id": file_id})
            meta.raise_for_status(); path = meta.json()["result"]["file_path"]
            r = await client.get(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{path}")
            r.raise_for_status(); return r.content
    except Exception as exc:
        logger.error(f"Telegram download failed: {type(exc).__name__}"); return None


@router.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    message = update.get("message") or update.get("edited_message")
    if not message: return {"ok": True}
    chat_id, user_id = str(message["chat"]["id"]), str(message["from"]["id"])
    text, document = message.get("text", "").strip(), message.get("document")
    session = session_for(user_id)

    if text.startswith("/start") or text.startswith("/help"):
        await send_message(chat_id, "👋 Resume Screening Bot\n\n/analyze - start screening\n/screen - rank uploaded resumes\n/reset - start over\n\n📊 Includes validation, ranking, comparison graph, required/preferred skills, score explanation, confidence and course recommendations.")
        return {"ok": True}
    if text.startswith("/reset"):
        session.update({"state": "idle", "jd": "", "resumes": []}); await send_message(chat_id, "✅ Reset complete. Use /analyze to start."); return {"ok": True}
    if text.startswith("/analyze"):
        session.update({"state": "awaiting_jd", "jd": "", "resumes": []}); await send_message(chat_id, "📋 Send the complete Job Description text now.\n\n⚠️ Please send the JD as text, not as a resume file."); return {"ok": True}

    # A document is never a valid JD input. Handle it explicitly so the bot
    # does not silently ignore a PDF/DOCX resume sent at the wrong step.
    if session["state"] == "awaiting_jd" and document:
        filename = document.get("file_name", "document")
        if filename.lower().endswith((".pdf", ".docx")):
            await send_message(chat_id, "❌ You are currently at the Job Description step.\n\nThat file looks like a resume/document, but I need the Job Description text first.\n\n📋 Please paste or type the JD here, then I will ask you to upload resumes.")
        else:
            await send_message(chat_id, "❌ I am waiting for the Job Description text.\n\nPlease paste the JD here instead of uploading a file.")
        return {"ok": True}

    if session["state"] == "awaiting_jd" and text and not text.startswith("/"):
        valid, reason = validate_jd(text)
        if not valid:
            await send_message(chat_id, "❌ Invalid Job Description\n\n" + reason + "\n\nPlease send the JD again.")
            return {"ok": True}
        session["jd"], session["state"] = text, "awaiting_resumes"
        required, preferred = extract_required_preferred_skills(text)
        await send_message(chat_id, "✅ Job Description validated\n\n🎯 Required: " + (", ".join(required[:15]) if required else "None detected") + "\n🟢 Preferred: " + (", ".join(preferred[:10]) if preferred else "None detected") + "\n\n📎 Upload up to 10 PDF/DOCX resumes, then send /screen.")
        return {"ok": True}

    if session["state"] == "awaiting_resumes":
        if document:
            if len(session["resumes"]) >= MAX_RESUMES:
                await send_message(chat_id, f"❌ Maximum {MAX_RESUMES} resumes per screening. Send /screen or /reset."); return {"ok": True}
            filename = document.get("file_name", "resume.pdf")
            if not filename.lower().endswith((".pdf", ".docx")):
                await send_message(chat_id, "❌ Only PDF and DOCX files are supported."); return {"ok": True}
            file_size = int(document.get("file_size", 0) or 0)
            if file_size > MAX_FILE_SIZE:
                await send_message(chat_id, "❌ Resume is too large. Maximum file size is 10 MB."); return {"ok": True}
            data = await download_file(document["file_id"])
            if not data:
                await send_message(chat_id, "❌ Could not download the resume. Try again."); return {"ok": True}
            if len(data) > MAX_FILE_SIZE:
                await send_message(chat_id, "❌ Resume is too large. Maximum file size is 10 MB."); return {"ok": True}
            file_hash = hashlib.sha256(data).hexdigest()
            if any(r.get("hash") == file_hash for r in session["resumes"]):
                await send_message(chat_id, "⚠️ This resume was already uploaded. Please send a different resume."); return {"ok": True}
            try:
                resume_text = extract_resume_text(data, filename)
                valid, reason = validate_resume(resume_text, filename)
                if not valid:
                    await send_message(chat_id, "❌ Resume rejected\n\n" + reason); return {"ok": True}
                candidate = extract_candidate_name(resume_text, filename)
                session["resumes"].append({"name": candidate, "text": resume_text, "hash": file_hash})
                await send_message(chat_id, f"✅ Resume accepted: {candidate}\n💻 Skills found: {len(extract_skills(resume_text))}\n📊 {len(session['resumes'])}/{MAX_RESUMES} resumes uploaded\n\nSend another resume or /screen.")
            except Exception as exc:
                logger.error(f"Resume parsing failed: {type(exc).__name__}"); await send_message(chat_id, "❌ Could not read this resume. Try another text-based PDF/DOCX.")
            return {"ok": True}
        if text.startswith("/screen"):
            if not session["resumes"]:
                await send_message(chat_id, "❌ Upload at least one valid resume first."); return {"ok": True}
            await send_message(chat_id, f"⏳ Screening {len(session['resumes'])} resume(s)...")
            results = [(r["name"], score_resume(session["jd"], r["text"])) for r in session["resumes"]]
            results.sort(key=lambda x: x[1]["overall"], reverse=True)
            if len(results) > 1:
                try: await send_photo(chat_id, comparison_chart(results), "📊 Candidate comparison — ranked by overall match")
                except Exception as exc: logger.error(f"Chart generation failed: {type(exc).__name__}")
            for i, (candidate, result) in enumerate(results, 1):
                await send_message(chat_id, (f"🏆 RANK #{i}\n\n" if len(results) > 1 else "") + format_result(candidate, result))
            session.update({"state": "idle", "jd": "", "resumes": []})
            return {"ok": True}

    if session["state"] == "idle":
        await send_message(chat_id, "Use /analyze to start resume screening.")
    return {"ok": True}
