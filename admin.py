"""Admin panel: password login + CRUD for every content table + seeder."""
import json
import os
import re
import uuid
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

import backup
import db
import storage

admin_bp = Blueprint("admin", __name__)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

ALLOWED_EXT = {
    ".mp3", ".wav", ".ogg", ".flac", ".m4a",
    ".mp4", ".webm", ".mov", ".mkv", ".avi",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".pdf", ".txt", ".zip",
}
MAX_UPLOAD = 50 * 1024 * 1024

# Every column that can reference an uploaded file (by its /uploads/… URL).
# Moving media rewrites each occurrence so the site follows automatically.
REFC_COLUMNS = [
    ("posts", "image_url"),
    ("posts", "content"),
    ("books", "cover_url"),
    ("music", "cover_url"),
    ("photos", "url"),
    ("sections", "config"),
    ("site_settings", "value"),
]

FOLDER_OK = re.compile(r"^[\w .\-]+$")


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def _form_value(key, default=None):
    v = request.form.get(key)
    return v.strip() if isinstance(v, str) else v


# ── Entity specs for the generic list/edit views ───────────────────────────────
# columns: (header, key) ; fields: (name, label, type)
ENTITY_FIELDS = {
    "posts": [
        ("title", "Title", "text"),
        ("tab_id", "Page", "tab"),
        ("subtitle", "Subtitle", "text"),
        ("excerpt", "Excerpt", "textarea"),
        ("content", "Content (markdown)", "textarea"),
        ("image_url", "Image URL", "text"),
        ("tags", "Tags (comma separated)", "tags"),
        ("status", "Status", "select:live,draft,hidden"),
        ("published", "Published", "checkbox"),
        ("pinned", "Pinned", "checkbox"),
    ],
    "books": [
        ("title", "Title", "text"),
        ("author", "Author", "text"),
        ("rating", "Rating (0-10)", "number"),
        ("cover_url", "Cover URL", "text"),
        ("year_read", "Year read", "text"),
        ("status", "Status", "select:published,draft"),
        ("review", "Review", "textarea"),
    ],
    "music": [
        ("title", "Title", "text"),
        ("artist", "Artist", "text"),
        ("type", "Type (album / track / artist)", "text"),
        ("cover_url", "Cover URL", "text"),
        ("rating", "Rating (0-5)", "number"),
        ("status", "Status", "select:published,draft"),
    ],
    "photos": [
        ("url", "Photo URL", "text"),
        ("caption", "Caption", "text"),
        ("album", "Albums (comma separated)", "albums"),
        ("tags", "Tags (comma separated)", "tags"),
        ("alt_text", "Alt text", "text"),
        ("visible", "Visible", "checkbox"),
    ],
    "links": [
        ("label", "Label", "text"),
        ("url", "URL", "text"),
        ("description", "Description", "textarea"),
        ("category", "Category", "text"),
        ("visible", "Visible", "checkbox"),
    ],
    "tabs": [
        ("name", "Name", "text"),
        ("slug", "Slug", "text"),
        ("page_type", "Page type", "select:standard,posts,books,photos,music,links,guestbook,home"),
        ("visible", "Visible (in nav)", "checkbox"),
        ("position", "Position", "number"),
    ],
    "sections": [
        ("tab_id", "Page", "tab"),
        ("type", "Type", "select:hero,text,posts,books,photos,music,links,guestbook"),
        ("title", "Title", "text"),
        ("config", "Config (JSON)", "textarea"),
        ("visible", "Visible", "checkbox"),
        ("position", "Position", "number"),
    ],
}


def _parse_field_value(fname, ftype, raw):
    if ftype == "checkbox":
        return 1 if raw else 0
    if ftype == "number":
        raw = (raw or "").strip()
        try:
            return float(raw) if raw else None
        except ValueError:
            return None
    if ftype == "tab":
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None
    if ftype == "tags":
        return db.list_to_tags(raw or "")
    if ftype == "albums":
        parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
        return db.serialize_albums(parts)
    return (raw or "").strip() or None


