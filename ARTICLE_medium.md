# One Content Engine, Any Topic, Any Brand: Meet SynapseQuill

### A configurable engine that turns a subject into a narrated, subtitled, ready-to-upload video and the social copy to go with it. Its live showcase is the World Cup 2026, but it points at any topic you give it.

There is a strange gap in content production. The thing happens, the facts are known within seconds, and yet the video, the recap and the social posts still take hours of manual editing to ship. By the time it is published, the moment has cooled.

SynapseQuill closes that gap. Give it a subject and a brand profile and it returns a publish-ready video: an energetic spoken narration, a real voice, copyright-safe visuals, karaoke-style burned-in subtitles, and an optional private upload straight to YouTube. It also drafts the blog, X, Instagram and LinkedIn copy to match. The whole thing runs on free tiers, so the proof of concept costs nothing to operate.

The key idea is that the engine is **retargetable**. A brand profile carries the voice, language, persona, visual style and subject area, so the same pipeline that covers a football match can just as easily cover a product launch, a science explainer or a company announcement. To make that concrete, the project ships a fully built showcase: an automated highlight and recap machine for the **FIFA World Cup 2026**. Sports is an ideal proving ground because the facts are crisp and verifiable, which makes the engine's fact-checking visible and measurable. But the World Cup is the demo, not the ceiling.

This article walks through what it does from a user's seat, then opens the hood: the pipeline, the architecture, and the design decisions that make it work.

