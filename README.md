<div align="center">

<img src="frontend/public/logo.png" alt="F88tball" width="380" />

### Automated FIFA World Cup 2026 highlight-video generator for YouTube, powered by LLMs, LangChain / LangGraph and free-tier AI.

[![English](https://img.shields.io/badge/English-1a1a1a?style=for-the-badge)](README.md) **·** [![Español](https://img.shields.io/badge/Espa%C3%B1ol-1a1a1a?style=for-the-badge)](README.es.md)

[![Python](https://img.shields.io/badge/Python-3.12-1a1a1a?style=flat&logo=python&logoColor=white&labelColor=1a1a1a)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-1a1a1a?style=flat&logo=fastapi&logoColor=white&labelColor=1a1a1a)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-1a1a1a?style=flat&logo=react&logoColor=white&labelColor=1a1a1a)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-7.x-1a1a1a?style=flat&logo=vite&logoColor=white&labelColor=1a1a1a)](https://vitejs.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-1a1a1a?style=flat&logo=typescript&logoColor=white&labelColor=1a1a1a)](https://www.typescriptlang.org/)
[![LangChain](https://img.shields.io/badge/LangChain-LangGraph-1a1a1a?style=flat&logo=langchain&logoColor=white&labelColor=1a1a1a)](https://www.langchain.com/)
[![MoviePy](https://img.shields.io/badge/MoviePy-ffmpeg-1a1a1a?style=flat&labelColor=1a1a1a)](https://zulko.github.io/moviepy/)
[![Edge TTS](https://img.shields.io/badge/Edge--TTS-voice-1a1a1a?style=flat&labelColor=1a1a1a)](https://github.com/rany2/edge-tts)
[![Docker](https://img.shields.io/badge/Docker-compose-1a1a1a?style=flat&logo=docker&logoColor=white&labelColor=1a1a1a)](https://www.docker.com/)
[![pnpm](https://img.shields.io/badge/pnpm-package%20mgr-1a1a1a?style=flat&logo=pnpm&logoColor=white&labelColor=1a1a1a)](https://pnpm.io/)
[![uv](https://img.shields.io/badge/uv-python%20mgr-1a1a1a?style=flat&logo=astral&logoColor=white&labelColor=1a1a1a)](https://docs.astral.sh/uv/)
[![Cost](https://img.shields.io/badge/cost-free%20tier-1a1a1a?style=flat&labelColor=1a1a1a)](#tech-stack)

</div>

---

## What is F88tball?

F88tball turns a finished football match into a ready-to-publish highlight video.
Give it a match and it builds an exciting narration written by an LLM, a real
voice (Edge-TTS), copyright-safe visuals (team crests, an animated scoreboard,
optional AI ambience), burned-in subtitles, and an automatic **private** upload
to YouTube. It also writes blog / X / Instagram / LinkedIn copy for the same
match.

Everything runs on **free tiers** (Groq, ESPN, Edge-TTS, FLUX images, local
embeddings), so the whole proof of concept costs nothing to run.

The web dashboard adds a World Cup 2026 calendar, a self-filling knockout
bracket, a FIFA power ranking of the 48 teams, a content library with bulk and
scheduled YouTube uploads, and an AI Lab (arXiv RAG, live finance news,
multi-agent routing). The UI ships in **English and Spanish** with light, dark
and colorblind themes.

## How it works (data flow)

```
ESPN / openfootball                    .env + profiles/<id>
 (matches, scorers,                    (team, language, voice,
  flags, calendar)                      providers, brand persona)
        |                                        |
        v                                        v
  match_monitor.py  ------ finished match ----> runner.py  (orchestration)
                                                  |
        +-----------------+-----------------+-----+-----------------+
        v                 v                 v                       v
   narrator.py      media_provider.py   voice_generator.py   content_generator.py
   (LLM narration   (crests, animated   (Edge-TTS voice +    (blog / X / IG /
    + match         scoreboard, FLUX     synced subtitles)    LinkedIn copy)
    character)       ambience)
        |                 |                 |
        v                 |                 |
   guardrail.py           |                 |
   (facts check +         |                 |
    LLM-as-judge,         |                 |
    regenerate if wrong)  |                 |
        +-----------------+-----------------+
                          v
                  video_assembler.py
                 (MoviePy + ffmpeg -> .mp4,
                  burned-in subtitles)
                          v
                  publishers.py
              (YouTube Data API v3 OAuth,
               uploads private by default)
```

Match data and brand config feed the orchestrator. The narration is fact-checked
by a guardrail (and regenerated if it invents a score) before the voice, visuals
and subtitles are composited into an MP4 and uploaded.

## Project structure

```
F88tball/
├── core/
│   ├── brand_config.py      BrandProfile: per-profile config (team, language, voice, persona)
│   ├── competitions.py      competition presets (La Liga, World Cup 2026, ...)
│   ├── voices.py            named broadcaster voice presets
│   ├── architecture.py      self-describing system map served to the UI
│   ├── llm/                 switchable LLMs: groq · gemini · cerebras · ollama (+ fallbacks)
│   └── tracing.py           LangSmith activation
├── pipeline/
│   ├── match_monitor.py     finished-match detection + Match / Goal model
│   ├── data_sources/        ESPN (default), API-Football, TheSportsDB, on-disk cache
│   ├── wc_calendar.py       World Cup 2026 schedule (openfootball)
│   ├── wc_bracket.py        self-filling knockout bracket
│   ├── power_ranking.py     FIFA power ranking of the 48 World Cup teams
│   ├── narrator.py          multi-language narration + match-character tone + metadata
│   ├── media_provider.py    visuals: crests · scoreboard/timeline · FLUX ambience
│   ├── voice_generator.py   Edge-TTS voice + synchronized subtitles
│   ├── video_assembler.py   MoviePy slideshow + audio + burned-in subtitles -> .mp4
│   ├── content_generator.py blog / X / Instagram / LinkedIn copy
│   ├── publishers.py        YouTube Data API v3 OAuth upload (private)
│   ├── runner.py            per-match orchestration (with guardrail)
│   └── tools/               finance (Finnhub) · arxiv_rag (Chroma) · graph_rag (NetworkX)
├── agents/
│   ├── guardrail.py         anti-hallucination: facts check + LLM-as-judge
│   └── graph.py             LangGraph supervisor routing specialised agents
├── api/server.py            FastAPI backend (profiles, matches, generate, rankings, ...)
├── frontend/                React 19 + Vite 7 + TypeScript dashboard (EN / ES, themes)
│   ├── public/              logo + favicons
│   └── src/                 pages, api client, i18n catalog, components
├── profiles/<id>/           profile.json + .env + tokens + output
├── scripts/                 background scheduler (launchd)
├── main.py                  CLI (fixtures, match, scheduler, report)
└── docker-compose.yml       backend + frontend (nginx)
```

## Tech stack

| Layer | Choice | Free tier |
|-------|--------|-----------|
| Text LLM | Groq (Llama 3.3 70B) plus Gemini / Cerebras / Ollama | yes |
| Orchestration | LangChain, LangGraph, LangSmith | 5k traces/mo |
| Football data | ESPN (default), API-Football, TheSportsDB | free |
| Images | FLUX (Together / FAL) then Cloudflare / HF / local | free tiers |
| Voice | Edge-TTS (no key) then Piper / gTTS | free |
| Video | MoviePy plus ffmpeg | local |
| RAG | arXiv plus Chroma plus BAAI/bge-small (local) | free |
| Graph RAG | LLMGraphTransformer plus NetworkX | free |
| Finance | Finnhub (plus yfinance) | 60 req/min |
| Frontend | React 19, Vite 7, TypeScript | local |
| Tooling | uv (Python), pnpm (Node), Docker | local |

## Quick start

You need Python 3.12 and Node 18+. Backend is managed with
[uv](https://docs.astral.sh/uv/), frontend with [pnpm](https://pnpm.io/).

### macOS / Linux

```bash
# 1. Backend
uv sync
cp .env.example .env          # add GROQ_API_KEY (free); ESPN needs no key
uv run uvicorn api.server:app --reload --port 5001

# 2. Frontend (new terminal)
cd frontend
pnpm install
pnpm run dev                  # http://localhost:5173
```

### Windows (PowerShell)

```powershell
# 1. Backend
uv sync
Copy-Item .env.example .env   # add GROQ_API_KEY (free); ESPN needs no key
uv run uvicorn api.server:app --reload --port 5001

# 2. Frontend (new terminal)
cd frontend
pnpm install
pnpm run dev                  # http://localhost:5173
```

Images (FLUX) and voice (Edge-TTS) need **no API key**. Open
`http://localhost:5173` and the dashboard talks to the backend on port 5001.

### Make shortcuts (macOS / Linux)

The Makefile wraps the steps above:

```bash
make install   # uv sync + pnpm install
make dev       # backend (:5001) + frontend (:5173) together — Ctrl+C stops both
make backend   # backend only
make frontend  # frontend only
make build     # production build of the frontend
make docker    # full stack in Docker (frontend :8080, backend :5001)
make clean     # remove generated artifacts
```

## CLI

```bash
python main.py --profile worldcup_es --fixtures              # today's matches
python main.py --profile worldcup_es --match 12345           # generate one video
python main.py --profile worldcup_es --scheduler             # auto-generate as matches finish
python main.py --profile worldcup_es --match 12345 --upload --social
```

## Docker

```bash
cp .env.example .env
docker compose up --build      # frontend :8080  ·  backend :5001
```

## Background scheduler (macOS)

Run the scheduler as a background service that auto-generates and uploads a
summary as each match finishes. It survives closing the terminal and the IDE,
restarts on crash, and starts at login.

```bash
bash scripts/f88ball_scheduler_ctl.sh install    # install and start
bash scripts/f88ball_scheduler_ctl.sh status     # is it running?
bash scripts/f88ball_scheduler_ctl.sh logs       # follow the log live
bash scripts/f88ball_scheduler_ctl.sh stop       # stop
bash scripts/f88ball_scheduler_ctl.sh uninstall  # remove
```

Logs at `profiles/worldcup_es/output/logs/scheduler.log`. The launchd label is
`com.f88ball.scheduler`, unique per app so multiple projects can each run their own.

## API keys

Required for a demo: `GROQ_API_KEY` (free). ESPN (the default data source) needs
no key. For YouTube upload: per-profile `profiles/<id>/tokens/client_secret.json`
(OAuth). Optional extras: `GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `TOGETHER_API_KEY`,
`LANGSMITH_API_KEY`, `FINNHUB_API_KEY`.

## Privacy and practice mode

`PRACTICE_MODE=true` (default) forces every YouTube upload to **private**. Set
`YOUTUBE_PRIVACY=private|unlisted|public` to change visibility once you are ready.
