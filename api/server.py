"""
server.py — SynapseQuill FastAPI backend.

Endpoints (all under /api):
    GET    /api/health                         liveness
    GET    /api/config/global                  supported providers / models / privacy
    GET    /api/profiles                       list profiles
    POST   /api/profiles                       create a profile from the template
    GET    /api/profiles/{id}                  profile (secret-free)
    PATCH  /api/profiles/{id}                  update profile.json (whitelisted)
    GET    /api/profiles/{id}/matches          fixtures for a day (any league)
    POST   /api/profiles/{id}/content/freeform multi-platform text for a free topic
    GET    /api/profiles/{id}/content          previously generated content records
    POST   /api/profiles/{id}/generate         generate a match video (background)
    GET    /api/profiles/{id}/status           poll generation progress
    POST   /api/profiles/{id}/cancel           cooperative cancellation
    GET    /api/science/topics                 suggested sports-science topics
    POST   /api/science/explain                arXiv + Graph RAG science explanation
    POST   /api/finance/news                   live market summary for a ticker
    POST   /api/agents/route                   multi-agent supervisor routing
    GET    /api/profiles/{id}/lab/history       saved Lab / free-topic requests
    DELETE /api/profiles/{id}/lab/history/{name} delete one history record

Background generation mirrors Synapse Core's pattern: a global `_running` dict
guarded by a lock, plus `_cancel_flags`, with `/generate` returning immediately
(202) and the frontend polling `/status`.
"""

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

# Use the pure-Python protobuf parser so ChromaDB's opentelemetry dependency
# (old generated *_pb2.py) works under modern protobuf. Must be set before any
# protobuf-backed import. See pipeline/tools/arxiv_rag.py for the full rationale.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

load_dotenv(ROOT / ".env")

from core.tracing import setup_tracing  # noqa: E402

setup_tracing()

from core.brand_config import PROFILES_DIR, BrandProfile, list_profiles  # noqa: E402
from pipeline.data_sources import get_data_source  # noqa: E402
from pipeline.runner import run_match  # noqa: E402

app = FastAPI(title="SynapseQuill API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Background task state ────────────────────────────────────────────
_running: dict[str, dict] = {}
_cancel_flags: dict[str, int] = {}     # profile_id -> run_id requested to cancel
_run_counter = 0                       # monotonically increasing run identity
_lock = threading.Lock()


# ── Request models ───────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    fixture_id: int
    do_video: bool = True
    do_upload: bool = False
    do_social: bool = False
    format: str = "reel"          # reel | youtube


class DigestRequest(BaseModel):
    day: str | None = None        # YYYY-MM-DD, default = latest match day
    format: str = "reel"          # reel | youtube


class ProfileUpdate(BaseModel):
    updates: dict


class FreeformRequest(BaseModel):
    """Essential-level: free topic the user provides, any platform/audience."""
    topic: str
    audience: str = ""
    platforms: list[str] | None = None     # default: all (blog/x/ig/linkedin)
    language: str | None = None            # default: profile language
    extra: str = ""                        # optional extra guidance
    provider: str | None = None            # optional LLM override


class CreateProfile(BaseModel):
    id: str
    name: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────
def _profile_or_404(profile_id: str) -> BrandProfile:
    try:
        return BrandProfile(profile_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── Health / config ──────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True, "service": "synapsequill"}


@app.get("/api/config/global")
def global_config():
    from core.competitions import options as competition_options
    from core.voices import options as voice_options
    return {
        "llm_providers": ["groq", "gemini", "cerebras", "ollama"],
        "image_providers": ["together", "fal", "pollinations", "cloudflare", "hf_inference"],
        "media_sources": ["stock", "graphics", "flux"],
        "tts_providers": ["edge", "gtts", "piper"],
        "languages": ["es", "en", "fr", "it"],
        "youtube_privacy": ["private", "unlisted", "public"],
        "competitions": competition_options(),
        "voices": voice_options(),
    }


# ── Profiles CRUD ────────────────────────────────────────────────────
@app.get("/api/profiles")
def get_profiles():
    return list_profiles()


@app.post("/api/profiles", status_code=201)
def create_profile(body: CreateProfile):
    dest = PROFILES_DIR / body.id
    if dest.exists():
        raise HTTPException(status_code=409, detail="Profile already exists")
    template = PROFILES_DIR / "profile_template"
    shutil.copytree(template, dest)
    cfg = BrandProfile(body.id)
    if body.name:
        cfg.update_profile_json({"name": body.name})
    return cfg.to_dict()


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str):
    return _profile_or_404(profile_id).to_dict()


