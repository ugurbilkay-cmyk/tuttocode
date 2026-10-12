import asyncio
import base64
import contextlib
import json
import logging
import re
import secrets
import smtplib
import time
from collections import defaultdict, deque
from email.message import EmailMessage
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Host, Mount, Route, Router
from starlette.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

from . import config, db, hmpo_auth, processing, photomatic

log = logging.getLogger("tuttoid")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))
templates.env.globals.update(cfg=config, short_url=hmpo_auth.short_url, catalog=photomatic.CATALOG,
                             profiles=photomatic.COUNTRIES, printers=photomatic.PRINTERS)
templates.env.filters["dt"] = lambda t: time.strftime("%d %b %Y %H:%M", time.localtime(t)) if t else ""
templates.env.filters["fromjson"] = json.loads

CODE_RE = re.compile(r"^[A-Za-z0-9]{6,8}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,40}$")
AGE_GROUPS = {"adult": "Adult / 6+", "child": "Child 1–5", "baby": "Baby under 1"}


# ---------------------------------------------------------------- helpers
def _photo_path(pid, preview=False):
    if not ID_RE.match(pid):
        raise HTTPException(404)
    return config.PHOTO_DIR / (f"{pid}_prev.jpg" if preview else f"{pid}.jpg")


def _client_ip(request):
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


_hits = defaultdict(deque)


def _rate_limited(ip, limit=20, window=3600):
    q, now = _hits[ip], time.time()
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def _require_admin(request):
    if not config.ADMIN_PASSWORD:
        raise HTTPException(503, "Set ADMIN_PASSWORD to enable the station.")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
            if secrets.compare_digest(user, config.ADMIN_USER) and secrets.compare_digest(
                pw, config.ADMIN_PASSWORD
            ):
                if request.method == "POST":  # basic CSRF guard
                    origin = request.headers.get("origin") or request.headers.get("referer") or ""
                    if origin and urlparse(origin).netloc != request.headers.get("host"):
                        raise HTTPException(403, "Bad origin")
                return
        except HTTPException:
            raise
        except Exception:
            pass
    raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="Photo station"'})


async def _read_upload(request):
    form = await request.form(max_files=1, max_fields=30, max_part_size=64 * 1024)
    up = form.get("photo")
    if up is None or not hasattr(up, "read"):
        raise HTTPException(400, "No photo uploaded")
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    if up.size is not None and up.size > limit:
        await form.close()
        raise HTTPException(413, "Photo exceeds upload limit")
    data = await up.read(limit + 1)
    await form.close()
    if len(data) > limit:
        raise HTTPException(413, "Photo exceeds upload limit")
    if not data:
        raise HTTPException(400, "Empty file")
    age = form.get("age_group", "adult")
    return form, data, age if age in AGE_GROUPS else "adult"


def _opts(form=None):
    """Enhance options from the form; defaults from config."""
    if form is None or form.get("opts") != "1":
        return dict(auto_adjust=config.AUTO_ADJUST, fix_shadows=config.FIX_SHADOWS,
                    even_bg=config.EVEN_BG, replace_bg=config.BG_REPLACE)
    return {k: form.get(k) == "on" for k in ("auto_adjust", "fix_shadows", "even_bg", "replace_bg")}


def _selection(form=None):
    form = form or {}
    try:
        profile = photomatic.country(form.get("country_id") or None)
        printer = form.get("printer") or photomatic.DEFAULT_PRINTER
        choices = photomatic.print_choices(profile, printer)
        layout_id = form.get("print_template_id") or photomatic.default_print(profile, printer)["id"]
        layout = photomatic.PRINTS[layout_id]
        if layout_id not in {p["id"] for p in choices}:
            raise ValueError("Layout does not match country/printer")
        return profile, layout
    except (KeyError, ValueError):
        raise HTTPException(400, "Choose a valid country and matching print layout")


def _crop_options(form=None):
    form = form or {}
    try:
        zoom, x, y = float(form.get("zoom", 1)), float(form.get("x", 0)), float(form.get("y", 0))
        rotation = int(form.get("rotation", 0))
        if not (0.5 <= zoom <= 2 and -30 <= x <= 30 and -30 <= y <= 30 and rotation in (0, 90, 180, 270)):
            raise ValueError()
        return dict(zoom=zoom, x=x, y=y, rotation=rotation)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid crop adjustment")


