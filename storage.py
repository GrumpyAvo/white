"""Durable storage via Supabase (PostgREST + Storage).

If SUPABASE_URL + a key are set (SUPABASE_SERVICE_ROLE_KEY preferred,
SUPABASE_ANON_KEY also works if RLS allows), the app mirrors its content
snapshot and uploaded files there so nothing is lost on Render redeploys.
Without them everything still works, just not durably.

One-time setup (run in the Supabase SQL editor):
    create table if not exists public.app_backup (
      id integer primary key check (id = 1),
      payload text not null,
      updated_at timestamptz default now()
    );
    alter table public.app_backup enable row level security;
    create policy "backup access" on public.app_backup
      for all using (true) with check (true);

    -- only needed if you use an anon/publishable key instead of the
    -- service role key (service role bypasses RLS and can create buckets):
    -- create bucket white-media in the dashboard, then:
    -- create policy "media read" on storage.objects for select using (bucket_id = 'white-media');
    -- create policy "media write" on storage.objects for insert with check (bucket_id = 'white-media');

The backup bucket is created automatically on first run when using the
service role key. Media blobs are capped below the platform request limit.
"""
import json
import os
import urllib.error
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SERVICE_ROLE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()

KEY = SERVICE_ROLE or ANON_KEY
USING_SERVICE_ROLE = bool(SERVICE_ROLE)

# app_backup.id = 1 holds the snapshot payload
BUCKET = "white-media"

# Cap per-file blob stored in Supabase (platform request limits are tight on
# the free tier); bigger files still work locally but won't survive a redeploy.
MAX_MEDIA = 4 * 1024 * 1024

# Uploaded files land here on disk (served at /uploads/<name>)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

_bucket_checked = False


def durable():
    return bool(SUPABASE_URL and KEY)


def _headers(json_body=False):
    h = {
        "Authorization": "Bearer " + KEY,
        "apikey": KEY,
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _request(url, method, body=None, headers=None, timeout=20):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or _headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return 0, b""


def _ensure_bucket():
    """Create the media bucket once (service-role only)."""
    global _bucket_checked
    if _bucket_checked:
        return
    _bucket_checked = True
    if not USING_SERVICE_ROLE:
        return
    status, _ = _request(SUPABASE_URL + "/storage/v1/bucket/" + BUCKET, "GET")
    if status == 200:
        return
    if status == 404:
        payload = json.dumps({"id": BUCKET, "name": BUCKET, "public": True}).encode("utf-8")
        _request(SUPABASE_URL + "/storage/v1/bucket", "POST", payload, _headers(json_body=True))


# ── snapshot ──────────────────────────────────────────────────────────────────
def save_snapshot(text):
    _ensure_bucket()
    payload = json.dumps({"id": 1, "payload": text}).encode("utf-8")
    # Upsert (merge-duplicates on the primary key id=1)
    status, body = _request(
        SUPABASE_URL + "/rest/v1/app_backup",
        "POST",
        payload,
        {**_headers(True), "Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    if status not in (200, 201, 204):
        raise RuntimeError("snapshot write failed (%s): %s" % (status, body[:200]))


def load_snapshot():
    url = SUPABASE_URL + "/rest/v1/app_backup?id=eq.1&select=payload"
    status, body = _request(url, "GET")
    if status != 200:
        return None
    try:
        rows = json.loads(body.decode("utf-8"))
    except (ValueError, TypeError):
        return None
    if not rows:
        return None
    return rows[0].get("payload")


# ── media blobs ───────────────────────────────────────────────────────────────
def save_media(name, blob):
    _ensure_bucket()
    status, body = _request(
        SUPABASE_URL + "/storage/v1/object/" + BUCKET + "/" + name,
        "POST",
        blob,
        {"Authorization": "Bearer " + KEY, "apikey": KEY, "Content-Type": "application/octet-stream"},
    )
    if status not in (200, 201):
        raise RuntimeError("media upload failed (%s): %s" % (status, body[:200]))


def load_media(name):
    status, body = _request(SUPABASE_URL + "/storage/v1/object/" + BUCKET + "/" + name, "GET")
    if status == 200:
        return body
    return None


def delete_media(name):
    _request(SUPABASE_URL + "/storage/v1/object/" + BUCKET + "/" + name, "DELETE")