@app.patch("/api/profiles/{profile_id}")
def update_profile(profile_id: str, body: ProfileUpdate):
    cfg = _profile_or_404(profile_id)
    cfg.update_profile_json(body.updates)
    return cfg.to_dict()


# ── Matches ──────────────────────────────────────────────────────────
@app.get("/api/profiles/{profile_id}/matches")
def get_matches(profile_id: str, day: str | None = None):
    cfg = _profile_or_404(profile_id)
    try:
        source = get_data_source(cfg)          # may raise ValueError (bad provider)
        # An explicit ?day= always wins. Otherwise MATCH_MODE decides:
        #   today  -> fixtures of the current date (live competition)
        #   latest -> most recent finished matches (past seasons / demos)
        if day:
            matches = source.fixtures_on(day)
        elif cfg.MATCH_MODE == "today":
            matches = source.fixtures_on()
        else:
            matches = source.latest_finished()
    except Exception as e:  # noqa: BLE001 — surface any data-layer failure as 502
        raise HTTPException(status_code=502, detail=str(e)) from e
    return [
        {
            "fixture_id": m.fixture_id, "status": m.status,
            "home": m.home, "away": m.away,
            "home_goals": m.home_goals, "away_goals": m.away_goals,
            "home_logo": m.home_logo, "away_logo": m.away_logo,
            "finished": m.is_finished, "scoreline": m.scoreline,
            "competition": m.competition, "date": m.date,
        }
        for m in matches
    ]


@app.get("/api/profiles/{profile_id}/matches/{fixture_id}")
def get_match_detail(profile_id: str, fixture_id: str):
    """Full detail of a single match: scorers, cards, venue, date."""
    cfg = _profile_or_404(profile_id)
    try:
        source = get_data_source(cfg)
        m = source.fixture(fixture_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "fixture_id": m.fixture_id, "status": m.status, "finished": m.is_finished,
        "home": m.home, "away": m.away,
        "home_goals": m.home_goals, "away_goals": m.away_goals,
        "home_logo": m.home_logo, "away_logo": m.away_logo,
        "scoreline": m.scoreline, "competition": m.competition,
        "date": m.date, "venue": m.venue, "city": m.city, "country": m.country,
        "goals": [
            {"player": g.player, "team": g.team, "minute": g.minute,
             "kind": g.kind, "description": g.description}
            for g in m.goals
        ],
        "cards": [
            {"player": c.player, "team": c.team, "minute": c.minute, "color": c.color}
            for c in m.cards
        ],
    }


@app.post("/api/profiles/{profile_id}/content/freeform")
def freeform_content(profile_id: str, body: FreeformRequest):
    """Generate multi-platform text from a free topic + audience (essential level).

    Uses the profile's brand/persona system_preamble and language by default, so
    the output is personalised exactly like the match-based content path.
    """
    cfg = _profile_or_404(profile_id)
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="A 'topic' is required")
    from pipeline.content_generator import generate_freeform
    try:
        content = generate_freeform(
            body.topic,
            audience=body.audience,
            language=body.language or cfg.LANGUAGE,
            platforms=body.platforms,
            system_preamble=cfg.system_preamble,
            extra=body.extra,
            provider=body.provider or cfg.LLM_PROVIDER,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e
    # Persist to the Lab history. content is {platform: text}; store it as the
    # result (joined for the list preview) plus the structured map in meta.
    result_text = "\n\n".join(f"[{p}]\n{t}" for p, t in (content or {}).items())
    _save_lab_history(profile_id, "freeform", body.topic, result_text,
                      {"audience": body.audience, "language": body.language,
                       "platforms": body.platforms, "content": content})
    return {"topic": body.topic, "audience": body.audience, "content": content}


@app.get("/api/profiles/{profile_id}/content")
def get_content(profile_id: str):
    cfg = _profile_or_404(profile_id)
    records = []
    # Per-match videos and daily digests both live as JSON + .mp4 records.
    files = sorted(cfg.CONTENT_DIR.glob("match_*.json"), reverse=True) + \
        sorted(cfg.CONTENT_DIR.glob("digest_*.json"), reverse=True)
    for f in files:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        # The .mp4 sits next to its JSON with the same stem.
        rec["id"] = f.stem          # stable id for playback + deletion
        vid = cfg.VIDEO_DIR / f"{f.stem}.mp4"
        if vid.exists():
            rec["video_url"] = f"/api/profiles/{profile_id}/video/{f.stem}"
        records.append(rec)
    return records


@app.delete("/api/profiles/{profile_id}/content/{name}")
def delete_content(profile_id: str, name: str):
    """Delete a generated item (its JSON, .mp4 and image folder)."""
    cfg = _profile_or_404(profile_id)
    # Guard against path traversal: only allow our own stems.
    if not name.startswith(("match_", "digest_")) or "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid id")
    removed = []
    for path in (cfg.CONTENT_DIR / f"{name}.json", cfg.VIDEO_DIR / f"{name}.mp4"):
        if path.exists():
            path.unlink()
            removed.append(path.name)
    # The per-item image folder is named after the stem (e.g. match_<id>).
    img_folder = cfg.IMAGE_DIR / name
    if img_folder.is_dir():
        shutil.rmtree(img_folder, ignore_errors=True)
    if not removed:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True, "removed": removed}


