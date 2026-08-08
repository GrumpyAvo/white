"""Snapshot backup / restore of the content tables to durable storage."""
import json
import os

import db
import storage

BACKUP_TABLES = [
    "tabs",
    "posts",
    "books",
    "music",
    "photos",
    "links",
    "guestbook_entries",
    "sections",
    "site_settings",
    "media",
]


def snapshot():
    """Push the whole content DB to durable storage (no-op when unconfigured)."""
    if not storage.durable():
        return
    data = {}
    for table in BACKUP_TABLES:
        data[table] = [dict(r) for r in db.query("SELECT * FROM %s" % table)]
    try:
        storage.save_snapshot(json.dumps(data))
    except Exception:
        pass


def restore():
    """Pull content back into the local DB. Returns True if a snapshot was
    applied (fresh deploy case), else False."""
    if not storage.durable():
        return False
    try:
        raw = storage.load_snapshot()
    except Exception:
        return False
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return False
    for table, rows in data.items():
        if table not in BACKUP_TABLES or not isinstance(rows, list):
            continue
        db.execute("DELETE FROM %s" % table)
        for row in rows:
            if not isinstance(row, dict):
                continue
            cols = list(row.keys())
            placeholders = ",".join("?" for _ in cols)
            db.execute(
                "INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), placeholders),
                [row[c] for c in cols],
            )
    return True


def restore_media_files():
    """Re-download uploaded files to disk after a fresh deploy."""
    if not storage.durable():
        return
    os.makedirs(storage.UPLOAD_DIR, exist_ok=True)
    for r in db.query("SELECT filename FROM media"):
        path = os.path.join(storage.UPLOAD_DIR, r["filename"])
        if os.path.exists(path):
            continue
        try:
            blob = storage.load_media(r["filename"])
        except Exception:
            continue
        if blob:
            with open(path, "wb") as fh:
                fh.write(blob)
