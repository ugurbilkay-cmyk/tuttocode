import json
import secrets
import sqlite3
import time
from contextlib import contextmanager

from . import config

# No 0/O/1/I/l to avoid typos when customers type the code.
CODE_ALPHABET = "23456789abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    code TEXT UNIQUE,
    status TEXT NOT NULL,          -- pending | issued | rejected
    source TEXT NOT NULL,          -- shop | online
    age_group TEXT NOT NULL DEFAULT 'adult',
    name TEXT, email TEXT, phone TEXT,
    checks TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    issued REAL,
    expires REAL NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    last_fetched REAL
);
CREATE INDEX IF NOT EXISTS idx_photos_code ON photos(code);
CREATE INDEX IF NOT EXISTS idx_photos_expires ON photos(expires);
CREATE TABLE IF NOT EXISTS fetch_log (
    ts REAL NOT NULL, code TEXT, ok INTEGER, reason TEXT, ip TEXT
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def new_id():
    return secrets.token_urlsafe(12)


def new_code(c):
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(config.CODE_LENGTH))
        if not c.execute("SELECT 1 FROM photos WHERE code=?", (code,)).fetchone():
            return code


def create(photo_id, source, age_group, result, name=None, email=None, phone=None):
    now = time.time()
    with conn() as c:
        c.execute(
            "INSERT INTO photos (id,status,source,age_group,name,email,phone,checks,ok,created,expires)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (photo_id, "pending", source, age_group, name, email, phone,
             json.dumps(result.as_dict()["checks"]), int(result.ok), now,
             now + config.PENDING_RETENTION_HOURS * 3600),
        )


def update_contact(photo_id, name, email, phone):
    with conn() as c:
        c.execute("UPDATE photos SET name=?, email=?, phone=? WHERE id=?", (name, email, phone, photo_id))


def issue(photo_id):
    now = time.time()
    with conn() as c:
        row = c.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            return None
        if row["code"]:
            return row["code"]
        code = new_code(c)
        c.execute(
            "UPDATE photos SET code=?, status='issued', issued=?, expires=? WHERE id=?",
            (code, now, now + config.RETENTION_DAYS * 86400, photo_id),
        )
        return code


def reject(photo_id):
    with conn() as c:
        c.execute("UPDATE photos SET status='rejected' WHERE id=?", (photo_id,))


def get(photo_id):
    with conn() as c:
        return c.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()


def by_code(code):
    with conn() as c:
        return c.execute(
            "SELECT * FROM photos WHERE code=? AND status='issued' AND expires>?", (code, time.time())
        ).fetchone()


def mark_fetched(code):
    with conn() as c:
        c.execute(
            "UPDATE photos SET fetched_count=fetched_count+1, last_fetched=? WHERE code=?",
            (time.time(), code),
        )


def log_fetch(code, ok, reason, ip):
    with conn() as c:
        c.execute("INSERT INTO fetch_log VALUES (?,?,?,?,?)", (time.time(), code, int(ok), reason, ip))


def recent(limit=100):
    with conn() as c:
        return c.execute("SELECT * FROM photos ORDER BY created DESC LIMIT ?", (limit,)).fetchall()


def purge_expired():
    """Delete expired rows and their photo files. Returns number removed."""
    now = time.time()
    with conn() as c:
        rows = c.execute("SELECT id FROM photos WHERE expires<=? OR status='rejected'", (now,)).fetchall()
        for r in rows:
            for suffix in (".jpg", "_prev.jpg"):
                (config.PHOTO_DIR / f"{r['id']}{suffix}").unlink(missing_ok=True)
        c.execute("DELETE FROM photos WHERE expires<=? OR status='rejected'", (now,))
        c.execute("DELETE FROM fetch_log WHERE ts<?", (now - 90 * 86400,))
        return len(rows)
