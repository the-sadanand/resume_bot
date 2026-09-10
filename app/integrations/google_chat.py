"""
Google Chat Platform Adapter
Official Google Chat API integration.

Setup Requirements:
1. Google Cloud Project: https://console.cloud.google.com/
2. Enable Google Chat API
3. Create a Chat App in Google Cloud Console
4. Configure:
   - App name
   - App URL: https://your-domain.com/integrations/google-chat/webhook
   - Authentication: Bearer token or Service Account
5. For service account auth, download credentials JSON
   and set GOOGLE_APPLICATION_CREDENTIALS in .env

Documentation:
- Chat API: https://developers.google.com/chat/api
- Chat App: https://developers.google.com/chat/how-tos/apps-develop
- Webhooks: https://developers.google.com/chat/how-tos/webhooks

Local testing: Use ngrok for HTTPS tunnel + configure URL in GCP Console.

File Handling Limitation:
Google Chat does not support arbitrary file uploads to Chat App bots via direct API.
The recommended approach for the MVP is:
1. Accept JD text via chat message
2. For resumes: user shares a Google Drive link, OR
3. User copies resume text into the chat
This limitation is documented and a Drive integration can be added as a future improvement.
"""
import logging
import json
import hmac
import hashlib
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.storage.repositories import ConversationStateRepository, JobRepository, ResumeRepository
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/integrations/google-chat", tags=["Google Chat"])
logger = get_logger(__name__)
settings = get_settings()


def build_text_response(text: str) -> dict:
    """Build a simple Google Chat text response."""
    return {"text": text}


def build_card_response(title: str, sections: list[dict]) -> dict:
    """Build a Google Chat card response."""
    return {
        "cardsV2": [
            {
                "cardId": "screening_result",
                "card": {
                    "header": {"title": title},
                    "sections": sections,
                },
            }
        ]
    }


def build_screening_card(result_data: dict) -> dict:
    """Build a Google Chat card for a screening result."""
    score = result_data.get("overall_score", 0)
    name = result_data.get("candidate_name", "Unknown")
    recommendation = result_data.get("recommendation", "")

    widgets = [
        {"decoratedText": {"text": f"<b>Overall Score:</b> {score:.0f}/100"}},
        {"decoratedText": {"text": f"<b>Recommendation:</b> {recommendation}"}},
    ]

    section_scores = result_data.get("section_scores", {})
    if section_scores:
        score_text = (
            f"Skills: {section_scores.get('skills', 0):.0f} | "
            f"Experience: {section_scores.get('experience', 0):.0f} | "
            f"Projects: {section_scores.get('projects', 0):.0f}"
        )
        widgets.append({"decoratedText": {"text": f"<b>Scores:</b> {score_text}"}})

    matched = result_data.get("skill_match", {}).get("matched", [])
    if matched:
        widgets.append({"decoratedText": {"text": f"<b>Matched Skills:</b> {', '.join(matched[:5])}"}})

    missing = result_data.get("skill_match", {}).get("missing", [])
    if missing:
        widgets.append({"decoratedText": {"text": f"<b>Missing Skills:</b> {', '.join(missing[:3])}"}})

    widgets.append({"divider": {}})
    widgets.append({"decoratedText": {
        "text": "⚠️ AI-assisted tool. Not an autonomous hiring decision system."
    }})

    return build_card_response(
        title=f"Resume Screening: {name}",
        sections=[{"widgets": widgets}],
    )


