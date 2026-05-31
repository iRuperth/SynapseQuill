"""
brand_config.py — per-profile configuration loader.

A "profile" is a content brand/channel living under `profiles/<id>/`:

    profiles/<id>/
    ├── profile.json      # public settings (team, language, style, voice, ...)
    ├── .env              # per-profile secrets (override the global .env)
    ├── tokens/           # YouTube OAuth tokens (youtube_token.pickle, client_secret.json)
    ├── prompts/          # system_preamble.txt — brand/persona text injected in every prompt
    └── output/{videos,images,content,logs}/

Config is merged in three layers (later wins):
    1. global  .env  (project root)
    2. profile .env  (profiles/<id>/.env)
    3. profile.json  (non-secret, public settings)

Secrets live ONLY in .env files, never in profile.json. `to_dict()` never
exposes secrets so it is safe to send to the frontend.

Mirrors the ChannelConfig pattern from the sister project "Synapse Core".
"""

import json
import os
from pathlib import Path

from dotenv import dotenv_values

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


def list_profiles() -> list[dict]:
    """Return a lightweight list of all profiles (id + name), skipping the template."""
    profiles = []
    if not PROFILES_DIR.exists():
        return profiles
    for entry in sorted(PROFILES_DIR.iterdir()):
        if not entry.is_dir() or entry.name == "profile_template":
            continue
        pj = entry / "profile.json"
        if not pj.exists():
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        profiles.append({
            "id": entry.name,
            "name": data.get("name", entry.name),
            "team": data.get("team", ""),
            "language": data.get("language", "es"),
        })
    return profiles