def _display_row(entity, row):
    d = dict(row)
    if entity == "posts":
        d["tab_name"] = (d.get("tab_name") or "—")
        d["status"] = "published" if d.get("published") and d.get("status") == "live" else d.get("status") or "draft"
        d["tags_list"] = db.tags_to_list(d)
    if entity == "photos":
        if d.get("album"):
            d["album"] = ", ".join(db.parse_albums(d["album"]))
        d["tags"] = ", ".join(db.tags_to_list(d))
        d["albums_list"] = db.parse_albums(d.get("album")) if d.get("album") else []
        d["tags_list"] = db.tags_to_list(d)
        d["visible"] = 1 if d.get("visible") else 0
    return d


def _list_sql(entity):
    base = {
        "posts": "SELECT p.*, t.name AS tab_name FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id",
        "books": "SELECT * FROM books",
        "music": "SELECT * FROM music",
        "photos": "SELECT * FROM photos",
        "links": "SELECT * FROM links",
        "tabs": "SELECT * FROM tabs",
        "sections": "SELECT s.*, t.name AS tab_name FROM sections s LEFT JOIN tabs t ON s.tab_id=t.id",
    }[entity]
    order = {
        "posts": " ORDER BY p.created_at DESC",
        "books": " ORDER BY created_at DESC",
        "music": " ORDER BY created_at DESC",
        "photos": " ORDER BY position",
        "links": " ORDER BY position",
        "tabs": " ORDER BY position",
        "sections": " ORDER BY s.position",
    }[entity]
    return base + order


def _columns(entity):
    """Return (key, header) pairs — list.html unpacks them as (key, label)."""
    return {
        "posts": [("title", "Title"), ("tab_name", "Page"), ("status", "Status"), ("created_at", "Date")],
        "books": [("title", "Title"), ("author", "Author"), ("rating", "Rating"), ("status", "Status")],
        "music": [("title", "Title"), ("artist", "Artist"), ("type", "Type"), ("status", "Status")],
        "photos": [("url", "URL"), ("album", "Album"), ("caption", "Caption"), ("visible", "Visible")],
        "links": [("label", "Label"), ("url", "URL"), ("category", "Category"), ("visible", "Visible")],
        "tabs": [("name", "Name"), ("slug", "Slug"), ("page_type", "Page type"), ("visible", "Visible")],
        "sections": [("type", "Type"), ("title", "Title"), ("tab_name", "Page"), ("visible", "Visible")],
    }[entity]


