"""
Discord Platform Adapter
Handles Discord bot integration using discord.py
All AI logic lives in screening_service, scoring_engine, ranking_service.

Required Bot Intents:
- message_content (Privileged)
- guilds
- guild_messages
- dm_messages

Required Bot Permissions:
- Read Messages
- Send Messages
- Attach Files
- Embed Links
"""
import asyncio
import logging
import io
from typing import Optional
from fastapi import APIRouter

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/integrations/discord", tags=["Discord"])
logger = get_logger(__name__)
settings = get_settings()

# Discord bot instance (runs as a background task)
_bot = None


def get_discord_bot():
    """
    Create and return the Discord bot instance.
    Requires: DISCORD_BOT_TOKEN in .env
    """
    if not settings.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN not configured. Discord integration disabled.")
        return None

    try:
        import discord
        from discord.ext import commands

        intents = discord.Intents.default()
        intents.message_content = True  # Privileged intent — must be enabled in Developer Portal
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True

        bot = commands.Bot(command_prefix="/", intents=intents)
        _setup_bot_events(bot)
        return bot
    except ImportError:
        logger.error("discord.py not installed. Run: pip install discord.py")
        return None


def _setup_bot_events(bot):
    """Configure Discord bot event handlers."""

    @bot.event
    async def on_ready():
        logger.info(f"Discord bot connected: {bot.user}")

    @bot.command(name="analyze")
    async def analyze_cmd(ctx):
        """Start resume screening flow."""
        await ctx.send(
            "👋 **Resume Screening Bot**\n\n"
            "I'll help you screen resumes against a job description.\n\n"
            "**Steps:**\n"
            "1. Use `/jd <job description text>` to provide the JD\n"
            "2. Attach resume files (PDF/DOCX) with `/upload`\n"
            "3. Use `/screen` to analyze\n\n"
            "⚠️ This is an AI-assisted tool, not an autonomous hiring system."
        )

    @bot.command(name="jd")
    async def jd_cmd(ctx, *, description: str):
        """Submit a job description."""
        if not description.strip():
            await ctx.send("❌ Please provide a job description after `/jd`")
            return

        from app.services.jd_parser import parse_job_description
        from app.storage.database import get_session_factory
        from app.storage.repositories import JobRepository, ConversationStateRepository
        import uuid

        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            parsed_jd = parse_job_description(description)
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            JobRepository(db).create(job_id, parsed_jd.job_title or "Unnamed", description, parsed_jd.model_dump())
            ConversationStateRepository(db).update(
                "discord", str(ctx.author.id),
                state="awaiting_resumes", job_id=job_id, resume_ids=[]
            )
            await ctx.send(
                f"✅ **Job Description received!**\n"
                f"📌 Role: {parsed_jd.job_title}\n"
                f"🔑 Skills: {', '.join(parsed_jd.required_skills[:5])}\n\n"
                "Now attach resume files and use `/screen` to analyze.\n"
                "(Upload PDFs or DOCX files as attachments with `/upload`)"
            )
        finally:
            db.close()

    @bot.command(name="upload")
    async def upload_cmd(ctx):
        """Upload resume files (attach to this message)."""
        if not ctx.message.attachments:
            await ctx.send("❌ Please attach PDF or DOCX resume files to this command.")
            return

        from app.services.resume_parser import parse_resume
        from app.utils.file_utils import validate_file_extension, save_temp_file, delete_temp_file, get_safe_filename
        from app.storage.database import get_session_factory
        from app.storage.repositories import ResumeRepository, ConversationStateRepository
        import uuid

        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            conv_repo = ConversationStateRepository(db)
            conv = conv_repo.get_or_create("discord", str(ctx.author.id))

            uploaded_names = []
            for attachment in ctx.message.attachments:
                safe_name = get_safe_filename(attachment.filename)
                if not validate_file_extension(safe_name):
                    await ctx.send(f"⚠️ Skipping unsupported file: {safe_name}")
                    continue

                file_bytes = await attachment.read()
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
                    conv_repo.update("discord", str(ctx.author.id), resume_ids=resume_ids)
                    uploaded_names.append(f"• {parsed.name} ({len(parsed.skills)} skills)")
                except Exception as e:
                    await ctx.send(f"❌ Failed to parse {safe_name}")
                    logger.error(f"Discord upload parse error: {type(e).__name__}")
                finally:
                    delete_temp_file(temp_path)

            if uploaded_names:
                await ctx.send(
                    f"✅ **Resumes uploaded:**\n" + "\n".join(uploaded_names) +
                    "\n\nUse `/screen` when ready to analyze."
                )
        finally:
            db.close()

    @bot.command(name="screen")
    async def screen_cmd(ctx):
        """Screen uploaded resumes against the JD."""
        from app.storage.database import get_session_factory
        from app.storage.repositories import (
            ConversationStateRepository, JobRepository, ResumeRepository
        )
        from app.services.scoring_engine import screen_resume
        from app.models.resume import ParsedResume
        from app.models.job import ParsedJobDescription
        from app.services.ranking_service import rank_candidates, build_comparison_table
        from app.services.report_service import generate_discord_embed, format_batch_report
        from app.models.screening import BatchScreeningResult
        from app.utils.chart_utils import generate_overall_score_chart
        from app.core.config import get_settings

        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            import discord as discord_lib

            conv_repo = ConversationStateRepository(db)
            conv = conv_repo.get_or_create("discord", str(ctx.author.id))
            resume_ids = list(conv.resume_ids or [])
            job_id = conv.job_id

            if not job_id:
                await ctx.send("❌ No job description set. Use `/jd <description>` first.")
                return
            if not resume_ids:
                await ctx.send("❌ No resumes uploaded. Use `/upload` with attached files first.")
                return

            await ctx.send(f"⏳ Analyzing {len(resume_ids)} resume(s)...")

            job_record = JobRepository(db).get(job_id)
            jd = ParsedJobDescription(**job_record.parsed_data)
            resume_records = ResumeRepository(db).get_many(resume_ids)
            s = get_settings()

            candidate_results = []
            for rr in resume_records:
                pd_data = dict(rr.parsed_data)
                pd_data["raw_text"] = ""
                resume = ParsedResume(**pd_data)
                section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)
                candidate_results.append({
                    "name": resume.name,
                    "analysis_id": f"dc_{rr.id}",
                    "overall_score": overall_score,
                    "section_scores": section_scores,
                    "skill_match": skill_detail,
                })

            if len(candidate_results) == 1:
                c = candidate_results[0]
                from app.models.screening import ScreeningResult
                result = ScreeningResult(
                    analysis_id=c["analysis_id"],
                    candidate_name=c["name"],
                    overall_score=c["overall_score"],
                    recommendation=s.get_score_category(c["overall_score"]),
                    section_scores=c["section_scores"],
                    skill_match=c["skill_match"],
                    strengths=[],
                    gaps=[],
                )
                embed_data = generate_discord_embed(result)
                embed = discord_lib.Embed(
                    title=embed_data["title"],
                    description=embed_data["description"],
                    color=embed_data["color"],
                )
                for field in embed_data["fields"]:
                    embed.add_field(name=field["name"], value=field["value"] or "N/A", inline=field["inline"])
                embed.set_footer(text=embed_data["footer"]["text"])
                await ctx.send(embed=embed)
            else:
                ranked = rank_candidates(candidate_results)
                comparison_table = build_comparison_table(ranked)
                batch_result = BatchScreeningResult(
                    batch_id="discord_batch",
                    job_title=job_record.title,
                    total_candidates=len(ranked),
                    ranked_candidates=ranked,
                    comparison_table=comparison_table,
                )
                from app.services.report_service import format_batch_report
                report = format_batch_report(batch_result, job_record.title)
                await ctx.send(f"```\n{report[:1900]}\n```")

                # Send chart
                try:
                    score_data = [{"name": rc.candidate_name, "score": rc.overall_score} for rc in ranked]
                    chart_path = generate_overall_score_chart(score_data, job_record.title)
                    with open(chart_path, "rb") as f:
                        await ctx.send(file=discord_lib.File(f, filename="ranking.png"))
                except Exception as e:
                    logger.warning(f"Discord chart send failed: {e}")

            conv_repo.reset("discord", str(ctx.author.id))
        finally:
            db.close()

    @bot.command(name="help")
    async def help_cmd(ctx):
        await ctx.send(
            "**Resume Screening Bot — Commands**\n\n"
            "`/analyze` — Show instructions\n"
            "`/jd <text>` — Submit job description\n"
            "`/upload` — Upload resume files (attach PDFs/DOCXs)\n"
            "`/screen` — Run screening analysis\n"
            "`/reset` — Reset conversation\n\n"
            "⚠️ AI-assisted tool. Not an autonomous hiring system."
        )

    @bot.command(name="reset")
    async def reset_cmd(ctx):
        from app.storage.database import get_session_factory
        from app.storage.repositories import ConversationStateRepository
        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            ConversationStateRepository(db).reset("discord", str(ctx.author.id))
            await ctx.send("✅ Conversation reset.")
        finally:
            db.close()


async def start_discord_bot():
    """Start the Discord bot as an async task."""
    bot = get_discord_bot()
    if bot is None:
        return
    try:
        await bot.start(settings.discord_bot_token)
    except Exception as e:
        logger.error(f"Discord bot start failed: {type(e).__name__}")
