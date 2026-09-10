# AI Resume Screening & Ranking Bot

> **Disclaimer:** This is an AI-assisted screening tool and not an autonomous hiring decision system. Scores are based solely on job-relevant qualifications. No candidate is evaluated based on gender, religion, race, caste, marital status, or any protected characteristic.

---

## Overview

The **AI Resume Screening & Ranking Bot** is a modular, production-quality backend system that analyzes resumes against job descriptions using a transparent, explainable scoring engine combined with semantic NLP.

It can be used:
- **Directly** via a REST API (Swagger UI)
- **Through messaging platforms:** Google Chat, Telegram, WhatsApp (Cloud API), Discord

---

## Problem Statement

HR teams manually screen hundreds of resumes per job opening. This is:
- Time-consuming
- Inconsistent
- Prone to bias when done at scale

This bot provides objective, consistent, explainable scores based on skill match, experience, education, and job description alignment — accessible through any messaging platform.

---

## Features

| Feature | Status |
|---|---|
| PDF resume parsing (PyMuPDF) | ✅ |
| DOCX resume parsing (python-docx) | ✅ |
| Job Description parsing | ✅ |
| Exact + normalized skill matching | ✅ |
| Semantic skill matching (sentence-transformers) | ✅ |
| Transparent, weighted scoring engine | ✅ |
| Single resume screening | ✅ |
| Batch screening (multiple resumes) | ✅ |
| Candidate ranking | ✅ |
| Comparison table | ✅ |
| Chart generation (matplotlib) | ✅ |
| SQLite database storage | ✅ |
| FastAPI REST API with Swagger | ✅ |
| Telegram bot adapter | ✅ |
| WhatsApp Cloud API adapter | ✅ |
| Google Chat app adapter | ✅ |
| Discord bot adapter | ✅ |
| Optional LLM insights (Ollama / OpenAI) | ✅ |
| Docker + docker-compose | ✅ |
| Comprehensive test suite | ✅ |

---

## Architecture

```
Google Chat ─┐
Telegram ────┤
WhatsApp ────┼──→ Platform Adapters (app/integrations/)
Discord ─────┘          │
                        ▼
                   FastAPI Core (app/main.py)
                        │
              Screening Services (app/services/)
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
    resume_parser   jd_parser   skill_matcher
                                      │
                                      ▼
                              scoring_engine
                                      │
                           ┌──────────┴──────────┐
                           ▼                     ▼
                      ranking_service       report_service
                           │                     │
                           └──────────┬──────────┘
                                      ▼
                                 chart_utils
                                      │
                                  SQLite DB
```

### Core Design Principles
- **Platform adapters** contain only communication logic
- **AI/scoring logic** lives exclusively in services
- **Scoring is deterministic** — LLM never computes numerical scores
- **Privacy-first** — temp files deleted after parsing; resume contents never logged

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI + Uvicorn |
| Data Validation | Pydantic v2 |
| Database | SQLAlchemy + SQLite (PostgreSQL-ready) |
| PDF Parsing | PyMuPDF |
| DOCX Parsing | python-docx |
| Semantic Matching | sentence-transformers |
| Chart Generation | matplotlib + seaborn |
| LLM Support | Ollama (local) or OpenAI-compatible |
| Telegram | Official Telegram Bot API |
| WhatsApp | Official Meta WhatsApp Cloud API |
| Discord | discord.py |
| Google Chat | Official Google Chat API |

---

## Folder Structure

