"""Auto-fetch book covers from Open Library.

The books page advertises "cover art via open library" but books are stored
without covers. These helpers query the Open Library search API, cache results
in-process, and can backfill the books table.
"""
import json
import urllib.parse
import urllib.request

import db

OL_SEARCH = "https://openlibrary.org/search.json"

_cache = {}


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "white-cms/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _lookup(title, author):
    """Return an Open Library cover URL for the book, or None."""
    if not title:
        return None
    q = title
    if author:
        q += " " + author
    url = OL_SEARCH + "?" + urllib.parse.urlencode(
        {"q": q, "fields": "title,author_name,cover_i", "limit": 3})
    raw = _get(url)
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError):
        return None
    for doc in data.get("docs") or []:
        cover_i = doc.get("cover_i")
        if cover_i:
            return "https://covers.openlibrary.org/b/id/%s-L.jpg" % cover_i
    return None


def cover_for(book):
    """Live lookup with an in-process cache (won't hit the network twice)."""
    key = ((book.get("title") or ""), (book.get("author") or ""))
    if key not in _cache:
        _cache[key] = _lookup(*key)
    return _cache[key]


def resolve(book):
    """DB cover_url when present, else a live Open Library lookup."""
    if book.get("cover_url"):
        return book["cover_url"]
    return cover_for(book)


def fetch_missing():
    """Backfill empty cover_url for every published book. Returns count added."""
    n = 0
    rows = db.query(
        "SELECT id, title, author FROM books"
        " WHERE status='published' AND (cover_url IS NULL OR cover_url='')")
    for r in rows:
        url = _lookup(r["title"] or "", r["author"] or "")
        if url:
            db.execute("UPDATE books SET cover_url=? WHERE id=?", (url, r["id"]))
            n += 1
    return n