async def _process_and_store(data, age, source, opts=None, profile=None, layout=None, **contact):
    profile = profile or photomatic.country()
    layout = layout or photomatic.default_print(profile)
    options = dict(opts or _opts())
    options.setdefault("crop", _crop_options())
    result = await run_in_threadpool(lambda: processing.process(data, age, country_id=profile["id"], **options))
    pid = db.new_id()
    if result.jpeg:
        _photo_path(pid).write_bytes(result.jpeg)
        _photo_path(pid, True).write_bytes(result.preview_jpeg)
        if result.before_jpeg:
            (config.PHOTO_DIR / f"{pid}_before.jpg").write_bytes(result.before_jpeg)
    # A pending shop photo can be recropped; the source is removed on issue/expiry.
    if source == "shop":
        (config.PHOTO_DIR / f"{pid}_source").write_bytes(data)
    db.create(pid, source, age, result, country_id=profile["id"], print_template_id=layout["id"], options=options, **contact)
    return pid, result


def _send_code_email(row, code):
    if not (config.SMTP_HOST and row["email"]):
        return False
    msg = EmailMessage()
    msg["Subject"] = "Your passport photo code"
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = row["email"]
    msg.set_content(
        f"Hi {row['name'] or ''},\n\n"
        f"Your passport photo code is:\n\n    {config.SHORT_DOMAIN}/{code}\n\n"
        "Apply at https://www.gov.uk/apply-renew-passport and at the photo step choose the option "
        "to use a photo code.\n\n"
        f"The code is valid for {config.RETENTION_DAYS} days.\n\n"
        f"{config.SHOP_NAME}\n{config.SHOP_CONTACT}\n"
    )
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        log.error("Email failed: %s", e)
        return False


# ---------------------------------------------------------- short domain
async def code_fetch(request):
    """HMPO retrieves the photo here. Only HMPO-signed requests get the JPEG."""
    code = request.path_params["code"]
    ip = _client_ip(request)
    if not CODE_RE.match(code):
        return Response(status_code=404)
    row = db.by_code(code)
    if not row:
        db.log_fetch(code, False, "unknown or expired", ip)
        return Response(status_code=404)
    ok, reason = hmpo_auth.verify(request.headers.get("authorization"), code)
    if not ok:
        db.log_fetch(code, False, reason, ip)
        log.info("Rejected fetch %s from %s: %s", code, ip, reason)
        return Response(status_code=404)
    path = _photo_path(row["id"])
    if not path.exists():
        db.log_fetch(code, False, "file missing", ip)
        return Response(status_code=404)
    db.mark_fetched(code)
    db.log_fetch(code, True, "ok", ip)
    return Response(
        path.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def short_root(request):
    return RedirectResponse(config.PUBLIC_BASE_URL)


short_app = Router(
    routes=[
        Route("/", short_root),
        Route("/{code}", code_fetch, methods=["GET", "HEAD"]),
    ]
)


# ------------------------------------------------------------- customers
async def home(request):
    return templates.TemplateResponse(request, "upload.html", {"ages": AGE_GROUPS})


async def upload(request):
    if _rate_limited(_client_ip(request)):
        raise HTTPException(429, "Too many uploads. Try again later.")
    form, data, age = await _read_upload(request)
    if form.get("consent") != "on":
        raise HTTPException(400, "Consent required")
    pid, _ = await _process_and_store(data, age, "online")
    return RedirectResponse(f"/r/{pid}", status_code=303)


async def result_page(request):
    pid = request.path_params["pid"]
    row = db.get(pid) if ID_RE.match(pid) else None
    if not row:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "result.html", {"row": row, "checks": json.loads(row["checks"])})


async def result_submit(request):
    pid = request.path_params["pid"]
    row = db.get(pid) if ID_RE.match(pid) else None
    if not row or not row["ok"]:
        raise HTTPException(404)
    form = await request.form()
    name = (form.get("name") or "").strip()[:100]
    email = (form.get("email") or "").strip()[:200]
    phone = (form.get("phone") or "").strip()[:40]
    if not name or not (email or phone):
        raise HTTPException(400, "Name and email or phone required")
    db.update_contact(pid, name, email, phone)
    return RedirectResponse(f"/r/{pid}?sent=1", status_code=303)


async def preview(request):
    path = _photo_path(request.path_params["pid"], preview=True)
    if not path.exists():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def privacy(request):
    return templates.TemplateResponse(request, "privacy.html", {})


# ----------------------------------------------------------------- admin
async def admin_home(request):
    _require_admin(request)
    return templates.TemplateResponse(request, "admin_list.html", {"rows": db.recent(200), "ages": AGE_GROUPS})


async def admin_new(request):
    _require_admin(request)
    if request.method == "GET":
        profile = photomatic.country()
        return templates.TemplateResponse(request, "station.html", {
            "ages": AGE_GROUPS, "row": None, "profile": profile, "layout": photomatic.default_print(profile),
            "choices": photomatic.print_choices(profile), "checks": [], "groups": [], "options": _opts(),
            "crop": _crop_options(), "has_photo": False, "editable": True,
        })
    form, data, age = await _read_upload(request)
    profile, layout = _selection(form)
    pid, _ = await _process_and_store(
        data, age, "shop", dict(_opts(form), crop=_crop_options(form)), profile, layout,
        name=(form.get("name") or "").strip() or None,
        email=(form.get("email") or "").strip() or None,
        phone=(form.get("phone") or "").strip() or None,
    )
    return RedirectResponse(f"/admin/p/{pid}", status_code=303)


