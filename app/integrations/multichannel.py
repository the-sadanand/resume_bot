"""Multi-channel adapters for Discord, Google Chat and WhatsApp.

The adapters reuse the existing deterministic resume-scoring engine from the
Telegram integration. They intentionally keep channel-specific transport code
separate from the scoring logic.
"""
import base64
import hashlib
import hmac
import io
import json
from datetime import datetime

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.telegram import (
    MAX_FILE_SIZE,
    MAX_RESUMES,
    extract_document_text,
    format_result,
    score_resume,
    validate_jd,
    validate_resume,
)

try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
except Exception:  # pragma: no cover
    VerifyKey = None
    BadSignatureError = Exception

router = APIRouter(prefix="/integrations", tags=["Multi-channel"])
settings = get_settings()
logger = get_logger(__name__)

SESSIONS = {}


def session_for(key: str):
    session = SESSIONS.setdefault(
        key,
        {"state": "idle", "jd": "", "resumes": [], "updated": datetime.utcnow()},
    )
    session["updated"] = datetime.utcnow()
    return session


def reset_session(key: str):
    SESSIONS[key] = {"state": "idle", "jd": "", "resumes": [], "updated": datetime.utcnow()}
    return SESSIONS[key]


def add_resume(session, filename: str, data: bytes):
    if len(session["resumes"]) >= MAX_RESUMES:
        return False, f"You can add up to {MAX_RESUMES} resumes per screening session."
    if len(data) > MAX_FILE_SIZE:
        return False, "This file is larger than the 10 MB limit."
    digest = hashlib.sha256(data).hexdigest()
    if any(x["sha256"] == digest for x in session["resumes"]):
        return False, "That resume was already added."
    try:
        text = extract_document_text(data, filename)
    except Exception as exc:
        return False, str(exc)
    valid, reason = validate_resume(text, filename)
    if not valid:
        return False, reason
    session["resumes"].append({"filename": filename, "text": text, "sha256": digest})
    return True, f"Added **{filename}**. {len(session['resumes'])}/{MAX_RESUMES} resumes ready."


def screen_session(session):
    if not session["jd"]:
        return "Please send the Job Description first."
    if not session["resumes"]:
        return "Please upload at least one resume first."
    ranked = []
    for item in session["resumes"]:
        result = score_resume(session["jd"], item["text"])
        ranked.append((item["filename"], result))
    ranked.sort(key=lambda x: x[1]["overall"], reverse=True)
    chunks = ["🏆 **RESUME SCREENING RANKING**", "", f"Candidates: {len(ranked)}"]
    for idx, (filename, result) in enumerate(ranked, 1):
        chunks.append(
            f"**{idx}. {filename}** — {result['overall']:.1f}/100 ({result['recommendation']})\n"
            f"Skills {result['skills']:.0f}% · Experience {result['experience']:.0f}% · "
            f"Projects {result['projects']:.0f}% · JD {result['jd_match']:.0f}%"
        )
    chunks.append("")
    chunks.append("Send another resume to add it, or start a new session with /analyze.")
    return "\n\n".join(chunks)


def help_text(channel: str):
    if channel == "discord":
        return (
            "📄 **Resume Screening Bot**\n\n"
            "1. `/analyze` — start a screening session\n"
            "2. `/jd` — send the Job Description text\n"
            "3. `/resume` — attach a PDF/DOCX resume\n"
            "4. `/screen` — rank all uploaded resumes\n"
            "5. `/reset` — clear the current session"
        )
    return (
        "📄 *Resume Screening Bot*\n\n"
        "1. Send `/analyze`\n"
        "2. Send the Job Description as text\n"
        "3. Upload PDF/DOCX resumes one by one\n"
        "4. Send `/screen` to rank them\n"
        "5. Send `/reset` to start over"
    )


# ---------------- Discord ----------------