class BrandProfile:
    """Loads and exposes the configuration of a single content profile."""

    def __init__(self, profile_id: str):
        self.id = profile_id
        self.dir = PROFILES_DIR / profile_id
        if not self.dir.exists():
            raise ValueError(f"Profile '{profile_id}' not found at {self.dir}")

        # --- Layer 1+2: merge env files (profile .env wins over global) ---
        global_env = dotenv_values(PROFILES_DIR.parent / ".env")
        profile_env = dotenv_values(self.dir / ".env")
        self._env = {**global_env, **profile_env}

        # --- Layer 3: profile.json (public settings) ---
        pj = self.dir / "profile.json"
        self._json = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}

        self._setup_attributes()

    # ------------------------------------------------------------------
    def _env_get(self, key: str, default=None):
        """Look up a key in merged profile env, then os.environ, then default."""
        if key in self._env and self._env[key] not in (None, ""):
            return self._env[key]
        return os.environ.get(key, default)

    def _setup_attributes(self):
        j = self._json

        # --- Identity ---
        self.NAME = j.get("name", self.id)
        self.TEAM = j.get("team", "")            # favourite team to spotlight (optional)
        self.LANGUAGE = j.get("language", self._env_get("LANGUAGE", "es"))

        # --- Football competition ---
        # The .env wins so the competition can be switched globally without
        # editing each profile.json. A profile may still pin its own values by
        # setting competition.league_id / competition.season explicitly.
        comp = j.get("competition", {})
        self.LEAGUE_ID = int(comp.get("league_id") or self._env_get("APIFOOTBALL_LEAGUE", 140))
        self.SEASON = int(comp.get("season") or self._env_get("APIFOOTBALL_SEASON", 2023))
        # today -> current-date fixtures (live competition);
        # latest -> most recent finished matches (past seasons / demos).
        self.MATCH_MODE = (comp.get("mode") or self._env_get("MATCH_MODE", "latest")).lower()

        # --- LLM ---
        self.LLM_PROVIDER = j.get("llm_provider", self._env_get("LLM_PROVIDER", "groq"))

        # --- Voice / TTS ---
        voice = j.get("voice", {})
        self.TTS_PROVIDER = voice.get("provider", self._env_get("TTS_PROVIDER", "edge"))
        self.TTS_VOICE = voice.get("voice", self._env_get("TTS_VOICE", "es-ES-AlvaroNeural"))
        self.TTS_RATE = voice.get("rate", self._env_get("TTS_RATE", "+8%"))

        # --- Visual media ---
        media = j.get("media", {})
        sources = media.get("sources") or self._env_get("MEDIA_SOURCES", "stock,graphics,flux")
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        self.MEDIA_SOURCES = sources
        self.IMAGE_PROVIDER = media.get("image_provider", self._env_get("IMAGE_PROVIDER", "pollinations"))
        self.VISUAL_STYLE = j.get("style", {}).get("visual_style", "cinematic sports broadcast")

        # --- YouTube publish ---
        self.PRACTICE_MODE = str(self._env_get("PRACTICE_MODE", "true")).lower() == "true"
        self.YOUTUBE_PRIVACY = self._env_get("YOUTUBE_PRIVACY", "private")
        if self.PRACTICE_MODE:
            self.YOUTUBE_PRIVACY = "private"

        # --- Output dirs ---
        self.OUTPUT_DIR = self.dir / "output"
        self.VIDEO_DIR = self.OUTPUT_DIR / "videos"
        self.IMAGE_DIR = self.OUTPUT_DIR / "images"
        self.CONTENT_DIR = self.OUTPUT_DIR / "content"
        self.LOG_DIR = self.OUTPUT_DIR / "logs"
        for d in (self.VIDEO_DIR, self.IMAGE_DIR, self.CONTENT_DIR, self.LOG_DIR):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    @property
    def system_preamble(self) -> str:
        """Brand/persona text injected at the top of every generation prompt.

        Materialises the briefing requirement "add company/person info as a
        prompt to all generated content". Read from prompts/system_preamble.txt,
        falling back to the `persona` block in profile.json.
        """
        pf = self.dir / "prompts" / "system_preamble.txt"
        if pf.exists():
            return pf.read_text(encoding="utf-8").strip()
        persona = self._json.get("persona", {})
        if persona:
            parts = [persona.get("description", "")]
            if persona.get("tone"):
                parts.append(f"Tone: {persona['tone']}.")
            if persona.get("values"):
                parts.append(f"Values: {persona['values']}.")
            return " ".join(p for p in parts if p).strip()
        return ""

    @property
    def tokens_dir(self) -> Path:
        d = self.dir / "tokens"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_secret(self, key: str, default=None):
        """Read a secret (API key, token) from the merged env. Never serialised."""
        return self._env_get(key, default)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Public, secret-free representation safe to send to the frontend."""
        return {
            "id": self.id,
            "name": self.NAME,
            "team": self.TEAM,
            "language": self.LANGUAGE,
            "competition": {"league_id": self.LEAGUE_ID, "season": self.SEASON},
            "llm_provider": self.LLM_PROVIDER,
            "voice": {"provider": self.TTS_PROVIDER, "voice": self.TTS_VOICE, "rate": self.TTS_RATE},
            "media": {"sources": self.MEDIA_SOURCES, "image_provider": self.IMAGE_PROVIDER},
            "style": {"visual_style": self.VISUAL_STYLE},
            "youtube": {"practice_mode": self.PRACTICE_MODE, "privacy": self.YOUTUBE_PRIVACY},
            "has_system_preamble": bool(self.system_preamble),
        }

    def update_profile_json(self, updates: dict) -> None:
        """Deep-merge `updates` into profile.json and reload attributes.

        Only whitelisted top-level sections are accepted, to avoid writing junk.
        """
        allowed = {"name", "team", "language", "competition", "llm_provider",
                   "voice", "media", "style", "persona"}
        data = dict(self._json)
        for key, val in updates.items():
            if key not in allowed:
                continue
            if isinstance(val, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **val}
            else:
                data[key] = val
        pj = self.dir / "profile.json"
        pj.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._json = data
        self._setup_attributes()