@app.get("/api/profiles/{profile_id}/video/{name}")
def get_video(profile_id: str, name: str):
    """Stream a generated .mp4 (match or digest) so the frontend can play it."""
    cfg = _profile_or_404(profile_id)
    # Accept both a bare fixture id (legacy) and a full stem (match_<id>/digest_<...>).
    stem = name if name.startswith(("match_", "digest_")) else f"match_{name}"
    vid = cfg.VIDEO_DIR / f"{stem}.mp4"
    if not vid.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(vid, media_type="video/mp4")


class PublishRequest(BaseModel):
    fixture_id: int
    privacy: str = "private"        # private | unlisted | public


@app.post("/api/profiles/{profile_id}/publish")
def publish_video(profile_id: str, body: PublishRequest):
    """Upload an already-generated video to YouTube with the chosen privacy.

    Returns the watch URL on success. Reports a clear error if OAuth is not
    configured for the profile.
    """
    cfg = _profile_or_404(profile_id)
    vid = cfg.VIDEO_DIR / f"match_{body.fixture_id}.mp4"
    if not vid.exists():
        raise HTTPException(status_code=404, detail="Generate the video first")

    record_path = cfg.CONTENT_DIR / f"match_{body.fixture_id}.json"
    record = {}
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
    meta = record.get("metadata") or {"title": record.get("scoreline", "Match"),
                                       "description": "", "tags": []}

    # Practice mode forces private regardless of the requested privacy.
    privacy = "private" if cfg.PRACTICE_MODE else body.privacy
    try:
        from pipeline.publishers import upload_youtube
        cfg.YOUTUBE_PRIVACY = privacy
        url = upload_youtube(cfg, vid, meta)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"YouTube upload failed: {e}") from e

    # Persist the resulting URL back into the content record.
    record["youtube_url"] = url
    record["youtube_privacy"] = privacy
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "youtube_url": url, "privacy": privacy}


# Progress percentage per pipeline step, so the frontend can show a bar.
_STEP_PROGRESS = {
    "start": 2, "enrich": 8, "narrate": 22, "guardrail": 38,
    "metadata": 48, "media": 62, "voice": 74, "video": 88,
    "social": 93, "upload": 97, "done": 100,
}


# ── Generation (background) ──────────────────────────────────────────
def _run_generation(profile_id: str, req: GenerateRequest, run_id: int):
    def _is_current() -> bool:
        # Only the run that still owns the slot may touch its state.
        return _running.get(profile_id, {}).get("run_id") == run_id

    def on_step(step: str, msg: str):
        with _lock:
            if _is_current():
                _running[profile_id].update(
                    step=step, message=msg,
                    progress=_STEP_PROGRESS.get(step,
                             _running[profile_id].get("progress", 0)),
                )

    def check_cancel() -> bool:
        return _cancel_flags.get(profile_id) == run_id

    try:
        cfg = BrandProfile(profile_id)
        source = get_data_source(cfg)
        match = source.fixture(req.fixture_id)
        result = run_match(profile_id, match, on_step=on_step,
                          check_cancel=check_cancel,
                          do_video=req.do_video, do_upload=req.do_upload,
                          do_social=req.do_social, video_format=req.format)
        with _lock:
            if _is_current():
                _running[profile_id].update(state="done", result=result)
    except Exception as e:  # noqa: BLE001
        with _lock:
            if _is_current():
                _running[profile_id].update(state="error", message=str(e))
    finally:
        time.sleep(30)  # let the client read the final state
        with _lock:
            # Only clear if this run still owns the slot (a newer run may have
            # replaced it in the meantime).
            if _is_current():
                _running.pop(profile_id, None)
                if _cancel_flags.get(profile_id) == run_id:
                    _cancel_flags.pop(profile_id, None)