@router.post("/webhook")
async def google_chat_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Google Chat webhook endpoint.
    Receives events from Google Chat and responds.

    Event types handled:
    - MESSAGE: User sent a message
    - ADDED_TO_SPACE: Bot added to a space
    - REMOVED_FROM_SPACE: Bot removed from a space
    """
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type")
    space = event.get("space", {})
    sender = event.get("user", {})
    user_id = sender.get("name", "unknown")  # e.g. "users/12345"

    if event_type == "ADDED_TO_SPACE":
        return build_text_response(
            "👋 Hello! I'm the Resume Screening Bot.\n\n"
            "I can help you screen resumes against a job description.\n\n"
            "Commands:\n"
            "• `@bot analyze` — Start screening\n"
            "• `@bot help` — Show instructions\n\n"
            "⚠️ AI-assisted tool. Not an autonomous hiring system."
        )

    if event_type == "REMOVED_FROM_SPACE":
        return {}  # Acknowledge

    if event_type != "MESSAGE":
        return build_text_response("Event received.")

    # Extract message text
    message = event.get("message", {})
    text = message.get("argumentText", message.get("text", "")).strip()
    text_lower = text.lower()

    state_repo = ConversationStateRepository(db)
    conv = state_repo.get_or_create("google_chat", user_id)
    current_state = conv.state

    # ── Commands ──
    if any(cmd in text_lower for cmd in ["analyze", "start", "help"]):
        state_repo.update("google_chat", user_id, state="awaiting_jd", job_id=None, resume_ids=[])
        return build_text_response(
            "📋 *Resume Screening Started*\n\n"
            "Please paste the *Job Description* text in your next message."
        )

    if "reset" in text_lower:
        state_repo.reset("google_chat", user_id)
        return build_text_response("✅ Conversation reset. Type 'analyze' to start again.")

    # ── State handling ──
    if current_state == "awaiting_jd" and text:
        from app.services.jd_parser import parse_job_description
        import uuid

        parsed_jd = parse_job_description(text)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        JobRepository(db).create(job_id, parsed_jd.job_title or "Unnamed", text, parsed_jd.model_dump())
        state_repo.update("google_chat", user_id, state="awaiting_resumes", job_id=job_id, resume_ids=[])

        return build_text_response(
            f"✅ Job Description received!\n"
            f"Role: {parsed_jd.job_title}\n"
            f"Required skills: {', '.join(parsed_jd.required_skills[:5])}\n\n"
            "📝 *Note:* Google Chat doesn't support direct file uploads to bots in this flow.\n"
            "Please paste the resume text in your next message and I'll analyze it.\n"
            "Type 'screen' after pasting resume text.\n\n"
            "Or use the REST API (/api/v1/resumes/upload) for full file upload support."
        )

    if current_state == "awaiting_resumes":
        if "screen" in text_lower:
            resume_ids = list(conv.resume_ids or [])
            if not resume_ids:
                return build_text_response("❌ No resumes processed yet. Please paste resume text first.")

            job_record = JobRepository(db).get(conv.job_id)
            resume_records = ResumeRepository(db).get_many(resume_ids)

            from app.services.scoring_engine import screen_resume
            from app.models.resume import ParsedResume
            from app.models.job import ParsedJobDescription
            from app.core.config import get_settings as _gs
            from app.services.ranking_service import rank_candidates
            from app.services.report_service import format_single_report, format_batch_report
            from app.models.screening import ScreeningResult, BatchScreeningResult

            jd = ParsedJobDescription(**job_record.parsed_data)
            s = _gs()

            if len(resume_ids) == 1:
                rr = resume_records[0]
                pd_data = dict(rr.parsed_data)
                pd_data["raw_text"] = ""
                resume = ParsedResume(**pd_data)
                section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)

                result_data = {
                    "overall_score": overall_score,
                    "candidate_name": resume.name,
                    "recommendation": s.get_score_category(overall_score),
                    "section_scores": section_scores.model_dump(),
                    "skill_match": skill_detail.model_dump(),
                }
                state_repo.reset("google_chat", user_id)
                return build_screening_card(result_data)
            else:
                candidate_results = []
                for rr in resume_records:
                    pd_data = dict(rr.parsed_data)
                    pd_data["raw_text"] = ""
                    resume = ParsedResume(**pd_data)
                    section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)
                    candidate_results.append({
                        "name": resume.name,
                        "analysis_id": f"gc_{rr.id}",
                        "overall_score": overall_score,
                        "section_scores": section_scores,
                        "skill_match": skill_detail,
                    })
                ranked = rank_candidates(candidate_results)
                from app.services.ranking_service import build_comparison_table
                from app.models.screening import BatchScreeningResult
                comparison_table = build_comparison_table(ranked)
                batch_result = BatchScreeningResult(
                    batch_id="gc_batch",
                    job_title=job_record.title,
                    total_candidates=len(ranked),
                    ranked_candidates=ranked,
                    comparison_table=comparison_table,
                )
                report = format_batch_report(batch_result, job_record.title)
                state_repo.reset("google_chat", user_id)
                return build_text_response(f"```\n{report[:3500]}\n```")

        else:
            # Treat text as resume text input
            from app.services.resume_parser import _split_into_sections, _parse_skills, _extract_name, _extract_inline_skills
            from app.models.resume import ParsedResume
            from app.storage.repositories import ResumeRepository
            import uuid, re

            # Basic text resume parsing
            lines = text.splitlines()
            name = _extract_name(lines)
            skills = _extract_inline_skills(text)
            sections = _split_into_sections(text)
            parsed_skills = _parse_skills(sections.get("skills", ""))
            all_skills = list({s.lower(): s for s in parsed_skills + skills}.values())

            resume_id = f"res_{uuid.uuid4().hex[:12]}"
            parsed_data = {
                "name": name,
                "email": "",
                "phone": "",
                "summary": sections.get("summary", "")[:200],
                "education": [],
                "skills": all_skills,
                "experience": [],
                "projects": [],
                "certifications": [],
                "achievements": [],
                "total_years_experience": 0.0,
            }
            ResumeRepository(db).create(
                resume_id=resume_id,
                filename="text_resume.txt",
                candidate_name=name,
                email="",
                phone="",
                parsed_data=parsed_data,
            )
            resume_ids = list(conv.resume_ids or []) + [resume_id]
            state_repo.update("google_chat", user_id, resume_ids=resume_ids)

            return build_text_response(
                f"✅ Resume text received for: {name}\n"
                f"Skills found: {len(all_skills)}\n\n"
                "Paste more resumes or type 'screen' to analyze.\n\n"
                "💡 For full PDF/DOCX support, use the REST API endpoint."
            )

    # Default
    return build_text_response(
        "Type 'analyze' to start resume screening, or 'help' for instructions."
    )
