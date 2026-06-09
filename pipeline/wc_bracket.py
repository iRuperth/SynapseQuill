"""
wc_bracket.py — FIFA World Cup 2026 knockout bracket (free, no key).

Builds the elimination tree (Round of 32 → R16 → QF → SF → Final + 3rd place)
from the same public-domain openfootball worldcup.json used by wc_calendar, then
fills in real teams + scores by cross-referencing ESPN's free scoreboard.

How the skeleton fills itself:
  * openfootball gives every knockout match a `num` and placeholder opponents:
      - R32: group-position labels ("1E" = winner of group E, "2A" = runner-up
        of A) and best-third labels ("3A/B/C/D/F"). These have no feeder match;
        only ESPN (once the real team plays) can resolve them.
      - R16 onward: "W##"/"L##" = winner/loser of match ##, so the tree wiring is
        fully known offline.
  * ESPN (fifa.world scoreboard) provides the real teams, flags and scores for
    matches that have been played; we match them to nodes by date (±1 day for the
    UTC offset) and by already-known team name.
  * Once a match finishes we propagate its winner/loser down the tree, so the
    next round's slot shows the qualified team even before that match is played.

Before the tournament starts ESPN returns nothing, so the whole bracket renders
as a skeleton of placeholder labels — which is exactly the desired behaviour.
Cached on disk; safe to call hourly.
"""

import re
import unicodedata
from datetime import date, datetime

from .data_sources import cache
from .wc_calendar import _URL, _team_name

# Knockout round labels as they appear in openfootball, in bracket order.
_KO_ROUNDS = [
    "Round of 32", "Round of 16", "Quarter-final",
    "Semi-final", "Match for third place", "Final",
]
_ROUND_KEY = {
    "Round of 32": "r32", "Round of 16": "r16", "Quarter-final": "qf",
    "Semi-final": "sf", "Match for third place": "third", "Final": "final",
}
# Output order of rounds (third place rendered after the final by the UI).
_ROUND_ORDER = ["r32", "r16", "qf", "sf", "final", "third"]

# ESPN names don't always match openfootball country names; normalise both and
# keep a small alias map for the known mismatches.
_ALIASES = {
    "united states": "usa", "south korea": "korea republic",
    "ir iran": "iran", "iran": "iran", "cote d'ivoire": "ivory coast",
    "czechia": "czech republic", "turkiye": "turkey",
}


