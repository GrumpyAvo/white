"""Seed the database from data/seed.json (extracted from the old admin.html
"Import Data" arrays). Run `py -m seed` to seed a fresh database."""
import json
import os

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(BASE_DIR, "data", "seed.json")

DEFAULT_SETTINGS = {
    "site_title": "white",
    "site_tagline": "",
    "marquee_text": "★ welcome to white ★",
    "posts_per_page": "10",
    "guestbook_open": "true",
}


def load_seed():
    with open(SEED_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def seed_pages(seed=None):
    seed = seed or load_seed()
    added = 0
    for p in seed.get("pages", []):
        if db.query_one("SELECT id FROM tabs WHERE slug=?", (p["slug"],)):
            continue
        db.execute(
            "INSERT INTO tabs(name,slug,page_type,visible,position) VALUES(?,?,?,?,?)",
            (
                p["name"],
                p["slug"],
                p.get("page_type", "standard"),
                1 if p.get("visible") else 0,
                p.get("order", 0),
            ),
        )
        added += 1
    return added


def seed_books(seed=None):
    seed = seed or load_seed()
    existing = {r["title"] for r in db.query("SELECT title FROM books")}
    added = 0
    for b in seed.get("books", []):
        if b["title"] in existing:
            continue
        db.execute(
            "INSERT INTO books(title,author,rating,status,created_at) VALUES(?,?,?,?,?)",
            (b["title"], b.get("author"), b.get("rating"), b.get("status", "published"), db.now_iso()),
        )
        existing.add(b["title"])
        added += 1
    return added


def seed_papers(seed=None):
    seed = seed or load_seed()
    tab = db.query_one("SELECT id FROM tabs WHERE slug='studies'")
    if not tab:
        return 0
    existing = {r["title"] for r in db.query("SELECT title FROM posts WHERE tab_id=?", (tab["id"],))}
    added = 0
    for p in seed.get("papers", []):
        if p["title"] in existing:
            continue
        content = ("[PDF ↗](%s)\n\n" % p["href"]) if p.get("href") else ""
        content += p.get("summary", "")
        db.execute(
            "INSERT INTO posts(tab_id,title,subtitle,excerpt,content,tags,published,status,pinned,created_at)"
            " VALUES(?,?,?,?,?,?,1,'live',0,?)",
            (
                tab["id"],
                p["title"],
                p.get("authors"),
                (p.get("summary") or "")[:200],
                content,
                db.list_to_tags((p.get("tag") or "").split(" \u00b7 ")),
                db.now_iso(),
            ),
        )
        existing.add(p["title"])
        added += 1
    return added


def seed_photos(seed=None):
    seed = seed or load_seed()
    existing = {r["url"] for r in db.query("SELECT url FROM photos")}
    added = 0
    for i, url in enumerate(seed.get("photos", [])):
        if url in existing:
            continue
        db.execute(
            "INSERT INTO photos(url,visible,position,created_at) VALUES(?,1,?,?)",
            (url, i, db.now_iso()),
        )
        existing.add(url)
        added += 1
    return added


def seed_sections(seed=None):
    seed = seed or load_seed()
    tabs = {t["slug"]: t["id"] for t in db.query("SELECT id,slug FROM tabs")}
    added = 0
    for s in seed.get("sections", []):
        tid = tabs.get(s["slug"])
        if not tid:
            continue
        if db.query_one("SELECT id FROM sections WHERE tab_id=? AND type=? LIMIT 1", (tid, s["type"])):
            continue
        import json as _json

        db.execute(
            "INSERT INTO sections(tab_id,type,title,config,visible,position) VALUES(?,?,?,?,1,0)",
            (tid, s["type"], s.get("title"), _json.dumps(s.get("config") or {})),
        )
        added += 1
    return added


def seed_settings():
    added = 0
    for key, value in DEFAULT_SETTINGS.items():
        if not db.query_one("SELECT key FROM site_settings WHERE key=?", (key,)):
            db.execute("INSERT INTO site_settings(key,value) VALUES(?,?)", (key, value))
            added += 1
    return added


def seed_all():
    seed = load_seed()
    return {
        "pages": seed_pages(seed),
        "books": seed_books(seed),
        "papers": seed_papers(seed),
        "photos": seed_photos(seed),
        "sections": seed_sections(seed),
        "settings": seed_settings(),
    }


if __name__ == "__main__":
    db.init_db()
    result = seed_all()
    print("seeded:", result)