```
resume-screening-bot/
├── app/
│   ├── main.py                    # FastAPI application entry point
│   ├── api/routes/
│   │   ├── health.py              # GET /health
│   │   ├── resumes.py             # POST /api/v1/resumes/upload
│   │   ├── jobs.py                # POST/GET /api/v1/jobs
│   │   └── screening.py          # POST /api/v1/screen, /screen/batch
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings + .env)
│   │   └── logging.py            # Logging configuration
│   ├── models/
│   │   ├── resume.py              # ParsedResume, ResumeUploadResponse
│   │   ├── job.py                 # ParsedJobDescription, JobCreateRequest
│   │   └── screening.py          # ScreeningResult, BatchScreeningResult
│   ├── services/
│   │   ├── resume_parser.py      # PDF/DOCX extraction + structure parsing
│   │   ├── jd_parser.py          # JD text → structured requirements
│   │   ├── skill_matcher.py      # Exact + normalized skill matching
│   │   ├── embedding_matcher.py  # Semantic matching (sentence-transformers)
│   │   ├── scoring_engine.py     # Transparent weighted scoring
│   │   ├── ranking_service.py    # Multi-candidate ranking
│   │   ├── report_service.py     # Text report formatting
│   │   └── llm_service.py        # LLM abstraction (Ollama / OpenAI)
│   ├── integrations/
│   │   ├── telegram.py           # Telegram Bot API adapter
│   │   ├── whatsapp.py           # WhatsApp Cloud API adapter
│   │   ├── google_chat.py        # Google Chat app adapter
│   │   └── discord.py            # Discord bot adapter
│   ├── storage/
│   │   ├── database.py           # SQLAlchemy models + session
│   │   └── repositories.py       # Data access objects
│   └── utils/
│       ├── chart_utils.py        # matplotlib chart generation
│       └── file_utils.py         # Safe file handling
├── tests/
│   ├── conftest.py               # Fixtures
│   ├── test_jd_parser.py
│   ├── test_skill_matcher.py
│   ├── test_scoring_engine.py
│   ├── test_ranking_service.py
│   ├── test_charts.py
│   ├── test_api.py               # API integration tests
│   └── test_e2e.py               # End-to-end tests
├── sample_data/
│   ├── sample_jd.txt
│   ├── create_sample_resumes.py  # Generates sample DOCX resumes
│   └── (generated DOCX files)
├── .env.example
├── .gitignore
├── requirements.txt
├── pytest.ini
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Scoring Methodology

The scoring engine is **fully deterministic and explainable**. LLM is never used to determine scores.

### Weights

| Section | Weight |
|---|---|
| Skills Match | 35% |
| Experience Match | 20% |
| Project Match | 15% |
| Education Match | 10% |
| JD Requirement Match | 15% |
| Resume Completeness | 5% |
| **Total** | **100%** |

Weights are configurable via `.env`.

### Score Categories

| Score | Category |
|---|---|
| 85–100 | Strong Match |
| 70–84 | Good Match |
| 55–69 | Moderate Match |
| 0–54 | Weak Match |

Thresholds are configurable via `.env`.

### How Each Section Is Scored

**Skills (35%):**
- Exact + normalized matching (handles aliases: `k8s` = `kubernetes`, `postgres` = `postgresql`)
- Semantic boost using sentence-transformers (max +15 points)
- Required skills weighted more than preferred skills

**Experience (20%):**
- Years of experience vs required years (50%)
- Technology overlap between experience entries and JD requirements (50%)

**Projects (15%):**
- Number of projects (20%)
- Relevance to JD technologies (50%)
- Technology coverage (30%)

**Education (10%):**
- Degree level vs requirement
- Field of study relevance bonus

**JD Match (15%):**
- Semantic text similarity (40%)
- Keyword presence (30%)
- Skill semantic overlap (30%)

**Completeness (5%):**
- Presence of name, email, phone, summary, skills, experience, education, etc.

---

## AI/NLP Pipeline

```
Resume Text
    │
    ▼
Section Detection
    │
    ▼
Structured Extraction (name, email, skills, experience, projects, education)
    │
    ▼
Skill Normalization (lowercase, alias mapping)
    │
    ├─── Exact Matching (set intersection)
    │
    └─── Semantic Matching (sentence-transformers cosine similarity)
              │
              ▼
         Scoring Engine (deterministic weights)
              │
              ▼
         Overall Score
              │
              ▼
         LLM Insights (optional, supplementary only)
```

---

## Local Windows Setup

### Prerequisites

- Python 3.11 or 3.12
- Git (optional)

### Step-by-Step

```powershell
# 1. Navigate to project directory
cd d:\ai-bonus\resume-screening-bot