DISCORD_COMMANDS = [
    {"name": "analyze", "description": "Start a resume screening session"},
    {"name": "jd", "description": "Set the Job Description", "options": [{"name": "text", "description": "Job Description text", "type": 3, "required": True}]},
    {"name": "resume", "description": "Add a PDF/DOCX resume", "options": [{"name": "file", "description": "PDF or DOCX resume", "type": 11, "required": True}]},
    {"name": "screen", "description": "Rank all resumes against the current JD"},
    {"name": "reset", "description": "Reset the current screening session"},
    {"name": "help", "description": "Show bot instructions"},
]


def verify_discord(body: bytes, signature: str | None, timestamp: str | None):
    if not settings.discord_public_key:
        raise HTTPException(status_code=503, detail="Discord public key is not configured.")
    if not signature or not timestamp or VerifyKey is None:
        raise HTTPException(status_code=401, detail="Invalid Discord signature.")
    try:
        VerifyKey(bytes.fromhex(settings.discord_public_key)).verify(
            timestamp.encode() + body, bytes.fromhex(signature)
        )
    except (BadSignatureError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid Discord signature.")


async def discord_download(url: str):
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.content
        if len(data) > MAX_FILE_SIZE:
            raise ValueError("This file is larger than the 10 MB limit.")
        return data


async def discord_followup(application_id: str, token: str, content: str):
    url = f"https://discord.com/api/v10/webhooks/{application_id}/{token}/messages/@original"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(url, json={"content": content[:1900]})
        response.raise_for_status()


@router.get("/discord/commands")
async def discord_commands():
    """Returns the command JSON to paste/use when registering the Discord app."""
    return DISCORD_COMMANDS


@router.post("/discord/interactions")
async def discord_interactions(
    request: Request,
    x_signature_ed25519: str | None = Header(default=None),
    x_signature_timestamp: str | None = Header(default=None),
):
    body = await request.body()
    verify_discord(body, x_signature_ed25519, x_signature_timestamp)
    payload = json.loads(body)
    if payload.get("type") == 1:
        return {"type": 1}
    if payload.get("type") != 2:
        return {"type": 4, "data": {"content": "Unsupported Discord interaction."}}

    command = payload.get("data", {}).get("name", "")
    user = payload.get("member", {}).get("user", {}) or payload.get("user", {})
    uid = user.get("id", "unknown")
    key = f"discord:{uid}"
    session = session_for(key)
    options = payload.get("data", {}).get("options", [])
    values = {x.get("name"): x for x in options}

    if command == "help":
        return {"type": 4, "data": {"content": help_text("discord")}}
    if command == "analyze":
        reset_session(key)
        return {"type": 4, "data": {"content": "✅ Screening session started. Now use `/jd` to send the Job Description."}}
    if command == "reset":
        reset_session(key)
        return {"type": 4, "data": {"content": "🧹 Session reset."}}
    if command == "jd":
        text = str(values.get("text", {}).get("value", "")).strip()
        ok, reason = validate_jd(text)
        if not ok:
            return {"type": 4, "data": {"content": f"❌ {reason}"}}
        session["jd"] = text
        session["state"] = "awaiting_resumes"
        return {"type": 4, "data": {"content": "✅ Job Description saved. Now use `/resume` and attach a PDF/DOCX resume."}}
    if command == "resume":
        if not session["jd"]:
            return {"type": 4, "data": {"content": "❌ Send `/jd` first."}}
        attachment_id = values.get("file", {}).get("value")
        attachment = payload.get("data", {}).get("resolved", {}).get("attachments", {}).get(str(attachment_id), {})
        if not attachment:
            return {"type": 4, "data": {"content": "❌ I could not read that attachment."}}
        filename = attachment.get("filename", "resume.pdf")
        if not filename.lower().endswith((".pdf", ".docx")):
            return {"type": 4, "data": {"content": "❌ Only PDF and DOCX resumes are supported."}}
        try:
            data = await discord_download(attachment.get("url", ""))
            ok, message = add_resume(session, filename, data)
        except Exception as exc:
            ok, message = False, f"Could not download the resume: {type(exc).__name__}"
        return {"type": 4, "data": {"content": ("✅ " if ok else "❌ ") + message}}
    if command == "screen":
        return {"type": 4, "data": {"content": screen_session(session)[:1900]}}
    return {"type": 4, "data": {"content": "Unknown command. Use `/help`."}}


# ---------------- WhatsApp ----------------

async def whatsapp_send(to: str, text: str):
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        logger.warning("WhatsApp credentials are not configured")
        return
    url = f"https://graph.facebook.com/v23.0/{settings.whatsapp_phone_number_id}/messages"
    async with httpx.AsyncClient(timeout=30) as client:
        for start in range(0, len(text), 3500):
            chunk = text[start:start + 3500]
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": chunk}},
            )
            response.raise_for_status()


