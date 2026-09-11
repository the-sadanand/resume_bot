"""Rich Google Chat response adapter for the resume screening bot."""

from fastapi import APIRouter, Request

from app.integrations.multichannel import (
    MAX_RESUMES,
    add_resume,
    google_chat_download,
    help_text,
    reset_session,
    score_resume,
    session_for,
    validate_jd,
    validate_resume,
)

router = APIRouter(prefix="/integrations", tags=["Google Chat Rich"])


def bar(value: float, width: int = 16) -> str:
    filled = round(max(0, min(100, value)) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def rich_screen(session):
    if not session["jd"]:
        return {"text": "Please send the Job Description first."}
    if not session["resumes"]:
        return {"text": "Please upload at least one resume first."}

    ranked = []
    for item in session["resumes"]:
        result = score_resume(session["jd"], item["text"])
        ranked.append((item["filename"], result))
    ranked.sort(key=lambda x: x[1]["overall"], reverse=True)

    top = ranked[0][1]
    top_name = ranked[0][0]

    widgets = [
        {"textParagraph": {"text": f"<b>👤 {top_name}</b><br>🏆 RANK #1/{len(ranked)}<br>🎯 <b>OVERALL MATCH: {top['overall']:.1f}/100</b><br>📌 {top['recommendation']}<br>🔎 Evidence Confidence: {top['confidence']}"}},
        {"textParagraph": {"text": "<b>📊 MATCH BREAKDOWN</b>"}},
    ]

    for label, key in [
        ("Skills", "skills"),
        ("Experience", "experience"),
        ("Projects", "projects"),
        ("Education", "education"),
        ("JD Match", "jd_match"),
        ("Completeness", "completeness"),
    ]:
        value = top[key]
        widgets.append({"textParagraph": {"text": f"<b>{label}</b> {bar(value)} {value:.0f}%"}})

    widgets.append({"textParagraph": {"text": "<b>💻 SKILL CHECK</b>"}})
    for skill in top["required"][:10]:
        mark = "✅" if skill in top["required_matched"] else "❌"
        widgets.append({"textParagraph": {"text": f"{mark} {skill} — REQUIRED"}})
    for skill in top["preferred"][:8]:
        mark = "🟢" if skill in top["preferred_matched"] else "⚪"
        widgets.append({"textParagraph": {"text": f"{mark} {skill} — PREFERRED"}})

    widgets.append({"textParagraph": {"text": "<b>💪 STRENGTHS</b>"}})
    for item in top["strengths"][:3]:
        widgets.append({"textParagraph": {"text": f"• {item}"}})

    widgets.append({"textParagraph": {"text": "<b>⚠️ GAPS</b>"}})
    for item in top["gaps"][:4]:
        widgets.append({"textParagraph": {"text": f"• {item}"}})

    widgets.append({"textParagraph": {"text": "<b>🧮 SCORE EXPLANATION</b>"}})
    for item in top["explanation"]:
        widgets.append({"textParagraph": {"text": f"• {item}"}})

    widgets.append({"textParagraph": {"text": f"<b>📌 FINAL VERDICT: {top['recommendation']}</b>"}})

    if len(ranked) > 1:
        ranking_widgets = []
        for idx, (name, result) in enumerate(ranked, 1):
            ranking_widgets.append({"textParagraph": {"text": f"<b>#{idx} {name}</b> — {result['overall']:.1f}/100 {result['recommendation']}<br>{bar(result['overall'])}"}})
        return {
            "text": "🏆 Resume screening completed.",
            "cardsV2": [
                {"cardId": "resume-insight", "card": {"header": {"title": "🤖 RESUME INSIGHT", "subtitle": "Top candidate"}, "sections": [{"widgets": widgets}]}},
                {"cardId": "resume-ranking", "card": {"header": {"title": "📊 CANDIDATE COMPARISON", "subtitle": "Ranked by overall match"}, "sections": [{"widgets": ranking_widgets}]}} ,
            ],
        }

    return {
        "text": "🤖 Resume screening completed.",
        "cardsV2": [
            {"cardId": "resume-insight", "card": {"header": {"title": "🤖 RESUME INSIGHT", "subtitle": "Detailed screening result"}, "sections": [{"widgets": widgets}]}}
        ],
    }


@router.post("/google-chat/events")
async def google_chat_rich_events(request: Request):
    event = await request.json()
    user = event.get("user", {})
    user_id = user.get("name") or user.get("displayName") or "unknown"
    space = event.get("space", {}).get("name", "unknown")
    key = f"google-chat:{space}:{user_id}"
    session = session_for(key)
    message = event.get("message", {})
    text = (message.get("text") or "").strip()
    low = text.lower()

    if low in {"/start", "/help"}:
        return {"text": help_text("google-chat")}
    if low == "/analyze":
        reset_session(key)
        return {"text": "✅ Screening session started. Send the Job Description as a message."}
    if low == "/reset":
        reset_session(key)
        return {"text": "🧹 Session reset."}
    if low == "/screen":
        return rich_screen(session)

    attachments = message.get("attachment", []) or message.get("attachments", [])
    if attachments:
        if not session["jd"]:
            return {"text": "❌ Send the Job Description first."}
        messages = []
        for attachment in attachments[:MAX_RESUMES]:
            filename = attachment.get("contentName") or attachment.get("content_name") or "resume.pdf"
            if not filename.lower().endswith((".pdf", ".docx")):
                messages.append(f"❌ {filename}: only PDF and DOCX are supported.")
                continue
            ref = attachment.get("attachmentDataRef") or attachment.get("attachment_data_ref") or {}
            resource_name = ref.get("resourceName") or ref.get("resource_name")
            if not resource_name:
                messages.append(f"❌ {filename}: Google Chat did not provide downloadable attachment data.")
                continue
            try:
                data = google_chat_download(resource_name)
                ok, result = add_resume(session, filename, data)
                messages.append(("✅ " if ok else "❌ ") + result)
            except Exception as exc:
                messages.append(f"❌ {filename}: could not process ({type(exc).__name__}).")
        return {"text": "\n".join(messages)}

    if text:
        if not session["jd"]:
            ok, reason = validate_jd(text)
            if ok:
                session["jd"] = text
                session["state"] = "awaiting_resumes"
                return {"text": "✅ Job Description saved. Upload PDF/DOCX resumes, then send `/screen`."}
            return {"text": f"❌ {reason}"}
        return {"text": "Please upload a PDF/DOCX resume, or send `/screen` when finished."}

    return {"text": "Send `/analyze` to start, or `/help` for instructions."}