# 2. Check Python version
python --version
# Expected: Python 3.11.x or 3.12.x

# 3. Create virtual environment
python -m venv .venv

# 4. Activate virtual environment
.venv\Scripts\activate

# 5. Install dependencies
pip install -r requirements.txt

# Note: sentence-transformers will download the embedding model on first run (~90MB)

# 6. Create environment file
copy .env.example .env

# 7. Create data directories
mkdir data, temp, generated -Force

# 8. Generate sample resumes
python sample_data\create_sample_resumes.py

# 9. Start the server
uvicorn app.main:app --reload

# Server starts at: http://localhost:8000
# Swagger UI:       http://localhost:8000/docs
# Health check:     http://localhost:8000/health
```

---

## Environment Variables

Edit `.env` after copying from `.env.example`.

### Core Settings
```env
APP_ENV=development
DEBUG=false
HOST=0.0.0.0
PORT=8000
```

### LLM (optional)
```env
# Disable LLM (core functionality works without it)
LLM_PROVIDER=none

# OR use Ollama (local)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# OR use OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

### Platform Tokens
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
DISCORD_BOT_TOKEN=your_discord_bot_token
WHATSAPP_ACCESS_TOKEN=your_meta_access_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_VERIFY_TOKEN=your_custom_verify_token
```

### Scoring (optional — defaults are ready-to-use)
```env
WEIGHT_SKILLS=35
WEIGHT_EXPERIENCE=20
WEIGHT_PROJECTS=15
WEIGHT_EDUCATION=10
WEIGHT_JD_MATCH=15
WEIGHT_COMPLETENESS=5

THRESHOLD_STRONG=85
THRESHOLD_GOOD=70
THRESHOLD_MODERATE=55
```

---

## Running Without Docker

```powershell
# Activate venv
.venv\Scripts\activate

# Run with auto-reload (development)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run for production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## Running With Docker

```bash
# Build and start
docker-compose up --build

# With Redis (optional)
docker-compose --profile with-redis up --build

# Background
docker-compose up -d --build

# Stop
docker-compose down
```

---

## API Documentation

Interactive API docs at: `http://localhost:8000/docs`

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Application health check |
| POST | `/api/v1/jobs` | Submit a job description |
| GET | `/api/v1/jobs/{job_id}` | Retrieve a job |
| GET | `/api/v1/jobs` | List all jobs |
| POST | `/api/v1/resumes/upload` | Upload a resume (PDF or DOCX) |
| POST | `/api/v1/resumes/upload-multiple` | Upload multiple resumes |
| POST | `/api/v1/screen` | Screen one resume |
| POST | `/api/v1/screen/batch` | Screen multiple resumes |
| GET | `/api/v1/results/{id}` | Get screening result |
| GET | `/api/v1/results/{id}/report` | Get formatted text report |

---

## Sample Usage

### 1. Create a Job Description

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Python Backend Engineer",
    "description": "We need a Python engineer with FastAPI, Docker, PostgreSQL, Redis, AWS. 5+ years experience. Bachelor CS required."
  }'
```

Response:
```json
{
  "job_id": "job_abc123",
  "title": "Senior Python Backend Engineer",
  "parsed": {
    "required_skills": ["python", "fastapi", "docker", "postgresql"],
    "min_years_experience": 5.0,
    ...
  }
}
```

### 2. Upload a Resume

```bash
curl -X POST http://localhost:8000/api/v1/resumes/upload \
  -F "file=@sample_data/resume_alex_chen.docx"
```

Response:
```json
{
  "resume_id": "res_xyz789",
  "candidate_name": "Alex Chen",
  "status": "parsed"
}
```

### 3. Screen Single Resume

```bash
curl -X POST http://localhost:8000/api/v1/screen \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "job_abc123",
    "resume_ids": ["res_xyz789"]
  }'