async def whatsapp_download(media_id: str):
    base = "https://graph.facebook.com/v23.0"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        meta = await client.get(f"{base}/{media_id}", headers=headers)
        meta.raise_for_status()
        url = meta.json().get("url")
        if not url:
            raise ValueError("WhatsApp did not return a media URL.")
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        if len(response.content) > MAX_FILE_SIZE:
            raise ValueError("This file is larger than the 10 MB limit.")
        return response.content


@router.get("/whatsapp/webhook")
async def whatsapp_verify(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") != settings.whatsapp_verify_token:
        raise HTTPException(status_code=403, detail="Invalid verification token.")
    return int(params.get("hub.challenge", "0"))


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                sender = message.get("from")
                if not sender:
                    continue
                key = f"whatsapp:{sender}"
                session = session_for(key)
                mtype = message.get("type")
                if mtype == "text":
                    text = message.get("text", {}).get("body", "").strip()
                    low = text.lower()
                    if low in {"/start", "/help"}:
                        await whatsapp_send(sender, help_text("whatsapp"))
                    elif low == "/analyze":
                        reset_session(key)
                        await whatsapp_send(sender, "✅ Screening session started. Send the Job Description as text.")
                    elif low == "/reset":
                        reset_session(key)
                        await whatsapp_send(sender, "🧹 Session reset.")
                    elif low == "/screen":
                        await whatsapp_send(sender, screen_session(session))
                    elif not session["jd"]:
                        ok, reason = validate_jd(text)
                        if ok:
                            session["jd"] = text
                            session["state"] = "awaiting_resumes"
                            await whatsapp_send(sender, "✅ Job Description saved. Now upload PDF/DOCX resumes.")
                        else:
                            await whatsapp_send(sender, f"❌ {reason}")
                    else:
                        await whatsapp_send(sender, "Please upload a PDF/DOCX resume, or send `/screen` when finished.")
                elif mtype == "document":
                    if not session["jd"]:
                        await whatsapp_send(sender, "❌ Send the Job Description first.")
                        continue
                    doc = message.get("document", {})
                    filename = doc.get("filename", "resume.pdf")
                    if not filename.lower().endswith((".pdf", ".docx")):
                        await whatsapp_send(sender, "❌ Only PDF and DOCX resumes are supported.")
                        continue
                    try:
                        data = await whatsapp_download(doc.get("id", ""))
                        ok, result = add_resume(session, filename, data)
                    except Exception as exc:
                        ok, result = False, f"Could not process the file: {type(exc).__name__}"
                    await whatsapp_send(sender, ("✅ " if ok else "❌ ") + result)
                else:
                    await whatsapp_send(sender, "I support text messages and PDF/DOCX resume documents.")
    return {"ok": True}


# ---------------- Google Chat ----------------


def google_credentials():
    if not settings.google_application_credentials:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not configured.")
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_file(
        settings.google_application_credentials,
        scopes=["https://www.googleapis.com/auth/chat.bot"],
    )


def google_chat_download(resource_name: str):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    service = build("chat", "v1", credentials=google_credentials(), cache_discovery=False)
    request = service.media().download_media(resourceName=resource_name)
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        if output.tell() > MAX_FILE_SIZE:
            raise ValueError("This file is larger than the 10 MB limit.")
    return output.getvalue()


@router.post("/google-chat/events")
async def google_chat_events(request: Request):
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
        return {"text": screen_session(session)}

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