**Repo:** [github.com/iRuperth/SynapseQuill](https://github.com/iRuperth/SynapseQuill) · **Published on Medium:** [read the article](https://medium.com/@devrup404/one-content-engine-any-topic-any-brand-meet-synapsequill-6a18b5d463fd)

---

## What it actually does

SynapseQuill is two things at once: a content engine and a dashboard wrapped around it. Here is what you can do from the web app.

**Make a video about any topic.** This is the general-purpose mode. Type a subject you want explained, or paste your own text to narrate, choose a format (vertical reel at 1080x1920 or horizontal YouTube at 1920x1080), and generate a clean narrated video with a backdrop, a pulsing logo and subtitles. When you paste your own text, the narration is grounded strictly in that text and will not invent anything around it. This is the path that works for any company or subject.

**Write multi-platform social copy.** Type any topic, pick an audience (general, outreach, kids, technical, SEO) and a language, and get publish-ready copy for a blog post, an X post, an Instagram caption and a LinkedIn post, each tuned to its platform's length and tone.

**Generate a match video (the World Cup showcase).** Pick a finished match, choose a format, and hit generate. The dashboard shows live progress through each stage: finding scorers, writing narration, verifying the data, generating the title and tags, creating visuals, recording the voice and subtitles, editing the video, drafting social text, and uploading. The output lands in your library. This is the same engine as the topic mode, with sports-specific data and graphics layered on top.

**Build a match-day digest.** Combine several games from a single day into one recap video, with an optional angle for the narration.

**Browse the tournament.** A live World Cup 2026 calendar with a countdown, a self-filling knockout bracket, and a FIFA power ranking of all 48 teams.

**Run the AI Lab.** Three advanced tools: a science explainer backed by retrieval over arXiv papers plus a knowledge graph, live market news for a given ticker, and a multi-agent router that sends free-form requests to the right specialist.

**Manage the library.** Everything you generate is collected in one place, with bulk uploads and scheduled uploads to YouTube.

The interface ships in **English and Spanish**, with light, dark and colorblind themes.

---

## The pipeline, stage by stage

The heart of the project is the orchestrator in `pipeline/runner.py`. A match flows through it like this.

**1. Enrich.** If the data source is missing goalscorers or minutes, it backfills them from ESPN.

**2. Narrate.** An LLM writes the narration from a structured block of match facts (teams, score, goals, cards) plus a brand persona. The result is an excited, play-by-play style script, sized for the chosen format.

**3. Guardrail.** This is the part worth lingering on. Before anything is rendered, the narration is fact-checked against the real match data in two passes: a deterministic rule check (the scoreline has to match exactly) and an LLM-as-judge pass (facts, language, tone). If the narration invents a score, a wrong scorer or the wrong card color, it is rejected and regenerated, with feedback, up to three times. Sports is the perfect domain for this because the facts are crisp and verifiable, which makes hallucination visible and catchable.

**4. Polish.** A pass of deterministic language fixes plus an optional rewrite for natural spoken flow, with the facts re-verified afterward so the polish cannot quietly change them.

**5. Metadata.** The LLM generates a YouTube title, description and tags, grounded in the narration and the match.

**6. Visuals.** Team crests, an animated scoreboard that counts up, a goal timeline that slides in row by row, and an optional AI-generated crowd backdrop. No copyrighted footage, everything is generated or composited.

**7. Voice and subtitles.** Text-to-speech produces the audio plus word-level timing. The default is a free, keyless Spanish male voice with an energetic broadcaster preset (faster rate, lifted pitch). Subtitles are then locked word by word to the audio for a karaoke effect.

**8. Assemble.** MoviePy and ffmpeg composite the backdrop, animated graphics, optional background music and burned-in subtitles into an H.264 MP4 in the chosen aspect ratio.

**9. Publish.** An optional OAuth upload to YouTube, **private by default**. If the narration ever failed the guardrail, auto-upload is blocked and the video waits in the library for a human to review.

The explainer-video path is a lighter version of the same flow: narrate, polish, metadata, backdrop, voice, assemble. No scoreboard, no match guardrail, just a clean clip.

---

## Architecture

```
ESPN / openfootball                 .env + profiles/<id>
 (matches, scorers,                 (team, language, voice,
  flags, calendar)                   providers, brand persona)
        |                                     |
        v                                     v
  match_monitor.py  --- finished match ---> runner.py  (orchestration)
                                              |
     +-------------+-------------+------------+------------+
     v             v             v                         v
  narrator    media_provider  voice_generator      content_generator
  (LLM)       (crests, score)  (voice + subs)       (blog / X / IG / LinkedIn)
     |
     v
  guardrail  (facts + LLM-as-judge, regenerate if wrong)
     |
     v
  video_assembler  (MoviePy + ffmpeg -> .mp4)
     |
     v
  publishers  (YouTube Data API v3, private by default)
```

A few design choices shape the whole codebase:

**Multi-tenant brand profiles.** This is what makes the engine generic. Each profile lives under `profiles/<id>/` with its own config, secrets, brand persona, voice, language, visual style and subject presets, plus its own OAuth tokens and output directory. Swap the profile and you retarget the entire pipeline: the same code that narrates a World Cup match will narrate a fintech product update or a museum exhibit, in that brand's voice. The World Cup profile is simply the one shipped fully wired up as a reference.

**Pluggable everything.** The LLM provider (Groq, Gemini, Cerebras, Ollama), the data source (ESPN, API-Football, TheSportsDB), the voice engine (Edge-TTS, ElevenLabs, gTTS, Piper) and the image provider (FLUX across several backends) all sit behind small abstractions with automatic fallback and key rotation when a free tier returns a quota error.

**Background jobs with polling.** Generation endpoints return immediately and the frontend polls a status endpoint for live progress, so the UI stays responsive while a video renders.

**A self-describing system.** The app serves its own architecture map to an in-app page, so you can explore how it works from inside the product, in either a simple or technical view.

---

## The stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Orchestration | LangChain, LangGraph, LangSmith |
| Text LLM | Groq (Llama 3.3 70B) with Gemini, Cerebras, Ollama fallbacks |
| Football data | ESPN (default), API-Football, TheSportsDB |
| Voice | Edge-TTS (keyless default), ElevenLabs, gTTS, Piper |
| Images | FLUX.1-schnell across Cloudflare, HuggingFace, local |
| Video | MoviePy plus ffmpeg, H.264 / AAC |
| RAG | arXiv plus Chroma plus a local embedding model |
| Graph RAG | LLMGraphTransformer plus NetworkX |
| Finance | Finnhub plus yfinance |
| Frontend | React 19, Vite 7, TypeScript, Tailwind CSS 4 |
| Tooling | uv (Python), pnpm (Node), Docker Compose |

Every external service was chosen for its free tier. That is a deliberate constraint, not an accident: it forces the design to handle quota limits, provider failover and key rotation, which is exactly the resilience a production system needs anyway.

---

## Project structure

```
SynapseQuill/
├── core/         config, switchable LLMs, voices, competitions, system map
├── pipeline/     the engine: monitor, data sources, narrator, media,
│                 voice, video assembler, content, publishers, runner
├── agents/       guardrail (anti-hallucination) + LangGraph supervisor
├── api/          FastAPI backend (profiles, matches, generate, rankings, lab)
├── frontend/     React 19 + Vite 7 dashboard (EN / ES, themes)
├── profiles/     per-tenant config, secrets, tokens, output
├── scripts/      background scheduler
├── main.py       CLI (fixtures, match, scheduler, report)
└── docker-compose.yml
```

There is also a CLI for the people who would rather not touch a browser:

```bash
python main.py --profile worldcup_es --fixtures        # today's matches
python main.py --profile worldcup_es --match 12345     # generate one video
python main.py --profile worldcup_es --scheduler       # auto-generate as matches finish
```

The scheduler can run as a background service that watches for finished matches and generates and uploads a recap as each one ends, surviving terminal close and restarting on crash.

---

## Try it

You need Python 3.12 and Node 18+. The only key required for a demo is a free Groq key; ESPN, the default data source, needs none, and voice and images work with no key at all.

```bash
uv sync
cp .env.example .env          # add GROQ_API_KEY (free)
uv run uvicorn api.server:app --reload --port 5001

cd frontend
pnpm install
pnpm run dev                  # http://localhost:5173
```

Or the whole stack in one command with Docker:

```bash
docker compose up --build     # frontend :8080, backend :5001
```

---

## Get involved

SynapseQuill is open source and there is plenty of room to build on it: new brand profiles for domains beyond sports, more data sources, new voice and image backends, richer animated graphics, additional output platforms, or sharper guardrails. If any of that sounds fun, the repo is the place to start.

⭐ **Star, fork and open a pull request:** [github.com/iRuperth/SynapseQuill](https://github.com/iRuperth/SynapseQuill)

Issues, ideas and feedback are all welcome. If you build something with it, I would love to see it.