@app.post("/api/profiles/{profile_id}/generate", status_code=202)
def generate(profile_id: str, req: GenerateRequest):
    global _run_counter
    _profile_or_404(profile_id)
    with _lock:
        if profile_id in _running and _running[profile_id].get("state") == "running":
            raise HTTPException(status_code=409, detail="A generation is already running")
        _run_counter += 1
        run_id = _run_counter
        _running[profile_id] = {"state": "running", "step": "start", "progress": 0,
                                "message": "Starting...", "fixture_id": req.fixture_id,
                                "run_id": run_id}
        _cancel_flags.pop(profile_id, None)
    try:
        threading.Thread(target=_run_generation, args=(profile_id, req, run_id),
                         daemon=True).start()
    except Exception as e:  # noqa: BLE001 — thread creation can fail (resource limits)
        # Release the slot we just published so the profile isn't stuck on
        # "running" forever (the worker that owns cleanup never started).
        with _lock:
            if _running.get(profile_id, {}).get("run_id") == run_id:
                _running.pop(profile_id, None)
        raise HTTPException(status_code=503,
                            detail=f"Could not start generation: {e}") from e
    return {"ok": True, "message": "Generation started"}


def _run_digest(profile_id: str, req: DigestRequest, run_id: int):
    def _is_current() -> bool:
        return _running.get(profile_id, {}).get("run_id") == run_id

    def on_step(step: str, msg: str):
        with _lock:
            if _is_current():
                _running[profile_id].update(
                    step=step, message=msg,
                    progress=_STEP_PROGRESS.get(step, _running[profile_id].get("progress", 0)))

    def check_cancel() -> bool:
        return _cancel_flags.get(profile_id) == run_id

    try:
        from pipeline.digest import run_daily_digest
        cfg = BrandProfile(profile_id)
        day = req.day
        if not day:
            # Default to the most recent finished match day.
            src = get_data_source(cfg)
            latest = src.latest_finished(limit=1)
            day = latest[0].date if latest else None
        if not day:
            raise RuntimeError("No match day available")
        result = run_daily_digest(profile_id, day, req.format,
                                  on_step=on_step, check_cancel=check_cancel)
        with _lock:
            if _is_current():
                _running[profile_id].update(state="done", result=result)
    except Exception as e:  # noqa: BLE001
        with _lock:
            if _is_current():
                _running[profile_id].update(state="error", message=str(e))
    finally:
        time.sleep(30)
        with _lock:
            if _is_current():
                _running.pop(profile_id, None)
                _cancel_flags.pop(profile_id, None)


@app.post("/api/profiles/{profile_id}/digest", status_code=202)
def generate_digest(profile_id: str, req: DigestRequest):
    global _run_counter
    _profile_or_404(profile_id)
    with _lock:
        if profile_id in _running and _running[profile_id].get("state") == "running":
            raise HTTPException(status_code=409, detail="A generation is already running")
        _run_counter += 1
        run_id = _run_counter
        _running[profile_id] = {"state": "running", "step": "start", "progress": 0,
                                "message": "Preparando resumen del día...", "run_id": run_id}
        _cancel_flags.pop(profile_id, None)
    try:
        threading.Thread(target=_run_digest, args=(profile_id, req, run_id),
                         daemon=True).start()
    except Exception as e:  # noqa: BLE001
        with _lock:
            if _running.get(profile_id, {}).get("run_id") == run_id:
                _running.pop(profile_id, None)
        raise HTTPException(status_code=503, detail=f"Could not start digest: {e}") from e
    return {"ok": True, "message": "Digest started"}


@app.get("/api/worldcup/calendar")
def worldcup_calendar():
    """FIFA World Cup 2026 schedule grouped by day (openfootball, free)."""
    from pipeline.wc_calendar import calendar_summary
    try:
        return calendar_summary()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/profiles/{profile_id}/status")
def status(profile_id: str):
    with _lock:
        # Return a copy: the worker thread mutates the live dict during on_step.
        return dict(_running.get(profile_id, {"state": "idle"}))


