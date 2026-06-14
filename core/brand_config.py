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
        # A named preset (set from the frontend) is the friendly way to switch
        # between "La Liga" and "World Cup". If the profile names a competition
        # preset, it wins; otherwise fall back to the raw .env values.
        from core.competitions import DEFAULT as _DEFAULT_COMP
        from core.competitions import get as _comp_get
        comp = j.get("competition", {})
        self.COMPETITION = comp.get("preset") or self._env_get("COMPETITION", "")
        preset = _comp_get(self.COMPETITION) if self.COMPETITION else {}

        self.DATA_PROVIDER = (preset.get("provider")
                              or comp.get("provider")
                              or self._env_get("DATA_PROVIDER", "espn")).lower()
        self.LEAGUE_ID = int(preset.get("league_id")
                             or comp.get("league_id")
                             or self._env_get("APIFOOTBALL_LEAGUE", 140))
        self.SEASON = int(preset.get("season")
                          or comp.get("season")
                          or self._env_get("APIFOOTBALL_SEASON", 2023))
        self.MATCH_MODE = (preset.get("mode") or comp.get("mode")
                           or self._env_get("MATCH_MODE", "latest")).lower()
        # ESPN league slug (esp.1 = La Liga, fifa.world = World Cup) from preset.
        self.ESPN_SLUG = (preset.get("espn_slug")
                          or comp.get("espn_slug")
                          or self._env_get("ESPN_LEAGUE_SLUG", "esp.1"))
        # TheSportsDB league id (World Cup = 4429) may come from the preset.
        self._tsdb_league = (preset.get("tsdb_league")
                             or self._env_get("THESPORTSDB_LEAGUE", "4429"))
        if not self.COMPETITION:
            self.COMPETITION = _DEFAULT_COMP

        # --- LLM ---
        self.LLM_PROVIDER = j.get("llm_provider", self._env_get("LLM_PROVIDER", "groq"))
        # The guardrail judge should be a DIFFERENT model than the narrator:
        # a model re-reading its own prose tends to miss its own mistakes.
        # Falls back to the narrator's provider when not set.
        self.JUDGE_PROVIDER = j.get("judge_provider",
                                    self._env_get("JUDGE_PROVIDER",
                                                  self.LLM_PROVIDER))

        # --- Voice / TTS ---
        # A named voice preset (man/woman x ES/EN) is the friendly choice; it
        # resolves to an Edge-TTS voice id and rate. Explicit voice/rate still win.
        from core.voices import DEFAULT as _DEFAULT_VOICE
        from core.voices import get as _voice_get
        voice = j.get("voice", {})
        self.VOICE_PRESET = voice.get("preset") or self._env_get("VOICE_PRESET", _DEFAULT_VOICE)
        vp = _voice_get(self.VOICE_PRESET)
        # The preset declares its own TTS engine (edge / elevenlabs); an explicit
        # profile or env override still wins.
        self.TTS_PROVIDER = (voice.get("provider") or vp.get("provider")
                             or self._env_get("TTS_PROVIDER", "edge"))
        self.TTS_VOICE = voice.get("voice") or vp["voice"]
        self.TTS_RATE = voice.get("rate") or vp["rate"]
        self.TTS_PITCH = voice.get("pitch") or vp.get("pitch", "+0Hz")
        self.TTS_MODEL = voice.get("model") or vp.get("model", "eleven_multilingual_v2")

        # --- Visual media ---
        media = j.get("media", {})
        sources = media.get("sources") or self._env_get("MEDIA_SOURCES", "stock,graphics,flux")
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        self.MEDIA_SOURCES = sources
        self.IMAGE_PROVIDER = media.get("image_provider", self._env_get("IMAGE_PROVIDER", "pollinations"))
        self.VISUAL_STYLE = j.get("style", {}).get("visual_style", "cinematic sports broadcast")
        # Competition logo drawn bottom-right of every video. Swap the whole
        # tournament by pointing this at another file (World Cup -> La Liga).
        self.COMPETITION_LOGO = (j.get("style", {}).get("competition_logo")
                                 or self._env_get("COMPETITION_LOGO", ""))

        # --- YouTube publish ---
        self.PRACTICE_MODE = str(self._env_get("PRACTICE_MODE", "true")).lower() == "true"
        self.YOUTUBE_PRIVACY = self._env_get("YOUTUBE_PRIVACY", "private")
        if self.PRACTICE_MODE:
            self.YOUTUBE_PRIVACY = "private"
        # When true, every generated video uploads to YouTube automatically with
        # YOUTUBE_PRIVACY. Off by default so nothing is published unintentionally.
        self.AUTO_UPLOAD = str(
            j.get("youtube", {}).get("auto_upload",
                                     self._env_get("AUTO_UPLOAD", "false"))
        ).lower() == "true"
        # Optional playlist every uploaded video is added to, e.g. Reels
        # Mundial 2026. Public, not a secret, so it lives in profile.json;
        # YOUTUBE_PLAYLIST_ID in .env still works as an override. The playlist
        # must belong to the same channel as the OAuth token.
        self.YOUTUBE_PLAYLIST_ID = (
            j.get("youtube", {}).get("playlist_id")
            or self._env_get("YOUTUBE_PLAYLIST_ID", "")
        )

        # --- Output dirs ---
        self.OUTPUT_DIR = self.dir / "output"
        self.VIDEO_DIR = self.OUTPUT_DIR / "videos"
        self.IMAGE_DIR = self.OUTPUT_DIR / "images"
        self.CONTENT_DIR = self.OUTPUT_DIR / "content"
        self.LOG_DIR = self.OUTPUT_DIR / "logs"
        # History of Laboratorio IA / free-topic requests (one JSON per request).
        self.LAB_DIR = self.OUTPUT_DIR / "lab"
        for d in (self.VIDEO_DIR, self.IMAGE_DIR, self.CONTENT_DIR, self.LOG_DIR,
                  self.LAB_DIR):
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
            "competition": {
                "preset": self.COMPETITION,
                "provider": self.DATA_PROVIDER,
                "league_id": self.LEAGUE_ID,
                "season": self.SEASON,
                "mode": self.MATCH_MODE,
            },
            "llm_provider": self.LLM_PROVIDER,
            "voice": {"preset": self.VOICE_PRESET, "provider": self.TTS_PROVIDER,
                      "voice": self.TTS_VOICE, "rate": self.TTS_RATE},
            "media": {"sources": self.MEDIA_SOURCES, "image_provider": self.IMAGE_PROVIDER},
            "style": {"visual_style": self.VISUAL_STYLE},
            "youtube": {"practice_mode": self.PRACTICE_MODE, "privacy": self.YOUTUBE_PRIVACY,
                        "auto_upload": self.AUTO_UPLOAD,
                        "playlist_id": self.YOUTUBE_PLAYLIST_ID},
            "has_system_preamble": bool(self.system_preamble),
        }

    def update_profile_json(self, updates: dict) -> None:
        """Deep-merge `updates` into profile.json and reload attributes.

        Only whitelisted top-level sections are accepted, to avoid writing junk.
        """
        allowed = {"name", "team", "language", "competition", "llm_provider",
                   "voice", "media", "style", "persona", "youtube"}
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