def _norm(name: str) -> str:
    """Casefold + strip accents + alias, for tolerant team-name matching."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold().strip()
    return _ALIASES.get(s, s)


def parse_ref(s: str) -> dict:
    """Classify a knockout opponent placeholder. `label` is always preserved so
    the UI can show the raw token until a real team resolves it."""
    s = (s or "").strip()
    if m := re.fullmatch(r"W(\d+)", s):
        return {"kind": "winner", "num": int(m.group(1)), "label": s}
    if m := re.fullmatch(r"L(\d+)", s):
        return {"kind": "loser", "num": int(m.group(1)), "label": s}
    if m := re.fullmatch(r"([12])([A-L])", s):
        return {"kind": "group_pos", "pos": int(m.group(1)),
                "group": m.group(2), "label": s}
    if re.fullmatch(r"3[A-L/]+", s):
        return {"kind": "best_third", "label": s}
    return {"kind": "opaque", "label": s}


def _empty_slot(ref: dict) -> dict:
    return {"label": ref["label"], "name": None, "flag": None,
            "score": None, "winner": False}


def _fetch_openfootball() -> dict:
    """The same 104-match JSON wc_calendar uses; cached separately but cheap."""
    key = ("wc_bracket_raw", "2026")
    cached = cache.get(key)
    if cached is None:
        import requests
        r = requests.get(_URL, timeout=30)
        r.raise_for_status()
        cached = r.json()
        cache.put(key, cached)
    return cached


def build_tree() -> dict:
    """Parse openfootball into knockout nodes keyed by match number.

    The third-place match and Final may lack a `num`; assign synthetic numbers
    (103 = third place, 104 = Final) so every node is addressable. Returns a
    dict {num -> node}.
    """
    raw = _fetch_openfootball()
    matches = raw.get("matches", []) if isinstance(raw, dict) else []
    nodes: dict[int, dict] = {}
    for m in matches:
        rnd = m.get("round", "")
        if rnd not in _KO_ROUNDS:
            continue
        num = m.get("num")
        if num is None:
            num = 104 if rnd == "Final" else 103  # third place / final fallback
        ref1 = parse_ref(_team_name(m.get("team1")))
        ref2 = parse_ref(_team_name(m.get("team2")))
        nodes[int(num)] = {
            "num": int(num),
            "round": rnd,
            "key": _ROUND_KEY[rnd],
            "date": (m.get("date") or "")[:10],
            "time": m.get("time", ""),
            "ref1": ref1, "ref2": ref2,
            "slot1": _empty_slot(ref1), "slot2": _empty_slot(ref2),
            "status": "SCHEDULED",
            "winner_slot": None,   # "slot1" | "slot2" once decided
        }
    return nodes


# ---------------------------------------------------------------------------
# ESPN resolution
# ---------------------------------------------------------------------------
class _WcCfg:
    """Minimal duck-typed config so EspnSource targets the World Cup slug
    without dragging in the heavy brand_config (profiles, output dirs, …)."""
    ESPN_SLUG = "fifa.world"

    def get_secret(self, key, default=None):
        import os
        return os.getenv(key, default)


def _espn_ko_results() -> list:
    """Fetch the whole knockout window from ESPN once (cached). Best-effort:
    returns [] on any failure so the bracket still renders as a skeleton."""
    key = ("wc_bracket_espn", date.today().isoformat())
    try:
        from .data_sources.espn import EspnSource
        src = EspnSource(_WcCfg())
        # R32 starts 2026-06-28; Final 2026-07-19. Pad a day each side for TZ.
        return src._scoreboard("20260627-20260720")
    except Exception:
        stale = cache.get_stale(key)
        return stale or []


def _days_apart(a: str, b: str) -> int:
    try:
        da = datetime.strptime(a[:10], "%Y-%m-%d").date()
        db = datetime.strptime(b[:10], "%Y-%m-%d").date()
        return abs((da - db).days)
    except (ValueError, TypeError):
        return 99


# ESPN labels not-yet-decided knockout slots with its own placeholders, e.g.
# "Group A 2nd Place", "Group A Winner", "Quarterfinal 1 Winner". These are NOT
# real teams — we keep our own openfootball labels instead, so ignore them.
_ESPN_PLACEHOLDER = re.compile(
    r"\b(winner|place|runner|group|quarterfinal|semifinal|"
    r"round of|loser|tbd|seed)\b", re.IGNORECASE)


def _is_real_team(name: str) -> bool:
    return bool(name) and not _ESPN_PLACEHOLDER.search(name)


def _espn_slot_label(name: str) -> str | None:
    """Map an ESPN placeholder name to our openfootball label so we can match
    the SAME knockout fixture regardless of which teams are in it.
      "Group A Winner"   -> "1A"      "Group A 2nd Place" -> "2A"
      "Round of 32 5 Winner" / "Round of 16 2 Winner" / "Quarterfinal 1 Winner"
      / "Semifinal 2 Winner" are positional (ESPN's own numbering) — left to
      date matching. Third-place group placeholders are opaque.
    """
    if not name:
        return None
    if m := re.search(r"Group ([A-L]) Winner", name, re.IGNORECASE):
        return f"1{m.group(1).upper()}"
    if m := re.search(r"Group ([A-L]) 2nd Place", name, re.IGNORECASE):
        return f"2{m.group(1).upper()}"
    return None


def _match_espn_to_node(node: dict, espn: list) -> None:
    """Fill a node's slots from the matching ESPN knockout event.

    A knockout node is matched to the ESPN event whose own placeholder labels
    equal ours (e.g. our "2A"/"2B" == ESPN "Group A 2nd Place"/"Group B 2nd
    Place"). This is exact and immune to the group-stage matches ESPN also
    returns in the same date window. Once that fixture is played, ESPN swaps its
    placeholders for the real teams, so we then read names/flags/scores from the
    same event (matched by date + already-known team). ESPN placeholder names
    are never written into a slot — we keep our own labels until a real team
    appears.
    """
    def candidates(max_gap):
        cs = [e for e in espn if _days_apart(e.date, node["date"]) <= max_gap]
        cs.sort(key=lambda e: e.kickoff or "")
        return cs

    cands = candidates(0) or candidates(1)
    if not cands:
        return

    want = {node["ref1"]["label"], node["ref2"]["label"]}
    known = {_norm(node["slot1"]["name"]), _norm(node["slot2"]["name"])} - {""}

    chosen = None
    # 1) exact label match against ESPN's own group-position placeholders
    for e in cands:
        labels = {_espn_slot_label(e.home), _espn_slot_label(e.away)} - {None}
        if labels and labels == want:
            chosen = e
            break
    # 2) else, if we already know a real team, match the event containing it
    if chosen is None and known:
        for e in cands:
            if {_norm(e.home), _norm(e.away)} & known:
                chosen = e
                break
    if chosen is None:
        return

    # Only write real team names/flags; keep the placeholder label otherwise.
    if _is_real_team(chosen.home):
        node["slot1"]["name"] = chosen.home
        node["slot1"]["flag"] = chosen.home_logo or node["slot1"]["flag"]
    if _is_real_team(chosen.away):
        node["slot2"]["name"] = chosen.away
        node["slot2"]["flag"] = chosen.away_logo or node["slot2"]["flag"]
    if _is_real_team(chosen.home) or _is_real_team(chosen.away):
        node["slot1"]["score"] = chosen.home_goals
        node["slot2"]["score"] = chosen.away_goals

    if chosen.is_finished and (_is_real_team(chosen.home) or _is_real_team(chosen.away)):
        node["status"] = "FINISHED"
        hg, ag = chosen.home_goals, chosen.away_goals
        if hg is not None and ag is not None and hg != ag:
            win = "slot1" if hg > ag else "slot2"
            node["winner_slot"] = win
            node[win]["winner"] = True
        # Equal score on a finished KO = penalties; if ESPN doesn't expose the
        # shootout we leave winner_slot unset and don't propagate (better blank
        # downstream than a wrong team).
    elif chosen.status not in ("NS", "STATUS_SCHEDULED", ""):
        node["status"] = "LIVE"


def _propagate(nodes: dict) -> None:
    """Once ESPN is resolved, copy decided teams down the tree. Processed in
    `num` order because every downstream match number is larger than its
    feeders. R32 (group_pos / best_third) is never propagated — it has no
    feeder match and only ESPN can fill it."""
    for num in sorted(nodes):
        node = nodes[num]
        for slot_key, ref_key in (("slot1", "ref1"), ("slot2", "ref2")):
            slot, ref = node[slot_key], node[ref_key]
            if slot["name"] or ref["kind"] not in ("winner", "loser"):
                continue
            src = nodes.get(ref["num"])
            if not src or src["status"] != "FINISHED" or not src["winner_slot"]:
                continue
            if ref["kind"] == "winner":
                src_slot = src[src["winner_slot"]]
            else:
                src_slot = src["slot2"] if src["winner_slot"] == "slot1" else src["slot1"]
            slot["name"] = src_slot["name"]
            slot["flag"] = src_slot["flag"]


def _public_match(node: dict) -> dict:
    return {
        "num": node["num"], "round": node["round"], "date": node["date"],
        "time": node["time"], "status": node["status"],
        "team1": {k: node["slot1"][k] for k in ("label", "name", "flag", "score", "winner")},
        "team2": {k: node["slot2"][k] for k in ("label", "name", "flag", "score", "winner")},
    }


def bracket() -> dict:
    """Full bracket grouped by round, with ESPN results applied + propagated.

    Cached per (day, hour) so it recomputes at most once an hour — matching the
    UI's hourly refresh — while staying within the 6h cache TTL.
    """
    now = datetime.now()
    cache_key = ("wc_bracket_result", now.date().isoformat(), now.hour)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    nodes = build_tree()
    espn = _espn_ko_results()
    for node in nodes.values():
        _match_espn_to_node(node, espn)
    _propagate(nodes)

    by_key: dict[str, list] = {k: [] for k in _ROUND_ORDER}
    for num in sorted(nodes):
        node = nodes[num]
        by_key[node["key"]].append(_public_match(node))

    result = {
        "rounds": [
            {"key": k, "round": next(r for r, kk in _ROUND_KEY.items() if kk == k),
             "matches": by_key[k]}
            for k in _ROUND_ORDER if by_key[k]
        ],
        "updated_at": now.isoformat(timespec="seconds"),
    }
    cache.put(cache_key, result)
    return result