@app.post("/api/profiles/{profile_id}/cancel")
def cancel(profile_id: str):
    with _lock:
        # Cancel only the run that currently owns the slot (by run identity).
        cur = _running.get(profile_id, {})
        if cur.get("state") == "running" and "run_id" in cur:
            _cancel_flags[profile_id] = cur["run_id"]
    return {"ok": True, "message": "Cancellation requested"}


# ── Advanced / expert feature endpoints ──────────────────────────────
class TopicRequest(BaseModel):
    topic: str
    language: str = "es"
    use_graph: bool = True       # also use the knowledge-graph context (Graph RAG)
    profile_id: str | None = None   # whose history to log this under


class TickerRequest(BaseModel):
    ticker: str
    profile_id: str | None = None


class RouteRequest(BaseModel):
    request: str
    profile_id: str | None = None


# ── Laboratorio IA / free-topic request history ──────────────────────
_LAB_SEQ = 0
_LAB_SEQ_LOCK = threading.Lock()


def _save_lab_history(profile_id: str | None, kind: str, prompt: str,
                      result: str, meta: dict | None = None) -> None:
    """Persist one Lab/free-topic request+response as a JSON record.

    Best-effort: a logging failure must never break the actual feature, so all
    errors are swallowed. Records live in the profile's output/lab dir, one file
    per request, newest-first by the monotonic sequence in the filename.
    """
    if not profile_id:
        return
    try:
        cfg = BrandProfile(profile_id)
    except Exception:  # noqa: BLE001 — unknown profile: just skip logging
        return
    global _LAB_SEQ
    with _LAB_SEQ_LOCK:
        _LAB_SEQ += 1
        seq = _LAB_SEQ
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"lab_{kind}_{stamp}_{seq:04d}"
    record = {
        "id": name,
        "kind": kind,                 # science | finance | agents | freeform
        "prompt": prompt,
        "result": result,
        "meta": meta or {},
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        (cfg.LAB_DIR / f"{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


@app.get("/api/profiles/{profile_id}/lab/history")
def lab_history(profile_id: str):
    """Return the saved Laboratorio IA / free-topic requests, newest first."""
    cfg = _profile_or_404(profile_id)
    records = []
    for f in sorted(cfg.LAB_DIR.glob("lab_*.json"), reverse=True):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records


@app.delete("/api/profiles/{profile_id}/lab/history/{name}")
def delete_lab_history(profile_id: str, name: str):
    """Delete one saved Lab/free-topic record."""
    cfg = _profile_or_404(profile_id)
    if not name.startswith("lab_") or "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid id")
    path = cfg.LAB_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    path.unlink()
    return {"ok": True}


# Suggested arXiv topics that tie the scientific RAG to this project's sports
# domain — the frontend offers these as one-click examples.
_SCIENCE_TOPICS = [
    "expected goals (xG) models in football",
    "machine learning for football tactics analysis",
    "biomechanics of sprinting and injury prevention in soccer",
    "player tracking and computer vision in team sports",
    "deep learning for sports video highlight detection",
]


@app.get("/api/science/topics")
def science_topics():
    """Suggested sports-science arXiv topics for the science RAG (advanced level)."""
    return {"topics": _SCIENCE_TOPICS}


@app.post("/api/science/explain")
def science_explain(body: TopicRequest):
    """Popular-science explanation grounded in arXiv RAG + optional Graph RAG."""
    from pipeline.tools.arxiv_rag import explain
    try:
        explanation = explain(body.topic, language=body.language,
                              use_graph=body.use_graph)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e
    _save_lab_history(body.profile_id, "science", body.topic, explanation,
                      {"language": body.language, "use_graph": body.use_graph})
    return {"topic": body.topic, "explanation": explanation}


@app.post("/api/finance/news")
def finance_news(body: TickerRequest):
    """Live market summary for a ticker (advanced level)."""
    from pipeline.tools.finance import market_summary
    try:
        summary = market_summary(body.ticker)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e
    _save_lab_history(body.profile_id, "finance", body.ticker, summary)
    return {"ticker": body.ticker, "summary": summary}


@app.post("/api/agents/route")
def agents_route(body: RouteRequest):
    """Route a free-form content request through the multi-agent supervisor (expert level)."""
    from agents.graph import route_request
    try:
        result = route_request(body.request)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e
    _save_lab_history(body.profile_id, "agents", body.request, result)
    return {"request": body.request, "result": result}


# ── Serve built frontend (production / Docker) ───────────────────────
_DIST = ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        target = _DIST / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=5001, reload=True)
