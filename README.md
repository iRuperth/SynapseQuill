<div align="center">

# ⚽ F88tball

**Automated FIFA World Cup 2026 highlight-video generator for YouTube — powered by LLMs, LangChain/LangGraph and free-tier AI.**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![LangChain](https://img.shields.io/badge/LangChain-LangGraph-1C3C3C)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/cost-free--tier-2dd4bf)

</div>

## What it is

Give F88tball a finished World Cup match and it builds a ready-to-publish
highlight video: an exciting narration written by an LLM, a real voice
(Edge-TTS), copyright-safe visuals (team crests, animated scoreboard, AI
ambience), burned-in subtitles, and an automatic **private** upload to YouTube.
It also generates blog / X / Instagram / LinkedIn copy for the same match.

Everything runs on **free tiers** — Groq, Pollinations (FLUX), Edge-TTS,
API-Football, local embeddings — so the proof of concept costs nothing to run.

## How it works

```
[poll API-Football]  --finished match-->  narration (LLM)
                                              |
                          +-------------------+-------------------+
                          v                   v                   v
                   guardrail (judge)    visuals (stock +      voice + subtitles
                   verify score/        scoreboard +          (Edge-TTS)
                   scorers              FLUX ambience)
                          +-------------------+-------------------+
                                              v
                                     video_assembler (.mp4)
                                              v
                                  YouTube upload (private)
```

## Architecture

```
F88tball/
├── core/
│   ├── brand_config.py     # BrandProfile — per-profile config (team, language, voice, preamble)
│   ├── llm/                # switchable LLMs: groq · gemini · cerebras · ollama (+ fallbacks)
│   └── tracing.py          # LangSmith activation
├── pipeline/
│   ├── match_monitor.py    # API-Football: World Cup fixtures + finished-match detection
│   ├── narrator.py         # exciting multi-language narration + YouTube metadata
│   ├── media_provider.py   # visuals: real crests · scoreboard/timeline · FLUX ambience
│   ├── image_generator.py  # switchable image provider (Pollinations FLUX default)
│   ├── voice_generator.py  # Edge-TTS voice + synchronized subtitles
│   ├── video_assembler.py  # MoviePy slideshow + audio + burned-in subtitles -> .mp4
│   ├── content_generator.py# blog / X / Instagram / LinkedIn copy
│   ├── publishers.py       # YouTube Data API v3 OAuth upload (private)
│   ├── runner.py           # per-match orchestration (with guardrail)
│   └── tools/              # finance (Finnhub) · arxiv_rag (Chroma) · graph_rag (NetworkX)
├── agents/
│   ├── guardrail.py        # anti-hallucination: facts check + LLM-as-judge
│   └── graph.py            # LangGraph supervisor routing specialised agents
├── api/server.py           # FastAPI backend (profiles, matches, generate, status)
├── frontend/               # React 19 + Vite 7 + TS dashboard
├── profiles/<id>/          # profile.json + .env + tokens + output
├── main.py                 # CLI (fixtures, match, scheduler, report)
└── docker-compose.yml      # backend + frontend (nginx)
```

## Tech stack

| Layer | Choice | Free tier |
|-------|--------|-----------|
| Text LLM | Groq (Llama 3.3 70B) + Gemini / Cerebras / Ollama | yes |
| Orchestration | LangChain · LangGraph · LangSmith | 5k traces/mo |
| Images | Pollinations **FLUX** (no key) -> Cloudflare / HF / local | free |
| Voice | Edge-TTS (no key) -> Piper / gTTS | free |
| Football data | API-Football (World Cup 2026) | 100 req/day |
| Video | MoviePy + ffmpeg | — |
| RAG | arXiv + Chroma + BAAI/bge-small (local) | free |
| Graph RAG | LLMGraphTransformer + NetworkX | free |
| Finance | Finnhub (+ yfinance) | 60 req/min |
| Frontend | React 19 · Vite 7 · TypeScript | — |

## Quick start

```bash
# 1. Backend
uv sync
cp .env.example .env          # add GROQ_API_KEY and APIFOOTBALL_KEY (both free)
uv run uvicorn api.server:app --reload --port 5001

# 2. Frontend
cd frontend && pnpm install && pnpm run dev    # http://localhost:5173
```

Images (Pollinations/FLUX) and voice (Edge-TTS) need **no API key**.

## CLI

```bash
python main.py --profile worldcup_es --fixtures            # today's matches
python main.py --profile worldcup_es --match 12345         # generate one video
python main.py --profile worldcup_es --scheduler           # auto-generate as matches finish
python main.py --profile worldcup_es --match 12345 --upload --social
```

## Background scheduler (macOS)

Run the scheduler as a background service that auto-generates and uploads a
summary as each match finishes. It survives closing the terminal and the IDE,
restarts on crash, and starts at login — no need to keep a terminal open.

```bash
bash scripts/f88ball_scheduler_ctl.sh install    # install + start
bash scripts/f88ball_scheduler_ctl.sh status     # is it running?
bash scripts/f88ball_scheduler_ctl.sh logs        # follow the log live
bash scripts/f88ball_scheduler_ctl.sh stop        # stop
bash scripts/f88ball_scheduler_ctl.sh uninstall   # remove
```

Runs while the Mac is on and signed in. Logs at
`profiles/worldcup_es/output/logs/scheduler.log`. Poll interval and profile are
set in `scripts/f88ball_scheduler.sh`. The launchd label is `com.f88ball.scheduler`
(unique per app, so multiple projects can each run their own).

## Docker

```bash
cp .env.example .env
docker compose up --build      # frontend :8080  ·  backend :5001
```

## API keys

Required for a demo: `GROQ_API_KEY`, `APIFOOTBALL_KEY`.
For YouTube upload: per-profile `profiles/<id>/tokens/client_secret.json` (OAuth).
Optional (extra credit): `GEMINI_API_KEY`, `LANGSMITH_API_KEY`, `FINNHUB_API_KEY`, `PEXELS_API_KEY`.

## Privacy / practice mode

`PRACTICE_MODE=true` (default) forces YouTube uploads to **private**.
Set `YOUTUBE_PRIVACY=private|unlisted|public` to change visibility once ready.

## Briefing coverage

| Level | Requirement | Where |
|-------|-------------|-------|
| Essential | Multi-platform text from prompts; web UI; git | `content_generator.py`, `frontend/` |
| Medium | Docker; ≥2 LLMs; company/persona preamble; images in content | `docker-compose.yml`, `core/llm/`, `brand_config.system_preamble`, `media_provider.py` |
| Advanced | Tracing; ES/EN/FR/IT; live finance news; arXiv RAG | `tracing.py`, `narrator.py`, `tools/finance.py`, `tools/arxiv_rag.py` |
| Expert | Graph RAG; multi-agent system; guardrails | `tools/graph_rag.py`, `agents/graph.py`, `agents/guardrail.py` |
