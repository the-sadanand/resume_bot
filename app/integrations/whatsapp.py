"""
WhatsApp Cloud API Adapter
Official WhatsApp Business Cloud API integration.
Handles: webhook verification, incoming messages, media workflow, outgoing responses.

IMPORTANT: This is the OFFICIAL Meta WhatsApp Cloud API, NOT any unofficial automation.

Setup:
1. Meta Developer Account: https://developers.facebook.com/
2. Create App → Add WhatsApp product
3. Set up WhatsApp Business Account
4. Obtain Phone Number ID and Access Token
5. Configure webhook URL: https://your-domain.com/integrations/whatsapp/webhook
6. Set verify token in .env (WHATSAPP_VERIFY_TOKEN)

Local testing: Use ngrok or similar for HTTPS tunnel.
"""
import logging
import hashlib
import hmac
from typing import Optional

from fastapi import APIRouter, Request, Response, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.storage.repositories import ConversationStateRepository, JobRepository, ResumeRepository
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/integrations/whatsapp", tags=["WhatsApp"])
logger = get_logger(__name__)
settings = get_settings()

WHATSAPP_API_BASE = "https://graph.facebook.com/v19.0"


# ── Message Sending ───────────────────────────────────────────────────────────

async def send_whatsapp_text(to: str, text: str) -> bool:
    """Send a text message via WhatsApp Cloud API."""
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        logger.warning("WhatsApp credentials not configured")
        return False

    try:
        import httpx
        url = f"{WHATSAPP_API_BASE}/{settings.whatsapp_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4096]},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code != 200:
                logger.error(f"WhatsApp API error: {resp.status_code}")
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"WhatsApp send failed: {type(e).__name__}")
        return False


async def download_whatsapp_media(media_id: str) -> Optional[bytes]:
    """Download a media file from WhatsApp."""
    if not settings.whatsapp_access_token:
        return None
    try:
        import httpx
        headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
        async with httpx.AsyncClient() as client:
            # Get media URL
            r = await client.get(
                f"{WHATSAPP_API_BASE}/{media_id}",
                headers=headers, timeout=15,
            )
            media_url = r.json().get("url")
            if not media_url:
                return None
            # Download
            r2 = await client.get(media_url, headers=headers, timeout=30)
            return r2.content
    except Exception as e:
        logger.error(f"WhatsApp media download failed: {type(e).__name__}")
        return None


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.get("/webhook")
async def whatsapp_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    WhatsApp webhook verification endpoint.
    Meta sends a GET request with hub.challenge to verify ownership.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("WhatsApp webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("WhatsApp webhook verification failed")
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    WhatsApp webhook POST handler.
    Receives incoming messages and events from Meta.

    Message flow:
    1. User sends /analyze
    2. Bot asks for JD
    3. User pastes JD
    4. Bot asks for resumes
    5. User sends document(s)
    6. User sends /screen
    7. Bot returns analysis
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Navigate WhatsApp webhook structure
    entry = body.get("entry", [])
    if not entry:
        return {"status": "ok"}

    for e in entry:
        changes = e.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])

            for message in messages:
                sender = message.get("from")  # Phone number
                msg_type = message.get("type")

                # Handle text messages
                if msg_type == "text":
                    text = message.get("text", {}).get("body", "").strip()
                    await _handle_whatsapp_text(sender, text, db)

                # Handle document (resume file)
                elif msg_type == "document":
                    doc = message.get("document", {})
                    await _handle_whatsapp_document(sender, doc, db)

    return {"status": "ok"}