```

### 4. Batch Screen Multiple Resumes

```bash
curl -X POST http://localhost:8000/api/v1/screen/batch \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "job_abc123",
    "resume_ids": ["res_001", "res_002", "res_003"]
  }'
```

### 5. Get Formatted Report

```bash
curl http://localhost:8000/api/v1/results/{analysis_id}/report
```

---

## Google Chat Setup

### Requirements
1. Google Cloud Project: https://console.cloud.google.com/
2. Enable the **Google Chat API**
3. Go to **APIs & Services → Google Chat API → Configuration**
4. Create a Chat App:
   - Name: Resume Screening Bot
   - App URL: `https://your-domain.com/integrations/google-chat/webhook`
   - Authentication: Bearer Token (or Service Account for production)
5. Set permissions: Allow all domains or specific workspace

### Configuration (`.env`)
```env
GOOGLE_CHAT_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=./service_account.json  # For production
```

### Local Testing
Use ngrok for HTTPS tunnel:
```bash
ngrok http 8000
```
Set the ngrok URL as the App URL in Google Cloud Console.

### File Upload Limitation
Google Chat does not support arbitrary file uploads directly to Chat App bots. This MVP supports:
- Text-based JD and resume input
- REST API for full file upload support

A Google Drive integration can be added as a future improvement.

### Reference
- https://developers.google.com/chat/api/reference/rest
- https://developers.google.com/chat/how-tos/apps-develop

---

## Telegram Setup

