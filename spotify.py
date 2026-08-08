"""Spotify backend for the Flask app, ported from the old Vercel deployment.

Uses the OAuth refresh-token flow. Configure via env vars:
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
If unset, the API returns {"isPlaying": False} / empty top-stats instead of erroring.

Credentials can also live in a `.env` file next to this module (gitignored),
which is how local dev is configured. Render/other hosts use real env vars.
"""
import os
import time

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
PLAYER_URL = "https://api.spotify.com/v1/me/player/currently-playing"
TOP_ARTISTS_URL = "https://api.spotify.com/v1/me/top/artists"
TOP_TRACKS_URL = "https://api.spotify.com/v1/me/top/tracks"

# Tiny `.env` loader (stdlib only) so local dev works without extra deps.
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH, "r", encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            _key = _key.strip()
            _val = _val.strip().strip('"').strip("'")
            if _key and _key not in os.environ:
                os.environ[_key] = _val

_cache = {"token": None, "expires": 0.0, "playing": None, "playing_at": 0.0, "stats": None, "stats_at": 0.0}


def _access_token():
    now = time.time()
    if _cache["token"] and now < _cache["expires"] - 60:
        return _cache["token"]
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    refresh = os.environ.get("SPOTIFY_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh):
        return None
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    _cache["token"] = data["access_token"]
    _cache["expires"] = now + float(data.get("expires_in", 3600))
    return _cache["token"]


def _smallest_image(images):
    """Spotify returns images sorted largest-first; the small ones are fine here."""
    images = images or []
    return images[0].get("url") if images else None


def now_playing():
    """Return a dict shaped like the old Vercel response: isPlaying/title/artist/albumArt."""
    now = time.time()
    if _cache["playing"] and now - _cache["playing_at"] < 10:
        return _cache["playing"]

    result = {"isPlaying": False}
    token = _access_token()
    if token:
        try:
            resp = requests.get(
                PLAYER_URL,
                headers={"Authorization": "Bearer " + token},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                item = data.get("item") or {}
                album = item.get("album") or {}
                playing = bool(data.get("is_playing")) and bool(item)
                result = {
                    "isPlaying": playing,
                    "title": item.get("name") or "unknown",
                    "artist": ", ".join(
                        a.get("name", "") for a in (item.get("artists") or [])
                    ) or "unknown",
                    "album": album.get("name") or "",
                    "albumArt": _smallest_image(album.get("images")),
                    "songUrl": (item.get("external_urls") or {}).get("spotify") or "",
                    "progress": data.get("progress_ms") or 0,
                    "duration": item.get("duration_ms") or 0,
                }
        except requests.RequestException:
            pass

    _cache["playing"] = result
    _cache["playing_at"] = now
    return result


def _top(endpoint, limit):
    token = _access_token()
    if not token:
        return []
    resp = requests.get(
        endpoint,
        headers={"Authorization": "Bearer " + token},
        params={"limit": limit, "time_range": "short_term"},
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    return (resp.json().get("items") or [])


def top_stats():
    """Return {"artists": [...], "tracks": [...]} for the last month,
    shaped like the old Vercel top-stats endpoint."""
    now = time.time()
    if _cache["stats"] and now - _cache["stats_at"] < 300:
        return _cache["stats"]

    result = {"artists": [], "tracks": []}
    try:
        artists = _top(TOP_ARTISTS_URL, 6)
        result["artists"] = [
            {
                "name": a.get("name") or "unknown",
                "image": _smallest_image(a.get("images")),
                "url": (a.get("external_urls") or {}).get("spotify") or "",
                "genres": a.get("genres") or [],
            }
            for a in artists
        ]
        tracks = _top(TOP_TRACKS_URL, 5)
        result["tracks"] = [
            {
                "name": t.get("name") or "unknown",
                "artist": ", ".join(
                    a.get("name", "") for a in (t.get("artists") or [])
                ) or "unknown",
                "image": _smallest_image(((t.get("album") or {}).get("images"))),
                "url": (t.get("external_urls") or {}).get("spotify") or "",
            }
            for t in tracks
        ]
    except requests.RequestException:
        pass

    _cache["stats"] = result
    _cache["stats_at"] = now
    return result