async def _handle_whatsapp_text(phone: str, text: str, db: Session):
    """Handle incoming WhatsApp text messages."""
    state_repo = ConversationStateRepository(db)
    conv = state_repo.get_or_create("whatsapp", phone)
    current_state = conv.state

    text_lower = text.lower().strip()

    if text_lower in ("/analyze", "analyze", "/start", "start", "hi", "hello"):
        state_repo.update("whatsapp", phone, state="awaiting_jd", job_id=None, resume_ids=[])
        await send_whatsapp_text(phone,
            "👋 Welcome to Resume Screening Bot!\n\n"
            "Please paste the *Job Description* text now."
        )
        return

    if text_lower in ("/reset", "reset"):
        state_repo.reset("whatsapp", phone)
        await send_whatsapp_text(phone, "✅ Reset. Send 'analyze' to start again.")
        return

    if text_lower in ("/screen", "screen") and current_state == "awaiting_resumes":
        resume_ids = list(conv.resume_ids or [])
        job_id = conv.job_id

        if not resume_ids:
            await send_whatsapp_text(phone, "❌ No resumes uploaded yet. Please send resume documents first.")
            return

        await send_whatsapp_text(phone, f"⏳ Analyzing {len(resume_ids)} resume(s)...")

        try:
            from app.services.scoring_engine import screen_resume
            from app.models.resume import ParsedResume
            from app.models.job import ParsedJobDescription
            from app.core.config import get_settings as _gs
            from app.services.ranking_service import rank_candidates
            from app.services.report_service import format_single_report, format_batch_report
            from app.models.screening import ScreeningResult, BatchScreeningResult

            job_record = JobRepository(db).get(job_id)
            jd = ParsedJobDescription(**job_record.parsed_data)
            resume_records = ResumeRepository(db).get_many(resume_ids)
            s = _gs()

            if len(resume_ids) == 1:
                rr = resume_records[0]
                pd_data = dict(rr.parsed_data)
                pd_data["raw_text"] = ""
                resume = ParsedResume(**pd_data)
                section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)
                result = ScreeningResult(
                    analysis_id="wa_result",
                    candidate_name=resume.name,
                    overall_score=overall_score,
                    recommendation=s.get_score_category(overall_score),
                    section_scores=section_scores,
                    skill_match=skill_detail,
                    strengths=strengths,
                    gaps=gaps,
                )
                report = format_single_report(result, job_record.title)
                await send_whatsapp_text(phone, report[:4000])
            else:
                candidate_results = []
                for rr in resume_records:
                    pd_data = dict(rr.parsed_data)
                    pd_data["raw_text"] = ""
                    resume = ParsedResume(**pd_data)
                    section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)
                    candidate_results.append({
                        "name": resume.name,
                        "analysis_id": f"wa_{rr.id}",
                        "overall_score": overall_score,
                        "section_scores": section_scores,
                        "skill_match": skill_detail,
                    })
                ranked = rank_candidates(candidate_results)
                from app.services.ranking_service import build_comparison_table
                comparison_table = build_comparison_table(ranked)
                batch_result = BatchScreeningResult(
                    batch_id="wa_batch",
                    job_title=job_record.title,
                    total_candidates=len(ranked),
                    ranked_candidates=ranked,
                    comparison_table=comparison_table,
                )
                report = format_batch_report(batch_result, job_record.title)
                await send_whatsapp_text(phone, report[:4000])

            state_repo.reset("whatsapp", phone)

        except Exception as e:
            logger.error(f"WhatsApp screening error: {type(e).__name__}: {e}")
            await send_whatsapp_text(phone, "❌ Analysis failed. Please try again.")
        return

    if current_state == "awaiting_jd" and text and not text.startswith("/"):
        from app.services.jd_parser import parse_job_description
        import uuid

        parsed_jd = parse_job_description(text)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        JobRepository(db).create(job_id, parsed_jd.job_title or "Unnamed", text, parsed_jd.model_dump())
        state_repo.update("whatsapp", phone, state="awaiting_resumes", job_id=job_id, resume_ids=[])

        await send_whatsapp_text(phone,
            f"✅ Job Description received!\n"
            f"Role: {parsed_jd.job_title}\n"
            f"Required skills: {', '.join(parsed_jd.required_skills[:5])}\n\n"
            "Now send me resume documents (PDF or DOCX).\n"
            "Type 'screen' when done uploading all resumes."
        )
        return

    # Default
    await send_whatsapp_text(phone, "Type 'analyze' to start, or 'screen' after uploading resumes.")


async def _handle_whatsapp_document(phone: str, doc: dict, db: Session):
    """Handle incoming WhatsApp document (resume file)."""
    from app.utils.file_utils import validate_file_extension, save_temp_file, delete_temp_file, get_safe_filename
    from app.services.resume_parser import parse_resume
    import uuid

    state_repo = ConversationStateRepository(db)
    conv = state_repo.get_or_create("whatsapp", phone)

    if conv.state != "awaiting_resumes":
        await send_whatsapp_text(phone, "Please start with 'analyze' first.")
        return

    filename = doc.get("filename", "resume.pdf")
    media_id = doc.get("id")
    safe_name = get_safe_filename(filename)

    if not validate_file_extension(safe_name):
        await send_whatsapp_text(phone, f"❌ Unsupported file type. Please send PDF or DOCX files.")
        return

    file_bytes = await download_whatsapp_media(media_id)
    if not file_bytes:
        await send_whatsapp_text(phone, "❌ Failed to download file. Please try again.")
        return

    temp_path = save_temp_file(file_bytes, safe_name)
    try:
        parsed = parse_resume(temp_path)
        resume_id = f"res_{uuid.uuid4().hex[:12]}"
        ResumeRepository(db).create(
            resume_id=resume_id,
            filename=safe_name,
            candidate_name=parsed.name,
            email=parsed.email,
            phone=parsed.phone,
            parsed_data=parsed.model_dump(exclude={"raw_text"}),
        )
        resume_ids = list(conv.resume_ids or []) + [resume_id]
        state_repo.update("whatsapp", phone, resume_ids=resume_ids)
        await send_whatsapp_text(phone,
            f"✅ Resume received: {parsed.name}\n"
            f"Skills found: {len(parsed.skills)}\n\n"
            "Send more resumes or type 'screen' to analyze."
        )
    except Exception as e:
        logger.error(f"WhatsApp resume parse failed: {type(e).__name__}")
        await send_whatsapp_text(phone, "❌ Failed to parse resume. Please try again.")
    finally:
        delete_temp_file(temp_path)
