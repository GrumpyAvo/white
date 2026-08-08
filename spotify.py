"""Spotify now-playing backend, ported from the old Vercel deployment.

Uses the OAuth refresh-token flow. Configure via env vars:
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
If unset, the API returns {"isPlaying": False} instead of erroring.
"""
import os
import time

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
PLAYER_URL = "https://api.spotify.com/v1/me/player/currently-playing"

_cache = {"token": None, "expires": 0.0, "playing": None, "playing_at": 0.0}


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
                images = album.get("images") or []
                result = {
                    "isPlaying": True,
                    "title": item.get("name") or "unknown",
                    "artist": ", ".join(
                        a.get("name", "") for a in (item.get("artists") or [])
                    ) or "unknown",
                    "albumArt": images[0].get("url") if images else None,
                }
        except requests.RequestException:
            pass

    _cache["playing"] = result
    _cache["playing_at"] = now
    return result
