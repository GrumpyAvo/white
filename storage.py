"""Durable storage via Upstash Redis (REST API).

If UPSTASH_REST_URL + UPSTASH_REST_TOKEN are set, the app mirrors its content
snapshot and uploaded files there so nothing is lost on Render redeploys.
Without them everything still works, just not durably.

Media file sizes are capped for the Redis path; bigger files still work
locally but won't survive a redeploy.
"""
import base64
import json
import os
import urllib.request

REST_URL = os.environ.get("UPSTASH_REST_URL", "").strip().rstrip("/")
REST_TOKEN = os.environ.get("UPSTASH_REST_TOKEN", "").strip()

KEY_SNAPSHOT = "white:snapshot"
KEY_MEDIA = "white:media:"

# Cap per-file blob stored in Redis (Upstash free tier is happy well below this)
MAX_MEDIA = 4 * 1024 * 1024

# Uploaded files land here on disk (served at /uploads/<name>)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")


def durable():
    return bool(REST_URL and REST_TOKEN)


def _cmd(command, *args):
    if not durable():
        raise RuntimeError("upstash not configured")
    body = json.dumps([command] + list(args)).encode("utf-8")
    req = urllib.request.Request(REST_URL, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + REST_TOKEN)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("result")


def save_snapshot(text):
    _cmd("SET", KEY_SNAPSHOT, text)


def load_snapshot():
    return _cmd("GET", KEY_SNAPSHOT)


def save_media(name, blob):
    _cmd("SET", KEY_MEDIA + name, base64.b64encode(blob).decode("ascii"))


def load_media(name):
    raw = _cmd("GET", KEY_MEDIA + name)
    if raw is None:
        return None
    return base64.b64decode(raw)


def delete_media(name):
    _cmd("DEL", KEY_MEDIA + name)
