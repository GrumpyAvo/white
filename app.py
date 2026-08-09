"""white — Flask port of the static GitHub Pages site (Ricardo's Corner).

Run with:
    py -m flask --app app run --debug      # dev server
    py -m flask --app app init-db          # create schema
    py -m flask --app app seed             # import default data
"""
import json
import os
import re
from datetime import datetime, timezone

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

import backup
import db
import spotify
import storage
from admin import admin_bp

# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "white-dev-secret")
app.register_blueprint(admin_bp, url_prefix="/admin")
# Render sits behind a proxy: trust X-Forwarded-For so request.remote_addr
# carries the real visitor IP (used for the unique-visitor tally).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)


def ensure_db():
    """Create tables on boot (Render's disk is ephemeral — a fresh deploy
    starts empty). Restore from durable storage when available, else seed."""
    import sqlite3

    db.init_db()
    try:
        if not db.query_one("SELECT id FROM tabs LIMIT 1"):
            if not backup.restore():
                import seed as seed_mod

                seed_mod.seed_all()
            backup.restore_media_files()
    except sqlite3.OperationalError:
        pass


ensure_db()

# Public pages with dedicated templates (bespoke UI beyond plain sections)
DEDICATED = {"books": "books.html", "pics": "pics.html", "music": "music.html", "guestbook": "guestbook.html"}
# Slugs served by the generic sections template
GENERIC = {"about", "studies", "links"}


# ── Jinja filters ──────────────────────────────────────────────────────────────
@app.template_filter("fmtdate")
def fmtdate(value):
    if not value:
        return "\u2014"
    try:
        dt = datetime.fromisoformat(str(value))
        # `%-d` isn't portable (Windows), so strip a leading zero instead.
        return dt.strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(value)


BORAT_PHRASES = [
    "VERY NICE, SUCCESS",           # 10
    "very nice. i like very much",  # 9
    "like a pimp, but for books",   # 8
    "great success!",               # 7
    "not bad, not terrible",        # 6
    "i like",                       # 5
    "hmm. not so good",             # 4
    "is joke?",                     # 3
    "this is very bad",             # 2
    "very nice. actually not nice", # 1
]


