"""SQLite data layer. Mirrors the Supabase schema the site previously used."""
import json
import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("WHITE_DB_PATH", os.path.join(BASE_DIR, "white.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS tabs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  page_type TEXT NOT NULL DEFAULT 'standard',
  visible INTEGER NOT NULL DEFAULT 1,
  position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tab_id INTEGER,
  title TEXT NOT NULL,
  subtitle TEXT,
  excerpt TEXT,
  content TEXT,
  image_url TEXT,
  tags TEXT,
  published INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'live',
  pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  author TEXT,
  rating REAL,
  cover_url TEXT,
  year_read TEXT,
  status TEXT NOT NULL DEFAULT 'published',
  review TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS music (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  artist TEXT,
  type TEXT,
  cover_url TEXT,
  rating REAL,
  status TEXT NOT NULL DEFAULT 'published',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  caption TEXT,
  alt_text TEXT,
  album TEXT,
  tags TEXT,
  visible INTEGER NOT NULL DEFAULT 1,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL,
  url TEXT NOT NULL,
  description TEXT,
  category TEXT,
  visible INTEGER NOT NULL DEFAULT 1,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS guestbook_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  message TEXT NOT NULL,
  website TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS sections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tab_id INTEGER,
  type TEXT NOT NULL,
  title TEXT,
  config TEXT,
  visible INTEGER NOT NULL DEFAULT 1,
  position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS site_settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS pending_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS visitors (
  page TEXT PRIMARY KEY,
  count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS visitors_seen (
  vid TEXT PRIMARY KEY,
  first_seen TEXT
);
CREATE TABLE IF NOT EXISTS visitor_ips (
  ip TEXT NOT NULL,
  day TEXT NOT NULL,
  first_seen TEXT,
  PRIMARY KEY (ip, day)
);
CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL,
  url TEXT NOT NULL,
  content_type TEXT,
  size INTEGER NOT NULL DEFAULT 0,
  created_at TEXT
);
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    # Migrations for databases created before a column existed.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    if "tags" not in cols:
        conn.execute("ALTER TABLE photos ADD COLUMN tags TEXT")
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def query(sql, params=()):
    conn = get_db()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def query_one(sql, params=()):
    conn = get_db()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def execute(sql, params=()):
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def insert_ignore(sql, params=()):
    """Run an INSERT OR IGNORE and report how many rows actually landed."""
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def execute_update(sql, params=()):
    """Run an UPDATE and return the number of rows affected."""
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def execute_many(sql, seq):
    conn = get_db()
    try:
        conn.executemany(sql, seq)
        conn.commit()
    finally:
        conn.close()


def tags_to_list(row):
    """tags column is stored as a JSON array string."""
    try:
        return json.loads(row["tags"]) if row["tags"] else []
    except (ValueError, TypeError, KeyError):
        return []


def list_to_tags(value):
    if isinstance(value, str):
        parts = [t.strip() for t in value.split(",") if t.strip()]
    else:
        parts = list(value or [])
    return json.dumps(parts)


def parse_albums(value):
    """photos.album can be a JSON array (multi-album) or legacy plain text."""
    if not value:
        return []
    v = str(value).strip()
    if v.startswith("["):
        try:
            arr = json.loads(v)
            return [a for a in arr if a] if isinstance(arr, list) else [v]
        except (ValueError, TypeError):
            return [v]
    return [p.strip() for p in v.split(",") if p.strip()]


def serialize_albums(albums):
    return json.dumps([a for a in albums if a])
