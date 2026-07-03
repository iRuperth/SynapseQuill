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
import shutil
import time
from pathlib import Path

from core.brand_config import BrandProfile

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# httplib2 (what googleapiclient uses under the hood) creates sockets with NO
# timeout by default, so a connection that dies mid-transfer blocks the calling
# thread FOREVER — the scheduler ran in a single thread, so one hung upload
# froze the whole poll loop (seen as a stuck CLOSE_WAIT socket, 0% CPU, no new
# log lines for hours). A finite socket timeout turns that hang into a normal
# exception the retry loop / scheduler's try/except can handle.
_UPLOAD_SOCKET_TIMEOUT = 300      # seconds per HTTP request/chunk
# A resumable upload can hit transient network/5xx errors mid-stream; retry the
# failed chunk a bounded number of times with backoff before giving up, so a
# blip doesn't lose an otherwise-complete upload.
_UPLOAD_MAX_RETRIES = 5
_RETRIABLE_STATUS = frozenset({500, 502, 503, 504})


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
    is normalised to a single leading '#'. The tag builders already emit a tight,
    ordered set (a format tag, the competition, then the teams), of which only
    the first 3 show above the title; the cap at 10 is a backstop against a long
    hashtag wall that would read as spam (past 60, YouTube ignores them ALL)."""
    hashtags = []
    for t in tags:
        h = "#" + t.lstrip("#")
        if h != "#" and h not in hashtags:
            hashtags.append(h)
    if not hashtags:
        return description
    line = " ".join(hashtags[:10])
    return f"{description}\n\n{line}".strip()


def _add_to_playlist(youtube, playlist_id: str, video_id: str) -> None:
    """Append an uploaded video to a playlist. Best-effort: a failure here must
    NOT lose the upload, so errors are swallowed with a warning. The playlist
    must belong to the same channel as the OAuth token, otherwise YouTube
    returns a 404 playlistNotFound error."""
    from googleapiclient.errors import HttpError

    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()
    except HttpError as e:
        print(f"[publishers] could not add {video_id} to playlist "
              f"{playlist_id}: {e}")


def _timed_http(creds):
    """Build an authorized httplib2.Http whose socket has a finite timeout.

    Without this, httplib2 sockets never time out, so a stalled YouTube
    connection hangs the caller indefinitely. google-auth's AuthorizedHttp
    wraps the timed Http so credentials still apply."""
    import google_auth_httplib2
    import httplib2

    return google_auth_httplib2.AuthorizedHttp(
        creds, http=httplib2.Http(timeout=_UPLOAD_SOCKET_TIMEOUT))


def _resumable_upload(request):
    """Drive a resumable upload to completion, retrying failed chunks.

    Each next_chunk() sends one chunk. A finite socket timeout (see
    _timed_http) means a stalled connection raises instead of hanging; a
    transient network error or a retriable 5xx from YouTube is retried a
    bounded number of times with exponential backoff. Non-retriable HttpErrors
    (bad request, quota, auth) propagate immediately — the scheduler's
    try/except logs them and moves on rather than crashing."""
    from googleapiclient.errors import HttpError

    response = None
    retries = 0
    while response is None:
        try:
            _status, response = request.next_chunk()
        except HttpError as e:
            if e.resp.status in _RETRIABLE_STATUS and retries < _UPLOAD_MAX_RETRIES:
                retries += 1
            else:
                raise
        except OSError as e:
            # OSError covers socket timeouts (TimeoutError) and dropped
            # connections — the failure mode that used to hang the scheduler
            # forever, now that _timed_http gives sockets a finite timeout.
            if retries < _UPLOAD_MAX_RETRIES:
                retries += 1
                print(f"[publishers] upload chunk failed ({e}); "
                      f"retry {retries}/{_UPLOAD_MAX_RETRIES}")
            else:
                raise
        else:
            continue
        time.sleep(min(2 ** retries, 30))          # exponential backoff, capped
    return response


def upload_youtube(cfg: BrandProfile, video_path: Path, metadata: dict) -> str:
    """Upload `video_path` and return the watch URL."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    privacy = "private" if cfg.PRACTICE_MODE else cfg.YOUTUBE_PRIVACY

    creds = _credentials(cfg)
    # Pass a timeout-bearing authorized http so no single request can hang
    # forever (build() otherwise makes a default httplib2.Http with no timeout).
    # `http` already carries the credentials, so `credentials` must NOT also be
    # passed — build() rejects both together as mutually exclusive.
    youtube = build("youtube", "v3", http=_timed_http(creds))

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

    response = _resumable_upload(request)
    video_id = response["id"]

    # Add to the profile's playlist, e.g. Reels Mundial 2026, if configured.
    if cfg.YOUTUBE_PLAYLIST_ID:
        _add_to_playlist(youtube, cfg.YOUTUBE_PLAYLIST_ID, video_id)

    return f"https://youtube.com/watch?v={video_id}"


def cleanup_local_artifacts(youtube_url: str, paths, *,
                            on_step=lambda *_: None) -> list[str]:
    """Delete the local files/dirs in `paths` ONCE the upload is verified.

    The scheduler creates a video, uploads it, and then there is no reason to
    keep the heavy artifacts (the .mp4, the .mp3 narration, the crowd images) on
    this machine — the published YouTube copy is the source of truth. This frees
    the disk so an unattended run never fills it up.

    SAFETY: deletion only happens when `youtube_url` is a confirmed watch URL
    (the value `upload_youtube` returns). A failed/blocked/skipped upload passes
    an empty url here, so nothing is ever deleted while the only copy is local.
    Each path is removed best-effort; a single failure is logged and skipped so
    cleanup never breaks the run. Returns the list of paths actually removed.
    """
    if not (isinstance(youtube_url, str)
            and youtube_url.startswith("https://youtube.com/watch?v=")):
        return []                                   # not verified -> keep everything

    removed: list[str] = []
    for p in paths:
        if not p:
            continue
        p = Path(p)
        try:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            else:
                continue                            # already gone
            removed.append(str(p))
        except OSError as e:
            on_step("cleanup", f"Could not delete {p.name}: {e}")
    if removed:
        on_step("cleanup", f"Uploaded — freed {len(removed)} local artifact(s)")
    return removed