### Steps
1. Create a bot: Message [@BotFather](https://t.me/botfather) → `/newbot`
2. Copy the bot token
3. Set in `.env`: `TELEGRAM_BOT_TOKEN=your_token_here`

### Webhook Setup (Production)
```bash
curl "https://api.telegram.org/bot{TOKEN}/setWebhook?url=https://your-domain.com/integrations/telegram/webhook"
```

### Local Testing (Polling alternative)
The webhook endpoint at `/integrations/telegram/webhook` handles incoming updates.
For local testing, use [ngrok](https://ngrok.com/) and set the webhook to your ngrok URL.

### Bot Commands
- `/analyze` — Start screening session
- `/reset` — Reset conversation
- `/help` — Show instructions
- `/screen` — Analyze uploaded resumes

### Reference
- https://core.telegram.org/bots/api
- https://core.telegram.org/bots/webhooks

---

## WhatsApp Setup

> Uses the **Official Meta WhatsApp Cloud API** — no unofficial libraries.

### Steps
1. Meta Developer Account: https://developers.facebook.com/
2. Create App → Select **Business** type
3. Add **WhatsApp** product
4. Get a test phone number or register your own
5. Copy **Phone Number ID** and **Access Token**
6. Set verify token (any random string you choose)
7. Configure Webhook:
   - URL: `https://your-domain.com/integrations/whatsapp/webhook`
   - Verify Token: (same as `WHATSAPP_VERIFY_TOKEN` in `.env`)
   - Subscribe to: `messages`

### Configuration (`.env`)
```env
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxx
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_VERIFY_TOKEN=my_custom_verify_token
```

### Local Testing
```bash
ngrok http 8000
# Use ngrok URL as webhook URL in Meta Developer Console
```

### Message Flow
1. User sends: `analyze`
2. Bot responds: "Please paste the Job Description"
3. User pastes JD text
4. Bot: "Received. Now send resume documents (PDF/DOCX)"
5. User sends documents
6. User sends: `screen`
7. Bot: returns analysis results

### Reference
- https://developers.facebook.com/docs/whatsapp/cloud-api
- https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks

---

## Discord Setup

### Steps
1. Discord Developer Portal: https://discord.com/developers/applications
2. New Application → Bot tab → Create Bot
3. Copy bot token
4. Enable Privileged Intents:
   - **Message Content Intent** (required)
5. Generate OAuth2 URL with permissions:
   - Read Messages
   - Send Messages
   - Attach Files
   - Embed Links
6. Invite bot to your server using the OAuth2 URL

### Configuration (`.env`)
```env
DISCORD_BOT_TOKEN=your_discord_bot_token
```

### Bot Commands (prefix: `/`)
- `/analyze` — Show instructions
- `/jd <description>` — Submit job description
- `/upload` — Upload resume files (attach PDFs/DOCXs)
- `/screen` — Run screening
- `/reset` — Reset conversation
- `/help` — Show help

### Reference
- https://discord.com/developers/docs
- https://discordpy.readthedocs.io/

---

## Local HTTPS / Webhook Testing

All messaging platforms require HTTPS webhook URLs. For local development:

### Using ngrok
```bash
# Install ngrok: https://ngrok.com/
ngrok http 8000

# Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
# Use it as the webhook URL in each platform's configuration
```

### Using Localtunnel (alternative)
```bash
npx localtunnel --port 8000
```

---

## Running Tests

```powershell
# Activate venv
.venv\Scripts\activate

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test files
pytest tests/test_scoring_engine.py -v
pytest tests/test_api.py -v
pytest tests/test_e2e.py -v -s
```

---

## Deployment

### Recommended: VPS with nginx + SSL

```bash
# Install nginx and certbot for SSL
# nginx config:
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Cloud Options
- **Railway.app** — Simple Docker deployment
- **Render.com** — Free tier available
- **AWS EC2** — Full control
- **Google Cloud Run** — Serverless container

### Environment Variables
Set all variables from `.env.example` in your hosting provider's environment settings.
**Never commit `.env` to version control.**

---

## Security

- All credentials in `.env` — never in code
- File validation: extension + size limits
- Temp files deleted immediately after parsing
- Resume contents never logged
- API keys/tokens never logged
- Secure random IDs for all records

---

## Privacy

- Resume text is parsed and then deleted from disk
- Only structured metadata is stored (name, email, skills — not full resume text)
- Raw resume text is not persisted in the database
- Delete your database file to remove all candidate data
- Personal data is handled per GDPR principles

---

## Limitations

1. **Resume Parser Accuracy:** Parsing quality depends on resume structure. Non-standard formats may have reduced accuracy.
2. **Semantic Matching:** Requires sentence-transformers model download (~90MB) on first run.
3. **Google Chat File Uploads:** Text-based input only in the current MVP; Google Drive integration needed for file upload.
4. **WhatsApp Formatting:** Results sent as plain text (WhatsApp does not support markdown in most messages).
5. **Database:** SQLite is file-based; for high concurrency, migrate to PostgreSQL.
6. **LLM:** Optional; disabled by default. Enabling requires either Ollama (local) or OpenAI API key.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` in venv |
| `sqlite3.OperationalError` | Run `mkdir data` to create data directory |
| Webhook not receiving | Check ngrok is running and URL is correctly configured |
| Chart generation fails | Install matplotlib: `pip install matplotlib` |
| Sentence-transformers slow | Model downloads on first use; subsequent runs are faster |
| Discord bot not connecting | Check `DISCORD_BOT_TOKEN` and enable Message Content Intent |
| WhatsApp webhook 403 | Verify `WHATSAPP_VERIFY_TOKEN` matches Meta configuration |

---

## Future Improvements

- [ ] PostgreSQL support (remove SQLite limitation)
- [ ] Web dashboard UI (React/Vue)
- [ ] Google Drive integration for file uploads via Google Chat
- [ ] Resume template detection and normalization
- [ ] Multi-language resume support
- [ ] Batch email digest reports
- [ ] ATS (Applicant Tracking System) integration
- [ ] Interview question generation based on gaps
- [ ] Candidate anonymization mode
- [ ] GDPR data export/deletion API
- [ ] Prometheus metrics + Grafana dashboard
- [ ] Redis caching for repeated analyses

---

## ⚠️ Ethical Notice

This application is an **AI-assisted screening tool**.

- It does **NOT** make autonomous hiring decisions
- It does **NOT** evaluate candidates based on gender, religion, race, caste, photograph, marital status, or any non-job-relevant attribute
- All scores are based solely on job-relevant qualifications
- Final hiring decisions must be made by qualified human reviewers
- The tool is meant to assist, not replace, human judgment
