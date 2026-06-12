"""
publishers.py — upload the generated .mp4 to YouTube via the Data API v3.

OAuth credentials are per profile:
    profiles/<id>/tokens/client_secret.json   (downloaded from Google Cloud)
    profiles/<id>/tokens/youtube_token.pickle  (created on first auth)

Privacy is governed by the profile: PRACTICE_MODE=true forces "private";
otherwise YOUTUBE_PRIVACY (private | unlisted | public) is used.

Mirrors Synapse Core's upload_youtube pattern.
"""

import pickle
from pathlib import Path

from core.brand_config import BrandProfile

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _credentials(cfg: BrandProfile):
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_file = cfg.tokens_dir / "youtube_token.pickle"
    secrets_file = cfg.tokens_dir / "client_secret.json"

    creds = None
    if token_file.exists():
        with open(token_file, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets_file.exists():
                raise FileNotFoundError(
                    f"Missing OAuth client secret at {secrets_file}. "
                    "Download it from Google Cloud (YouTube Data API v3, Desktop)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "wb") as f:
            pickle.dump(creds, f)
    return creds


def _description_with_hashtags(description: str, tags: list[str]) -> str:
    """Append the hashtags to the description so they show on YouTube. Each tag
    is normalised to a single leading '#'. Cap at 10: build_tags orders them by
    value (competition, matchup, teams, scorers, fan tags first), only the
    first 3 show above the title, and a long hashtag wall reads as spam and
    dilutes the topical signal (past 60, YouTube ignores them ALL)."""
    hashtags = []
    for t in tags:
        h = "#" + t.lstrip("#")
        if h != "#" and h not in hashtags:
            hashtags.append(h)
    if not hashtags:
        return description
    line = " ".join(hashtags[:10])
    return f"{description}\n\n{line}".strip()


def upload_youtube(cfg: BrandProfile, video_path: Path, metadata: dict) -> str:
    """Upload `video_path` and return the watch URL."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    privacy = "private" if cfg.PRACTICE_MODE else cfg.YOUTUBE_PRIVACY

    creds = _credentials(cfg)
    youtube = build("youtube", "v3", credentials=creds)

    tags = metadata.get("tags", [])
    body = {
        "snippet": {
            "title": metadata.get("title", "")[:100],
            # Hashtags only count as VISIBLE on YouTube when they're in the
            # description (the `tags` field below is an invisible search-only
            # metadata list). YouTube honours at most 15 hashtags in the
            # description, so append the first 15.
            "description": _description_with_hashtags(
                metadata.get("description", ""), tags),
            "tags": [t.lstrip("#") for t in tags][:500],
            "categoryId": "17",   # Sports
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()

    video_id = response["id"]
    return f"https://youtube.com/watch?v={video_id}"