@app.template_filter("phrase")
def phrase(value):
    """Map a rating out of 10 onto a Borat review."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return "\u2014"
    n = max(1, min(n, 10))
    return BORAT_PHRASES[10 - n]


@app.template_filter("md")
def md(text):
    """Tiny markdown, ported verbatim from the old page.html `md()`."""
    if not text:
        return ""
    text = re.sub(r"&", "&amp;", text)
    text = re.sub(r"<", "&lt;", text)
    text = re.sub(r">", "&gt;", text)
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.M)
    text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.M)
    text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"^> (.+)$", r"<blockquote>\1</blockquote>", text, flags=re.M)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\n\n", "</p><p>", text)
    text = "<p>" + text + "</p>"
    text = re.sub(r"<p>(<h[123]>)", r"\1", text)
    text = re.sub(r"(</h[123]>)</p>", r"\1", text)
    text = re.sub(r"<p>(<blockquote>)", r"\1", text)
    text = re.sub(r"(</blockquote>)</p>", r"\1", text)
    return text


@app.template_filter("stars")
def stars(n):
    try:
        n = min(max(int(n or 0), 0), 5)
    except (TypeError, ValueError):
        return "\u2014"
    return "\u2605" * n + "\u2606" * (5 - n)


@app.template_filter("fmt_int")
def fmt_int(n):
    return str(n or 0)


@app.context_processor
def inject_year():
    return {"now_year": datetime.now().year}


# ── Shared context ─────────────────────────────────────────────────────────────
def load_settings():
    rows = db.query("SELECT key, value FROM site_settings")
    return {r["key"]: r["value"] for r in rows}


def visitors_for(page):
    """Read-only: every counter shows the same global tally."""
    row = db.query_one("SELECT count FROM visitors WHERE page='site'")
    return row["count"] if row else 0


@app.before_request
def count_visitor():
    """Tally unique visitors by IP — one person counts once per day, no matter
    how many pages they open. The tally is global, so every page shows the same
    number. Runs before rendering so the displayed count is already current."""
    path = request.path
    if path.startswith("/static") or path.startswith("/api") or path.startswith("/admin"):
        return None
    ip = request.remote_addr or "unknown"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    added = db.insert_ignore(
        "INSERT OR IGNORE INTO visitor_ips(ip, day, first_seen) VALUES(?, ?, ?)",
        (ip, day, db.now_iso()),
    )
    if added:
        db.execute(
            "INSERT INTO visitors(page, count) VALUES('site', 1)"
            " ON CONFLICT(page) DO UPDATE SET count = count + 1")
    return None


def load_nav():
    return [dict(r) for r in db.query(
        "SELECT name, slug FROM tabs WHERE visible=1 ORDER BY position")]


def base_ctx(slug, page_name=None):
    settings = load_settings()
    now = {}
    try:
        now = spotify.now_playing()
    except Exception:
        pass
    recent = [dict(r) for r in db.query(
        "SELECT p.id, p.title, p.created_at, t.slug AS tab_slug, t.name AS tab_name"
        " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id"
        " WHERE p.published=1 AND p.status!='hidden' ORDER BY p.created_at DESC LIMIT 3")]
    gb = db.query_one(
        "SELECT name, message FROM guestbook_entries"
        " WHERE status='approved' ORDER BY created_at DESC LIMIT 1")
    return {
        "site_title": settings.get("site_title") or "white",
        "marquee": settings.get("marquee_text") or "\u2605 welcome to white \u2605",
        "tagline": settings.get("site_tagline") or "",
        "guestbook_open": settings.get("guestbook_open", "true") != "false",
        "nav": load_nav(),
        "page_slug": slug,
        "page_name": page_name or slug,
        "visitor_count": visitors_for("site"),
        "meta_description": settings.get("site_tagline") or "",
        "recent_posts": recent,
        "gb_latest": dict(gb) if gb else None,
        "now_playing": now,
    }


def post_row_to_dict(row):
    d = dict(row)
    d["tags"] = db.tags_to_list(row)
    return d


def photo_to_dict(row):
    """Attach a parsed multi-album list to each photo row."""
    d = dict(row)
    d["albums"] = db.parse_albums(d.get("album")) if d.get("album") else []
    return d


IMG_URL_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)|\b(https?://[^\s<>'\"]+\.(?:jpe?g|png|gif|webp|avif))\b", re.IGNORECASE)


def gallery_images(post):
    """All images attached to a post: its cover + any images in its markdown."""
    urls = []
    if post.get("image_url"):
        urls.append(post["image_url"])
    content = post.get("content") or ""
    for m in IMG_URL_RE.finditer(content):
        url = m.group(1) or m.group(2)
        if url and url not in urls:
            urls.append(url)
    return urls


def load_sections(slug):
    """Return (tab, sections) for a generic page. Each section is a dict with
    cfg and pre-queried `items`."""
    tab = db.query_one("SELECT * FROM tabs WHERE slug=?", (slug,))
    if not tab:
        return None, []
    rows = db.query(
        "SELECT * FROM sections WHERE tab_id=? AND visible=1 ORDER BY position", (tab["id"],))
    sections = []
    for s in rows:
        sec = dict(s)
        sec["cfg"] = json.loads(sec["config"] or "{}")
        sec["items"] = []
        cfg = sec["cfg"]
        limit = int(cfg.get("limit") or 20)
        if sec["type"] == "posts":
            sql = ("SELECT p.*, t.slug AS tab_slug, t.name AS tab_name"
                   " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id"
                   " WHERE p.published=1 AND p.status!='hidden'")
            params = []
            if cfg.get("tag"):
                sql += " AND p.tags LIKE ?"
                params.append('"%%s"' % cfg["tag"].replace('"', ''))
            else:
                sql += " AND p.tab_id=?"
                params.append(tab["id"])
            sql += " ORDER BY p.pinned DESC, p.created_at DESC LIMIT ?"
            params.append(limit)
            sec["items"] = [post_row_to_dict(r) for r in db.query(sql, params)]
        elif sec["type"] == "books":
            order = "rating DESC" if cfg.get("sort") == "rating_desc" else "created_at DESC"
            sec["items"] = [dict(r) for r in db.query(
                "SELECT * FROM books WHERE status='published' ORDER BY %s LIMIT ?" % order,
                (limit,))]
        elif sec["type"] == "photos":
            sql = "SELECT * FROM photos WHERE visible=1"
            params = []
            if cfg.get("album"):
                sql += " AND album LIKE ?"
                params.append("%" + cfg["album"] + "%")
            sql += " ORDER BY position LIMIT ?"
            params.append(limit)
            sec["items"] = [photo_to_dict(r) for r in db.query(sql, params)]
        elif sec["type"] == "music":
            sql = "SELECT * FROM music WHERE status='published'"
            params = []
            if cfg.get("type"):
                sql += " AND type=?"
                params.append(cfg["type"])
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            sec["items"] = [dict(r) for r in db.query(sql, params)]
        elif sec["type"] == "links":
            rows = db.query("SELECT * FROM links WHERE visible=1 ORDER BY position LIMIT ?", (limit,))
            sec["items"] = [dict(r, category=r["category"] or "misc") for r in rows]
        elif sec["type"] == "guestbook":
            sec["items"] = [dict(r) for r in db.query(
                "SELECT * FROM guestbook_entries WHERE status='approved'"
                " ORDER BY created_at DESC LIMIT ?", (limit,))]
        sections.append(sec)
    return tab, sections


def fallback_content(tab):
    """Replicate the old page boot fallback for tabs with no sections."""
    t = tab["page_type"]
    if t == "books":
        return "books", [dict(r) for r in db.query(
            "SELECT * FROM books WHERE status='published' ORDER BY created_at DESC LIMIT 48")]
    if t == "photos":
        return "photos", [photo_to_dict(r) for r in db.query(
            "SELECT * FROM photos WHERE visible=1 ORDER BY position LIMIT 200")]
    if t == "music":
        return "music", [dict(r) for r in db.query(
            "SELECT * FROM music WHERE status='published' ORDER BY created_at DESC LIMIT 48")]
    if t == "guestbook":
        return "guestbook", [dict(r) for r in db.query(
            "SELECT * FROM guestbook_entries WHERE status='approved'"
            " ORDER BY created_at DESC LIMIT 50")]
    if t == "links":
        rows = db.query("SELECT * FROM links WHERE visible=1 ORDER BY position LIMIT 200")
        return "links", [dict(r, category=r["category"] or "misc") for r in rows]
    return "posts", [post_row_to_dict(r) for r in db.query(
        "SELECT p.*, t.slug AS tab_slug, t.name AS tab_name"
        " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id"
        " WHERE p.tab_id=? AND p.published=1 AND p.status!='hidden'"
        " ORDER BY p.pinned DESC, p.created_at DESC LIMIT 20", (tab["id"],))]


def render_page(slug, template):
    tab, sections = load_sections(slug)
    if not tab:
        abort(404)
    # Any post assigned to this page shows here, even without a configured
    # posts section (so a post placed on "about" actually appears there).
    if tab["page_type"] in ("standard", "posts") and not any(s["type"] == "posts" for s in sections):
        rows = db.query(
            "SELECT p.*, t.slug AS tab_slug, t.name AS tab_name"
            " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id"
            " WHERE p.published=1 AND p.status!='hidden' AND p.tab_id=?"
            " ORDER BY p.pinned DESC, p.created_at DESC LIMIT 20", (tab["id"],))
        if rows:
            sections.append({
                "id": -1,
                "type": "posts",
                "title": tab["name"],
                "cfg": {"limit": 20},
                "items": [post_row_to_dict(r) for r in rows],
            })
    ctx = base_ctx(slug, tab["name"])
    ctx["tab"] = dict(tab)
    if sections:
        ctx["sections"] = sections
    else:
        fallback_type, items = fallback_content(tab)
        ctx["fallback"] = {"type": fallback_type, "items": items}
    # Dedicated templates render the first section's items directly.
    if template in DEDICATED.values():
        if ctx.get("sections"):
            ctx["items"] = ctx["sections"][0]["items"]
        elif ctx.get("fallback"):
            ctx["items"] = ctx["fallback"]["items"]
        else:
            ctx["items"] = []
        if template == "pics.html":
            counts = {}
            covers = {}
            for ph in ctx["items"]:
                albums = ph.get("albums") or ["misc"]
                for album in albums:
                    counts[album] = counts.get(album, 0) + 1
                    if album not in covers:
                        covers[album] = ph.get("url")
            ctx["albums"] = [
                {"name": k, "count": v, "cover": covers.get(k)}
                for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ]
    return render_template(template, **ctx)


# ── Public routes ──────────────────────────────────────────────────────────────
@app.route("/")
def home():
    settings = load_settings()
    limit = int(settings.get("posts_per_page") or 6)
    posts = [post_row_to_dict(r) for r in db.query(
        "SELECT p.*, t.slug AS tab_slug, t.name AS tab_name"
        " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id"
        " WHERE p.published=1 AND p.status!='hidden'"
        " ORDER BY p.pinned DESC, p.created_at DESC LIMIT ?", (limit,))]
    ctx = base_ctx("index", "Home")
    ctx["posts"] = posts
    return render_template("index.html", **ctx)


@app.route("/<slug>")
def page_view(slug):
    if slug in DEDICATED:
        return render_page(slug, DEDICATED[slug])
    return render_page(slug, "page.html")


@app.route("/page")
def page_param():
    slug = request.args.get("slug", "index")
    if slug == "index":
        return redirect(url_for("home"))
    if slug in DEDICATED:
        return render_page(slug, DEDICATED[slug])
    return render_page(slug, "page.html")


@app.route("/<slug>.html")
def legacy_html(slug):
    if slug == "index":
        return redirect(url_for("home"), 301)
    if slug in DEDICATED or slug in GENERIC or db.query_one("SELECT id FROM tabs WHERE slug=?", (slug,)):
        return redirect(url_for("page_view", slug=slug), 301)
    abort(404)


@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    results = {"posts": [], "books": []}
    if q:
        # Token-based fuzzy match: every word of the query must appear
        # somewhere in the title / subtitle / excerpt / content / tags / page.
        tokens = [t for t in re.split(r"[^\w]+", q.lower()) if t]
        if tokens:
            post_where = " AND ".join(
                "(p.title LIKE ? OR p.subtitle LIKE ? OR p.excerpt LIKE ?"
                " OR p.content LIKE ? OR p.tags LIKE ? OR t.name LIKE ?)"
                for _ in tokens
            )
            post_params = []
            for t in tokens:
                like = "%" + t + "%"
                post_params += [like, like, like, like, like, like]
            results["posts"] = [post_row_to_dict(r) for r in db.query(
                "SELECT p.*, t.slug AS tab_slug, t.name AS tab_name"
                " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id"
                " WHERE p.published=1 AND p.status!='hidden' AND ("
                + post_where + ")"
                " ORDER BY p.created_at DESC LIMIT 20", post_params)]
            book_where = " AND ".join("(title LIKE ? OR author LIKE ?)" for _ in tokens)
            book_params = []
            for t in tokens:
                like = "%" + t + "%"
                book_params += [like, like]
            results["books"] = [dict(r) for r in db.query(
                "SELECT * FROM books WHERE status='published' AND ("
                + book_where + ") LIMIT 10", book_params)]
    ctx = base_ctx("search", "Search")
    ctx["q"] = q
    ctx["results"] = results
    return render_template("search.html", **ctx)


@app.route("/guestbook", methods=["GET", "POST"])
def guestbook():
    settings = load_settings()
    ctx = base_ctx("guestbook", "Guestbook")
    ctx["tab"] = {"name": "Guestbook", "page_type": "guestbook"}
    ctx["flash_msg"] = None
    ctx["flash_err"] = None
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        message = (request.form.get("message") or "").strip()
        website = (request.form.get("website") or "").strip()
        if not name or not message:
            ctx["flash_err"] = "Name and message are required."
        elif len(name) > 80 or len(message) > 500:
            ctx["flash_err"] = "Message is too long."
        elif website and not website.startswith(("http://", "https://")):
            ctx["flash_err"] = "Website must start with http:// or https://"
        elif settings.get("guestbook_open", "true") == "false":
            ctx["flash_err"] = "The guestbook is currently closed."
        else:
            db.execute(
                "INSERT INTO guestbook_entries(name,message,website,status,created_at)"
                " VALUES(?,?,?,'approved',?)",
                (name, message, website or None, db.now_iso()),
            )
            backup.snapshot()
            ctx["flash_msg"] = "Thanks for signing \u2726 your message is now live!"
    entries = [dict(r) for r in db.query(
        "SELECT * FROM guestbook_entries WHERE status='approved'"
        " ORDER BY created_at DESC LIMIT 50")]
    ctx["entries"] = entries
    return render_template("guestbook.html", **ctx)


@app.route("/post/<int:post_id>")
def post_view(post_id):
    row = db.query_one(
        "SELECT p.*, t.slug AS tab_slug, t.name AS tab_name"
        " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id WHERE p.id=?", (post_id,))
    if not row:
        abort(404)
    post = post_row_to_dict(row)
    ctx = base_ctx("post", post.get("tab_name") or "Post")
    ctx["post"] = post
    ctx["gallery"] = gallery_images(post)
    return render_template("post.html", **ctx)


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(storage.UPLOAD_DIR, filename)


@app.route("/ballas")
def ballas():
    # Secret page: fully self-contained (own CSS + embedded fonts), served as-is.
    return send_from_directory(app.root_path, "ballas.html")


@app.route("/borat")
def borat():
    return send_from_directory(app.root_path, "borat.html")


@app.route("/photos/<path:filename>")
def photos(filename):
    return send_from_directory(os.path.join(app.root_path, "photos"), filename)


@app.route("/papers/<path:filename>")
def papers(filename):
    return send_from_directory(os.path.join(app.root_path, "papers"), filename)


@app.errorhandler(404)
def not_found(_e):
    ctx = base_ctx("404", "Not Found")
    return render_template("404.html", **ctx), 404


# ── API (ported from the old Vercel backend) ───────────────────────────────────
@app.route("/api/now-playing")
def api_now_playing():
    return jsonify(spotify.now_playing())


@app.route("/api/top-stats")
def api_top_stats():
    return jsonify(spotify.top_stats())


@app.route("/api/visitors")
def api_visitors():
    page = request.args.get("page", "home")
    count = visitors_for(page)
    return jsonify({"count": count, "visitors": count})


# ── CLI ────────────────────────────────────────────────────────────────────────
@app.cli.command("init-db")
def init_db_command():
    db.init_db()
    print("database initialised")


@app.cli.command("seed")
def seed_command():
    db.init_db()
    import seed as seed_mod
    result = seed_mod.seed_all()
    print("seeded:", result)


if __name__ == "__main__":
    app.run(debug=True)
