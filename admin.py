"""Admin panel: password login + CRUD for every content table + seeder."""
import json
import os
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import db

admin_bp = Blueprint("admin", __name__)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


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
        ("url", "URL", "text"),
        ("caption", "Caption", "text"),
        ("alt_text", "Alt text", "text"),
        ("album", "Album", "text"),
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
    return (raw or "").strip() or None


def _display_row(entity, row):
    d = dict(row)
    if entity == "posts":
        d["tab_name"] = (d.get("tab_name") or "—")
        d["status"] = "published" if d.get("published") and d.get("status") == "live" else d.get("status") or "draft"
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


@admin_bp.route("/")
@require_admin
def dashboard():
    counts = {}
    for entity in ["tabs", "posts", "books", "music", "photos", "links", "guestbook_entries", "pending_users"]:
        counts[entity] = db.query_one("SELECT COUNT(*) AS n FROM %s" % entity)["n"]
    counts["pending_guestbook"] = db.query_one(
        "SELECT COUNT(*) AS n FROM guestbook_entries WHERE status='pending'")["n"]
    counts["pending_users"] = db.query_one(
        "SELECT COUNT(*) AS n FROM pending_users WHERE status='pending'")["n"]
    return render_template("admin/dashboard.html", counts=counts, active="dashboard")


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
        if item_id:
            sets = ", ".join("%s=?" % k for k in data)
            db.execute("UPDATE %s SET %s WHERE id=?" % (entity, sets), list(data.values()) + [item_id])
            flash("Saved", "ok")
        else:
            cols = ", ".join(data.keys())
            ph = ", ".join("?" for _ in data)
            db.execute("INSERT INTO %s (%s) VALUES (%s)" % (entity, cols, ph), list(data.values()))
            flash("Created", "ok")
        return redirect(url_for("admin.list_entity", entity=entity))

    return render_template(
        "admin/edit.html",
        entity=entity,
        record=record,
        fields=ENTITY_FIELDS[entity],
        tabs=db.query("SELECT id, name FROM tabs ORDER BY position"),
        active=entity,
    )


@admin_bp.route("/<entity>/<int:item_id>/delete", methods=["POST"])
@require_admin
def delete_entity(entity, item_id):
    if entity in ENTITY_FIELDS:
        db.execute("DELETE FROM %s WHERE id=?" % entity, (item_id,))
        flash("Deleted", "ok")
    return redirect(url_for("admin.list_entity", entity=entity))


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
