"""
server.py — SynapseQuill FastAPI backend.

Endpoints (all under /api):
    GET    /api/health                         liveness
    GET    /api/config/global                  supported providers / models / privacy
    GET    /api/profiles                       list profiles
    POST   /api/profiles                       create a profile from the template
    GET    /api/profiles/{id}                  profile (secret-free)
    PATCH  /api/profiles/{id}                  update profile.json (whitelisted)
    GET    /api/profiles/{id}/matches          World Cup fixtures for a day
    GET    /api/profiles/{id}/content          previously generated content records
    POST   /api/profiles/{id}/generate         generate a match video (background)
    GET    /api/profiles/{id}/status           poll generation progress
    POST   /api/profiles/{id}/cancel           cooperative cancellation
    POST   /api/science/explain                arXiv-grounded science explanation
    POST   /api/finance/news                   live market summary for a ticker
    POST   /api/agents/route                   multi-agent supervisor routing

Background generation mirrors Synapse Core's pattern: a global `_running` dict
guarded by a lock, plus `_cancel_flags`, with `/generate` returning immediately
(202) and the frontend polling `/status`.
"""

import json
import shutil
import sys
import threading
import time
from pathlib import Path

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
from pipeline.match_monitor import MatchMonitor  # noqa: E402
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
_cancel_flags: dict[str, bool] = {}
_lock = threading.Lock()


# ── Request models ───────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    fixture_id: int
    do_video: bool = True
    do_upload: bool = False
    do_social: bool = False


class ProfileUpdate(BaseModel):
    updates: dict


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
    return {
        "llm_providers": ["groq", "gemini", "cerebras", "ollama"],
        "image_providers": ["pollinations", "cloudflare", "hf_inference", "local_diffusers"],
        "media_sources": ["stock", "graphics", "flux"],
        "tts_providers": ["edge", "gtts", "piper"],
        "languages": ["es", "en", "fr", "it"],
        "youtube_privacy": ["private", "unlisted", "public"],
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
    monitor = MatchMonitor(cfg.LEAGUE_ID, cfg.SEASON,
                          api_key=cfg.get_secret("APIFOOTBALL_KEY"))
    try:
        # An explicit ?day= always wins. Otherwise MATCH_MODE decides:
        #   today  -> fixtures of the current date (live competition)
        #   latest -> most recent finished matches (past seasons / demos)
        if day:
            matches = monitor.fixtures_on(day)
        elif cfg.MATCH_MODE == "today":
            matches = monitor.fixtures_on()
        else:
            matches = monitor.latest_finished()
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return [
        {
            "fixture_id": m.fixture_id, "status": m.status,
            "home": m.home, "away": m.away,
            "home_goals": m.home_goals, "away_goals": m.away_goals,
            "home_logo": m.home_logo, "away_logo": m.away_logo,
            "finished": m.is_finished, "scoreline": m.scoreline,
        }
        for m in matches
    ]


@app.get("/api/profiles/{profile_id}/content")
def get_content(profile_id: str):
    cfg = _profile_or_404(profile_id)
    records = []
    for f in sorted(cfg.CONTENT_DIR.glob("match_*.json"), reverse=True):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return records


# ── Generation (background) ──────────────────────────────────────────
def _run_generation(profile_id: str, req: GenerateRequest):
    def on_step(step: str, msg: str):
        with _lock:
            if profile_id in _running:
                _running[profile_id].update(step=step, message=msg)

    def check_cancel() -> bool:
        return _cancel_flags.get(profile_id, False)

    try:
        cfg = BrandProfile(profile_id)
        monitor = MatchMonitor(cfg.LEAGUE_ID, cfg.SEASON,
                              api_key=cfg.get_secret("APIFOOTBALL_KEY"))
        match = monitor.fixture(req.fixture_id)
        result = run_match(profile_id, match, on_step=on_step,
                          check_cancel=check_cancel,
                          do_video=req.do_video, do_upload=req.do_upload,
                          do_social=req.do_social)
        with _lock:
            _running[profile_id].update(state="done", result=result)
    except Exception as e:  # noqa: BLE001
        with _lock:
            _running[profile_id].update(state="error", message=str(e))
    finally:
        time.sleep(30)  # let the client read the final state
        with _lock:
            _running.pop(profile_id, None)
            _cancel_flags.pop(profile_id, None)


@app.post("/api/profiles/{profile_id}/generate", status_code=202)
def generate(profile_id: str, req: GenerateRequest):
    _profile_or_404(profile_id)
    with _lock:
        if profile_id in _running and _running[profile_id].get("state") == "running":
            raise HTTPException(status_code=409, detail="A generation is already running")
        _running[profile_id] = {"state": "running", "step": "start",
                                "message": "Starting...", "fixture_id": req.fixture_id}
        _cancel_flags[profile_id] = False
    threading.Thread(target=_run_generation, args=(profile_id, req), daemon=True).start()
    return {"ok": True, "message": "Generation started"}


@app.get("/api/profiles/{profile_id}/status")
def status(profile_id: str):
    with _lock:
        return _running.get(profile_id, {"state": "idle"})


@app.post("/api/profiles/{profile_id}/cancel")
def cancel(profile_id: str):
    with _lock:
        _cancel_flags[profile_id] = True
    return {"ok": True, "message": "Cancellation requested"}


# ── Advanced / expert feature endpoints ──────────────────────────────
class TopicRequest(BaseModel):
    topic: str
    language: str = "es"


class TickerRequest(BaseModel):
    ticker: str


class RouteRequest(BaseModel):
    request: str


@app.post("/api/science/explain")
def science_explain(body: TopicRequest):
    """Popular-science explanation grounded in arXiv RAG (advanced level)."""
    from pipeline.tools.arxiv_rag import explain
    try:
        return {"topic": body.topic, "explanation": explain(body.topic, language=body.language)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/finance/news")
def finance_news(body: TickerRequest):
    """Live market summary for a ticker (advanced level)."""
    from pipeline.tools.finance import market_summary
    try:
        return {"ticker": body.ticker, "summary": market_summary(body.ticker)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/agents/route")
def agents_route(body: RouteRequest):
    """Route a free-form content request through the multi-agent supervisor (expert level)."""
    from agents.graph import route_request
    try:
        return {"request": body.request, "result": route_request(body.request)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e


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