async def admin_photo(request):
    _require_admin(request)
    row = db.get(request.path_params["pid"])
    if not row:
        raise HTTPException(404)
    profile = photomatic.country(row["country_id"])
    layout = photomatic.PRINTS.get(row["print_template_id"]) or photomatic.default_print(profile)
    checks = json.loads(row["checks"])
    options = json.loads(row["options"])
    return templates.TemplateResponse(request, "station.html", {
        "row": row, "checks": checks, "groups": photomatic.summary(checks), "ages": AGE_GROUPS,
        "profile": profile, "layout": layout, "choices": photomatic.print_choices(profile, layout["printer"]),
        "options": options, "crop": options.get("crop", _crop_options()),
        "has_photo": _photo_path(row["id"]).exists(),
        "editable": row["status"] == "pending" and (config.PHOTO_DIR / f"{row['id']}_source").exists(),
        "emailed": request.query_params.get("emailed"),
    })


async def admin_reprocess(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    row = db.get(pid)
    if not row or row["status"] != "pending":
        raise HTTPException(409, "Only pending photos can be recropped")
    source = config.PHOTO_DIR / f"{pid}_source"
    if not source.exists():
        raise HTTPException(409, "Upload a new photo to change this crop")
    form = await request.form()
    profile, layout = _selection(form)
    options = dict(_opts(form), crop=_crop_options(form))
    original = source.read_bytes()
    result = await run_in_threadpool(lambda: processing.process(original, row["age_group"], country_id=profile["id"], **options))
    current = db.get(pid)
    if not current or current["status"] != "pending":
        raise HTTPException(409, "This photo has already been issued or rejected")
    # Clear any previous usable crop when the new crop fails framing.
    for suffix in (".jpg", "_prev.jpg", "_before.jpg"):
        (config.PHOTO_DIR / f"{pid}{suffix}").unlink(missing_ok=True)
    if result.jpeg:
        _photo_path(pid).write_bytes(result.jpeg)
        _photo_path(pid, True).write_bytes(result.preview_jpeg)
        (config.PHOTO_DIR / f"{pid}_before.jpg").write_bytes(result.before_jpeg)
    db.update_processing(pid, profile["id"], layout["id"], options, result)
    return RedirectResponse(f"/admin/p/{pid}", status_code=303)


async def admin_issue(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    form = await request.form()
    row = db.get(pid)
    if not row or not _photo_path(pid).exists():
        raise HTTPException(404)
    if row["status"] == "rejected" or row["expires"] <= time.time():
        raise HTTPException(409, "Photo is rejected or expired")
    profile = photomatic.country(row["country_id"])
    if profile["code_service"] == "ie":
        raise HTTPException(503, "Irish photo codes need the Irish Passport Online provider connection. Print, save and email are available.")
    if profile["code_service"] != "uk":
        raise HTTPException(400, "Online photo codes are only for UK and Irish passports. Other templates can be printed, saved or emailed.")
    if not row["ok"] and form.get("override") != "on":
        raise HTTPException(400, "Photo failed checks. Tick override to issue anyway.")
    code = db.issue(pid)
    (config.PHOTO_DIR / f"{pid}_source").unlink(missing_ok=True)
    emailed = await run_in_threadpool(_send_code_email, db.get(pid), code)
    return RedirectResponse(f"/admin/p/{pid}?emailed={int(emailed)}", status_code=303)


async def admin_reject(request):
    _require_admin(request)
    db.reject(request.path_params["pid"])
    db.purge_expired()
    return RedirectResponse("/admin", status_code=303)


async def admin_full(request):
    _require_admin(request)
    path = _photo_path(request.path_params["pid"])
    if not path.exists():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def admin_before(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    if not ID_RE.match(pid):
        raise HTTPException(404)
    path = config.PHOTO_DIR / f"{pid}_before.jpg"
    if not path.exists():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def admin_sheet(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    row = db.get(pid)
    path = _photo_path(pid)
    if not row or not path.exists():
        raise HTTPException(404)
    code_text = f"{config.SHORT_DOMAIN}/{row['code']}" if row["code"] else None
    layout = photomatic.PRINTS.get(row["print_template_id"]) or photomatic.default_print(photomatic.country(row["country_id"]))
    requested = request.query_params.get("template")
    if requested:
        candidates = photomatic.print_choices(photomatic.country(row["country_id"]), request.query_params.get("printer") or layout["printer"])
        if requested not in {p["id"] for p in candidates}:
            raise HTTPException(400, "Print layout does not match the country")
        layout = photomatic.PRINTS[requested]
    if request.query_params.get("page") == "1":
        return templates.TemplateResponse(request, "print.html", {"row": row, "layout": layout})
    sheet = await run_in_threadpool(processing.print_sheet, path.read_bytes(), code_text, layout["id"])
    return Response(
        sheet, media_type="image/jpeg",
        headers={"Content-Disposition": f'inline; filename="passport-{pid[:6]}-6x4.jpg"'},
    )


async def admin_save(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    row = db.get(pid)
    if not row or not _photo_path(pid).exists():
        raise HTTPException(404)
    photo = await run_in_threadpool(processing.save_photo, _photo_path(pid).read_bytes(), row["country_id"])
    return Response(photo, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{row["country_id"]}-{pid[:6]}.jpg"'})


def _email_photo(row):
    if not config.SMTP_HOST or not row["email"]:
        return False
    profile = photomatic.country(row["country_id"])
    msg = EmailMessage()
    msg["Subject"] = f"Your {profile['name']} photo"
    msg["From"], msg["To"] = config.SMTP_FROM or config.SMTP_USER, row["email"]
    code = f"\nPhoto code: {config.SHORT_DOMAIN}/{row['code']}\n" if row["code"] else ""
    msg.set_content(f"Your {profile['name']} photo is attached.{code}\n{config.SHOP_NAME}\n{config.SHOP_CONTACT}")
    photo = processing.save_photo(_photo_path(row["id"]).read_bytes(), row["country_id"], email=True)
    msg.add_attachment(photo, maintype="image", subtype="jpeg", filename=f"{profile['id']}.jpg")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
            server.starttls()
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        log.exception("Photo email failed")
        return False


async def admin_email(request):
    _require_admin(request)
    row = db.get(request.path_params["pid"])
    if not row or not _photo_path(row["id"]).exists():
        raise HTTPException(404)
    if not config.SMTP_HOST or not row["email"]:
        raise HTTPException(400, "Set up SMTP and add a customer email address before sending")
    sent = await run_in_threadpool(_email_photo, row)
    return RedirectResponse(f"/admin/p/{row['id']}?emailed={int(sent)}", status_code=303)


async def admin_slip(request):
    _require_admin(request)
    row = db.get(request.path_params["pid"])
    if not row or not row["code"]:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "slip.html", {"row": row})


async def healthz(request):
    return Response("ok")


# ------------------------------------------------------------------- app
async def _purge_loop():
    while True:
        try:
            n = await run_in_threadpool(db.purge_expired)
            if n:
                log.info("Purged %d expired photos", n)
        except Exception as e:
            log.error("Purge failed: %s", e)
        await asyncio.sleep(3600)


@contextlib.asynccontextmanager
async def lifespan(app):
    db.init()
    try:
        await run_in_threadpool(hmpo_auth.get_key)
        log.info("HMPO public key loaded")
    except Exception as e:
        log.warning("HMPO key not loaded yet: %s", e)
    task = asyncio.create_task(_purge_loop())
    yield
    task.cancel()


async def to_admin(request):
    return RedirectResponse("/admin")


public_routes = [
    Route("/", home),
    Route("/upload", upload, methods=["POST"]),
    Route("/r/{pid}", result_page),
    Route("/r/{pid}/submit", result_submit, methods=["POST"]),
    Route("/r/{pid}/preview.jpg", preview),
] if config.PUBLIC_UPLOADS else [Route("/", to_admin)]

main_routes = public_routes + [
    Route("/privacy", privacy),
    Route("/healthz", healthz),
    Route("/admin", admin_new),
    Route("/admin/history", admin_home),
    Route("/admin/new", admin_new, methods=["GET", "POST"]),
    Route("/admin/p/{pid}", admin_photo),
    Route("/admin/p/{pid}/issue", admin_issue, methods=["POST"]),
    Route("/admin/p/{pid}/reprocess", admin_reprocess, methods=["POST"]),
    Route("/admin/p/{pid}/reject", admin_reject, methods=["POST"]),
    Route("/admin/p/{pid}/full.jpg", admin_full),
    Route("/admin/p/{pid}/before.jpg", admin_before),
    Route("/admin/p/{pid}/sheet.jpg", admin_sheet),
    Route("/admin/p/{pid}/save.jpg", admin_save),
    Route("/admin/p/{pid}/email", admin_email, methods=["POST"]),
    Route("/admin/p/{pid}/slip", admin_slip),
    Mount("/static", app=StaticFiles(directory=config.BASE_DIR / "static"), name="static"),
]

app = Starlette(
    routes=[Host(config.SHORT_DOMAIN, app=short_app), Mount("", routes=main_routes)],
    lifespan=lifespan,
)
