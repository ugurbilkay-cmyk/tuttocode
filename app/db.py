import json
import secrets
import shutil
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
CREATE TABLE IF NOT EXISTS govuk_checks (
    id TEXT PRIMARY KEY, photo_id TEXT NOT NULL, revision INTEGER NOT NULL,
    country_id TEXT NOT NULL, master_sha256 TEXT NOT NULL, photo_sha256 TEXT NOT NULL,
    status TEXT NOT NULL, created REAL NOT NULL, finished REAL,
    staff TEXT NOT NULL, synthetic_dob INTEGER NOT NULL,
    result TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_govuk_photo ON govuk_checks(photo_id, created);
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
        columns = {r["name"] for r in c.execute("PRAGMA table_info(photos)")}
        # Existing issued codes retain their UK profile and photo bytes.
        for name, definition in {
            "country_id": "TEXT NOT NULL DEFAULT 'united-kingdom-passport'",
            "print_template_id": "TEXT",
            "options": "TEXT NOT NULL DEFAULT '{}'",
            "measurements": "TEXT NOT NULL DEFAULT '{}'",
            "revision": "INTEGER NOT NULL DEFAULT 0",
            "edit_token": "TEXT",
            "edit_started": "REAL",
            "ai_state": "TEXT NOT NULL DEFAULT '{}'",
            "issue_review": "TEXT NOT NULL DEFAULT '{}'",
            "external_review": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            if name not in columns:
                c.execute(f"ALTER TABLE photos ADD COLUMN {name} {definition}")


def new_id():
    return secrets.token_urlsafe(12)


def new_code(c):
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(config.CODE_LENGTH))
        if not c.execute("SELECT 1 FROM photos WHERE code=?", (code,)).fetchone():
            return code


def create(photo_id, source, age_group, result, name=None, email=None, phone=None,
           country_id='united-kingdom-passport', print_template_id=None, options=None, external_review=None):
    now = time.time()
    with conn() as c:
        c.execute(
            "INSERT INTO photos (id,status,source,age_group,name,email,phone,checks,ok,created,expires)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (photo_id, "pending", source, age_group, name, email, phone,
             json.dumps(result.as_dict()["checks"]), int(result.ok), now,
             now + config.PENDING_RETENTION_HOURS * 3600),
        )
        c.execute("UPDATE photos SET country_id=?, print_template_id=?, options=?, measurements=?,external_review=? WHERE id=?",
                  (country_id, print_template_id, json.dumps(options or {}), json.dumps(result.measurements),
                   json.dumps(external_review or {}), photo_id))


def update_processing(photo_id, country_id, print_template_id, options, result, token=None):
    with conn() as c:
        c.execute("UPDATE photos SET country_id=?,print_template_id=?,options=?,checks=?,ok=?,measurements=?,revision=revision+1,ai_state='{}' WHERE id=? AND status='pending' AND edit_token IS ?",
                  (country_id, print_template_id, json.dumps(options), json.dumps(result.as_dict()['checks']),
                   int(result.ok), json.dumps(result.measurements), photo_id, token))


def claim_edit(photo_id, *, pending_only=True):
    """One editor per photo across processes, including slow external API calls."""
    token, now = secrets.token_urlsafe(24), time.time()
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row or row["expires"] <= now or row["status"] == "rejected":
            raise ValueError("Photo is missing or expired")
        if pending_only and row["status"] != "pending":
            raise ValueError("Issued photos cannot be edited")
        if row["edit_token"] and row["edit_started"] > now - max(900, config.OPENAI_TIMEOUT_SECONDS + 120, 2*config.BACKGROUND_TIMEOUT_SECONDS + 6*config.ENHANCER_TIMEOUT_SECONDS + 120):
            raise ValueError("This photo is being processed. Wait for it to finish.")
        c.execute("UPDATE photos SET edit_token=?,edit_started=? WHERE id=?", (token, now, photo_id))
    return token


def release_edit(photo_id, token):
    with conn() as c:
        c.execute("UPDATE photos SET edit_token=NULL,edit_started=NULL WHERE id=? AND edit_token=?", (photo_id, token))


def set_ai_state(photo_id, token, state):
    with conn() as c:
        changed = c.execute("UPDATE photos SET ai_state=? WHERE id=? AND edit_token=? AND status='pending' AND expires>?",
                            (json.dumps(state), photo_id, token, time.time())).rowcount
        if changed != 1:
            raise ValueError("The photo changed or expired during preparation")


def assert_edit(photo_id, token):
    row = get(photo_id)
    if not row or row["edit_token"] != token or row["expires"] <= time.time():
        raise ValueError("The photo changed or expired during preparation")
    return row


def update_contact(photo_id, name, email, phone):
    with conn() as c:
        c.execute("UPDATE photos SET name=?, email=?, phone=? WHERE id=?", (name, email, phone, photo_id))


def set_external_review(photo_id, record, checks, token):
    with conn() as c:
        changed = c.execute("UPDATE photos SET external_review=?,checks=?,ok=?,revision=revision+1 WHERE id=? AND edit_token=? AND status='pending' AND expires>?",
            (json.dumps(record), json.dumps([item.__dict__ for item in checks]),
             int(record['reviewed'] and not any(item.status != 'pass' for item in checks)), photo_id, token, time.time())).rowcount
        if changed != 1:
            raise ValueError('The photo changed or expired during review')


def issue(photo_id, review=None, token=None):
    now = time.time()
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            return None
        if row["code"]:
            return row["code"]
        if row["status"] != "pending" or row["expires"] <= now or row["edit_token"] != token:
            raise ValueError("Photo cannot be issued in its current state")
        code = new_code(c)
        c.execute(
            "UPDATE photos SET code=?, status='issued', issued=?, expires=?, issue_review=?, ai_state='{}' WHERE id=?",
            (code, now, now + config.RETENTION_DAYS * 86400, json.dumps(review or {}), photo_id),
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
            for suffix in PHOTO_SUFFIXES:
                (config.PHOTO_DIR / f"{r['id']}{suffix}").unlink(missing_ok=True)
            shutil.rmtree(config.GOVUK_DIR / r['id'], ignore_errors=True)
            c.execute("DELETE FROM govuk_checks WHERE photo_id=?", (r['id'],))
        c.execute("DELETE FROM photos WHERE expires<=? OR status='rejected'", (now,))
        c.execute("DELETE FROM fetch_log WHERE ts<?", (now - 90 * 86400,))
        if rows:
            from . import background
            background.clear_cache()
        return len(rows)


PHOTO_SUFFIXES = (".jpg", "_prev.jpg", "_before.jpg", "_source", "_working_source", "_code.jpg",
                  "_ai_source", "_ai.jpg", "_ai_prev.jpg", "_ai_before.jpg",
                  "_clean_before.png", "_clean_after.png", "_clean_mask.png")