def _entity_context(entity, tablename, extra=None):
    rows = [_display_row(entity, r) for r in db.query(_list_sql(entity))]
    ctx = {
        "entity": entity,
        "entity_label": extra.pop("entity_label") if extra and "entity_label" in extra else entity,
        "columns": _columns(entity),
        "rows": rows,
        "fields": ENTITY_FIELDS[entity],
    }
    if extra:
        ctx.update(extra)
    return ctx


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or url_for("admin.dashboard")
    if request.method == "POST":
        if _form_value("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(next_url)
        flash("Wrong password", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("home"))


@admin_bp.route("")
@admin_bp.route("/")
@require_admin
def dashboard():
    counts = {}
    for entity in ["tabs", "posts", "books", "music", "photos", "links", "guestbook_entries", "pending_users", "media"]:
        counts[entity] = db.query_one("SELECT COUNT(*) AS n FROM %s" % entity)["n"]
    counts["pending_gb"] = db.query_one(
        "SELECT COUNT(*) AS n FROM guestbook_entries WHERE status='pending'")["n"]
    counts["pending_users"] = db.query_one(
        "SELECT COUNT(*) AS n FROM pending_users WHERE status='pending'")["n"]
    recent = [dict(r) for r in db.query(
        "SELECT p.id, p.title, p.created_at, p.status, t.slug AS tab_slug"
        " FROM posts p LEFT JOIN tabs t ON p.tab_id=t.id"
        " ORDER BY p.created_at DESC LIMIT 8")]
    return render_template(
        "admin/dashboard.html", counts=counts, recent=recent, active="dashboard")


@admin_bp.route("/<entity>")
@require_admin
def list_entity(entity):
    if entity not in ENTITY_FIELDS:
        abort(404)
    rows = [_display_row(entity, r) for r in db.query(_list_sql(entity))]
    return render_template(
        "admin/list.html",
        entity=entity,
        entity_label=entity.replace("_", " ").title(),
        columns=_columns(entity),
        rows=rows,
        active=entity,
    )


@admin_bp.route("/<entity>/new", methods=["GET", "POST"])
@admin_bp.route("/<entity>/<int:item_id>/edit", methods=["GET", "POST"])
@require_admin
def edit_entity(entity, item_id=None):
    if entity not in ENTITY_FIELDS:
        abort(404)
    record = None
    if item_id:
        record = db.query_one("SELECT * FROM %s WHERE id=?" % entity, (item_id,))
        if not record:
            abort(404)
        record = dict(record)
        if entity == "posts" and record.get("tags"):
            record["tags"] = ", ".join(db.tags_to_list(record))
        if entity == "photos":
            if record.get("album"):
                record["album"] = ", ".join(db.parse_albums(record["album"]))
            if record.get("tags"):
                record["tags"] = ", ".join(db.tags_to_list(record))

    if request.method == "POST":
        data = {}
        for fname, _label, ftype in ENTITY_FIELDS[entity]:
            data[fname] = _parse_field_value(fname, ftype, request.form.get(fname))
        if entity == "posts":
            data["created_at"] = record["created_at"] if record else db.now_iso()
        if entity in ("photos", "links") and not record:
            n = db.query_one("SELECT COUNT(*) AS n FROM %s" % entity)["n"]
            data.setdefault("position", n)
            data.setdefault("created_at", db.now_iso())
        if entity == "books" and not data.get("cover_url"):
            import books
            data["cover_url"] = books.cover_for(data)
        if item_id:
            sets = ", ".join("%s=?" % k for k in data)
            db.execute("UPDATE %s SET %s WHERE id=?" % (entity, sets), list(data.values()) + [item_id])
            flash("Saved", "ok")
        else:
            cols = ", ".join(data.keys())
            ph = ", ".join("?" for _ in data)
            db.execute("INSERT INTO %s (%s) VALUES (%s)" % (entity, cols, ph), list(data.values()))
            flash("Created", "ok")
        backup.snapshot()
        return redirect(url_for("admin.list_entity", entity=entity))

    albums_all = sorted({
        a
        for r in db.query("SELECT album FROM photos WHERE album IS NOT NULL AND album != ''")
        for a in db.parse_albums(r["album"])
    })
    return render_template(
        "admin/edit.html",
        entity=entity,
        record=record,
        fields=ENTITY_FIELDS[entity],
        tabs=db.query("SELECT id, name FROM tabs ORDER BY position"),
        albums_all=albums_all,
        active=entity,
    )


@admin_bp.route("/preview", methods=["POST"])
@require_admin
def preview():
    """Render markdown for the posts editor live preview."""
    from app import md
    return md(request.form.get("content") or "")


@admin_bp.route("/<entity>/<int:item_id>/delete", methods=["POST"])
@require_admin
def delete_entity(entity, item_id):
    if entity in ENTITY_FIELDS:
        db.execute("DELETE FROM %s WHERE id=?" % entity, (item_id,))
        backup.snapshot()
        flash("Deleted", "ok")
    return redirect(url_for("admin.list_entity", entity=entity))


@admin_bp.route("/<entity>/<int:item_id>/toggle", methods=["POST"])
@require_admin
def toggle_entity(entity, item_id):
    """Quick show/hide flip from the list view."""
    if entity == "posts":
        row = db.query_one("SELECT status FROM posts WHERE id=?", (item_id,))
        if row:
            new = "hidden" if row["status"] != "hidden" else "live"
            db.execute("UPDATE posts SET status=? WHERE id=?", (new, item_id))
            flash("Post now %s" % ("hidden" if new == "hidden" else "visible"), "ok")
    elif entity in ("books", "music"):
        row = db.query_one("SELECT status FROM %s WHERE id=?" % entity, (item_id,))
        if row:
            new = "draft" if row["status"] == "published" else "published"
            db.execute("UPDATE %s SET status=? WHERE id=?" % entity, (new, item_id))
            flash("%s now %s" % (entity, new), "ok")
    elif entity in ("photos", "links"):
        row = db.query_one("SELECT visible FROM %s WHERE id=?" % entity, (item_id,))
        if row:
            new = 0 if row["visible"] else 1
            db.execute("UPDATE %s SET visible=? WHERE id=?" % entity, (new, item_id))
            flash("%s now %s" % (entity, "hidden" if not new else "visible"), "ok")
    backup.snapshot()
    return redirect(url_for("admin.list_entity", entity=entity))


@admin_bp.route("/upload", methods=["POST"])
@require_admin
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "unsupported file type: %s" % ext}), 400
    blob = f.read()
    if len(blob) > MAX_UPLOAD:
        return jsonify({"error": "file too large (max 50MB)"}), 400
    folder = request.form.get("folder", "").strip().strip("/\\")
    if folder and not FOLDER_OK.match(folder):
        return jsonify({"error": "invalid folder name"}), 400
    name = uuid.uuid4().hex[:12] + ext
    rel = name if not folder else folder + "/" + name
    os.makedirs(os.path.join(storage.UPLOAD_DIR, os.path.dirname(rel)), exist_ok=True)
    with open(os.path.join(storage.UPLOAD_DIR, rel), "wb") as fh:
        fh.write(blob)
    if storage.durable():
        try:
            if len(blob) <= storage.MAX_MEDIA:
                storage.save_media(rel, blob)
            else:
                flash("File stored locally only (over %dMB — won't survive a redeploy)" % (storage.MAX_MEDIA // (1024 * 1024)), "error")
        except Exception:
            pass
    media_id = db.execute(
        "INSERT INTO media(filename,url,content_type,size,created_at) VALUES(?,?,?,?,?)",
        (rel, "/uploads/" + rel, f.mimetype or "application/octet-stream", len(blob), db.now_iso()),
    )
    backup.snapshot()
    return jsonify({"id": media_id, "url": "/uploads/" + rel, "filename": f.filename, "size": len(blob)})


@admin_bp.route("/media")
@require_admin
def media_library():
    rows = [dict(r) for r in db.query("SELECT * FROM media ORDER BY created_at DESC")]
    folders = set()
    for r in rows:
        r["folder"] = os.path.dirname(r["filename"].replace("\\", "/"))
        r["refs"] = _count_refs(r["url"])
        if r["folder"]:
            folders.add(r["folder"])
    return render_template("admin/media.html", rows=rows, folders=sorted(folders), active="media")


def _count_refs(url):
    n = 0
    for table, col in REFC_COLUMNS:
        r = db.query_one(
            "SELECT COUNT(*) AS c FROM %s WHERE %s LIKE ?" % (table, col),
            ("%" + url + "%",),
        )
        if r and r["c"]:
            n += int(r["c"])
    return n


def _rewrite_url(old_url, new_url):
    """Point every stored reference at the new URL. Returns rows touched."""
    changed = 0
    esc = old_url.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    for table, col in REFC_COLUMNS:
        changed += db.execute_update(
            "UPDATE %s SET %s = REPLACE(%s, ?, ?) WHERE %s LIKE ? ESCAPE '\\'"
            % (table, col, col, col),
            (old_url, new_url, "%" + esc + "%"),
        )
    return changed


@admin_bp.route("/media/<int:item_id>/move", methods=["POST"])
@require_admin
def move_media(item_id):
    row = db.query_one("SELECT * FROM media WHERE id=?", (item_id,))
    if not row:
        flash("media not found", "error")
        return redirect(url_for("admin.media_library"))
    folder = request.form.get("folder", "").strip().strip("/\\")
    if folder and not FOLDER_OK.match(folder):
        flash("invalid folder name", "error")
        return redirect(url_for("admin.media_library"))
    old_rel = row["filename"]
    old_url = row["url"]
    base = os.path.basename(old_rel.replace("\\", "/"))
    new_rel = base if not folder else folder + "/" + base
    if new_rel == old_rel:
        flash("already in that folder", "ok")
        return redirect(url_for("admin.media_library"))
    dst = os.path.join(storage.UPLOAD_DIR, new_rel)
    if os.path.exists(dst):
        root, ext = os.path.splitext(base)
        n = 1
        while True:
            candidate = "%s-%d%s" % (root, n, ext)
            candidate_rel = candidate if not folder else folder + "/" + candidate
            if not os.path.exists(os.path.join(storage.UPLOAD_DIR, candidate_rel)):
                new_rel, base = candidate_rel, candidate
                dst = os.path.join(storage.UPLOAD_DIR, candidate_rel)
                break
            n += 1
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    src = os.path.join(storage.UPLOAD_DIR, old_rel)
    if os.path.exists(src):
        os.rename(src, dst)
    if storage.durable():
        try:
            storage.move_media(old_rel, new_rel)
        except Exception:
            pass
    new_url = "/uploads/" + new_rel
    db.execute("UPDATE media SET filename=?, url=? WHERE id=?", (new_rel, new_url, item_id))
    changed = _rewrite_url(old_url, new_url)
    backup.snapshot()
    where = folder if folder else "root"
    flash(
        "Moved to %s (updated %d reference%s)" % (where, changed, "" if changed == 1 else "s"),
        "ok",
    )
    return redirect(url_for("admin.media_library"))


@admin_bp.route("/media/<int:item_id>/delete", methods=["POST"])
@require_admin
def delete_media(item_id):
    row = db.query_one("SELECT * FROM media WHERE id=?", (item_id,))
    if row:
        path = os.path.join(storage.UPLOAD_DIR, row["filename"])
        if os.path.exists(path):
            os.remove(path)
        if storage.durable():
            try:
                storage.delete_media(row["filename"])
            except Exception:
                pass
        db.execute("DELETE FROM media WHERE id=?", (item_id,))
        backup.snapshot()
        flash("Deleted", "ok")
    return redirect(url_for("admin.media_library"))


@admin_bp.route("/photos/upload", methods=["POST"])
@require_admin
def photo_upload():
    """Upload an image and create a visible photo row in one step."""
    f = request.files.get("file")
    if not f or not f.filename:
        flash("no file provided", "error")
        return redirect(url_for("admin.list_entity", entity="photos"))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        flash("unsupported file type: %s" % ext, "error")
        return redirect(url_for("admin.list_entity", entity="photos"))
    blob = f.read()
    if len(blob) > MAX_UPLOAD:
        flash("file too large (max 50MB)", "error")
        return redirect(url_for("admin.list_entity", entity="photos"))
    name = uuid.uuid4().hex[:12] + ext
    os.makedirs(storage.UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(storage.UPLOAD_DIR, name), "wb") as fh:
        fh.write(blob)
    if storage.durable():
        try:
            if len(blob) <= storage.MAX_MEDIA:
                storage.save_media(name, blob)
        except Exception:
            pass
    url = "/uploads/" + name
    n = db.query_one("SELECT COUNT(*) AS n FROM photos")["n"]
    photo_id = db.execute(
        "INSERT INTO photos(url,caption,album,tags,visible,position,created_at)"
        " VALUES(?,?,?,?,1,?,?)",
        (url, request.form.get("caption") or None, None, None, n, db.now_iso()),
    )
    db.execute(
        "INSERT INTO media(filename,url,content_type,size,created_at) VALUES(?,?,?,?,?)",
        (name, url, f.mimetype or "application/octet-stream", len(blob), db.now_iso()),
    )
    backup.snapshot()
    flash("Photo added — live on /pics", "ok")
    return redirect(url_for("admin.edit_entity", entity="photos", item_id=photo_id))


@admin_bp.route("/books/fetch-covers", methods=["POST"])
@require_admin
def books_fetch_covers():
    import books
    n = books.fetch_missing()
    backup.snapshot()
    flash("Fetched %d cover%s from Open Library" % (n, "" if n == 1 else "s"), "ok")
    return redirect(url_for("admin.list_entity", entity="books"))


@admin_bp.route("/ledgerline")
@require_admin
def ledgerline():
    """Backend-exclusive tool — only reachable when logged in. The file is a
    self-contained React app (own CSS + CDN scripts), so it's served as-is;
    Jinja would choke on its JSX braces."""
    return send_from_directory(current_app.root_path, "ledgerline.html")


@admin_bp.route("/guestbook", methods=["GET", "POST"])
@require_admin
def guestbook_admin():
    if request.method == "POST":
        action = request.form.get("action")
        item_id = request.form.get("id")
        if item_id and action in ("approve", "reject", "delete"):
            if action == "approve":
                db.execute("UPDATE guestbook_entries SET status='approved' WHERE id=?", (item_id,))
            elif action == "reject":
                db.execute("UPDATE guestbook_entries SET status='rejected' WHERE id=?", (item_id,))
            else:
                db.execute("DELETE FROM guestbook_entries WHERE id=?", (item_id,))
            backup.snapshot()
            flash("Done", "ok")
        return redirect(url_for("admin.guestbook_admin"))
    entries = [dict(r) for r in db.query(
        "SELECT * FROM guestbook_entries ORDER BY created_at DESC")]
    return render_template("admin/guestbook.html", entries=entries, active="guestbook")


@admin_bp.route("/users", methods=["GET", "POST"])
@require_admin
def users_admin():
    if request.method == "POST":
        action = request.form.get("action")
        item_id = request.form.get("id")
        if item_id and action in ("approve", "reject", "delete"):
            if action == "approve":
                db.execute("UPDATE pending_users SET status='approved' WHERE id=?", (item_id,))
            elif action == "reject":
                db.execute("UPDATE pending_users SET status='rejected' WHERE id=?", (item_id,))
            else:
                db.execute("DELETE FROM pending_users WHERE id=?", (item_id,))
            flash("Done", "ok")
        return redirect(url_for("admin.users_admin"))
    users = [dict(r) for r in db.query("SELECT * FROM pending_users ORDER BY created_at DESC")]
    return render_template("admin/users.html", users=users, active="users")


SETTING_FIELDS = [
    ("site_title", "Site title"),
    ("site_tagline", "Tagline"),
    ("site_footer", "Footer tagline"),
    ("marquee_text", "Marquee text"),
    ("posts_per_page", "Posts per page"),
    ("guestbook_open", "Guestbook open (true/false)"),
]


@admin_bp.route("/settings", methods=["GET", "POST"])
@require_admin
def settings_admin():
    if request.method == "POST":
        for key, _label in SETTING_FIELDS:
            if key == "guestbook_open":
                value = "true" if _form_value(key) else "false"
            else:
                value = _form_value(key) or ""
            db.execute(
                "INSERT INTO site_settings(key,value) VALUES(?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        flash("Settings saved", "ok")
        backup.snapshot()
        return redirect(url_for("admin.settings_admin"))
    current = {r["key"]: r["value"] for r in db.query("SELECT key, value FROM site_settings")}
    return render_template("admin/settings.html", fields=SETTING_FIELDS, current=current, active="settings")


@admin_bp.route("/import", methods=["GET", "POST"])
@require_admin
def import_admin():
    import seed as seed_mod
    if request.method == "POST":
        which = request.form.get("which", "all")
        fns = {
            "pages": seed_mod.seed_pages,
            "books": seed_mod.seed_books,
            "papers": seed_mod.seed_papers,
            "photos": seed_mod.seed_photos,
            "sections": seed_mod.seed_sections,
            "settings": seed_mod.seed_settings,
        }
        if which == "all":
            result = seed_mod.seed_all()
            flash("Import complete: %s" % json.dumps(result), "ok")
        elif which in fns:
            n = fns[which]()
            flash("Import done: %s added %s" % (which, n), "ok")
        return redirect(url_for("admin.import_admin"))
    return render_template("admin/import.html", active="import")
