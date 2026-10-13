import asyncio
import base64
import contextlib
import hashlib
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

from . import config, db, hmpo_auth, processing, photomatic, ai_prepare, measurements, hotspots, local_adjustments, background, background_models, enhancement

log = logging.getLogger("tuttoid")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))
templates.env.globals.update(cfg=config, short_url=hmpo_auth.short_url, catalog=photomatic.CATALOG,
                             profiles=photomatic.COUNTRIES, printers=photomatic.PRINTERS,
                             adjustment_controls=local_adjustments.CONTROLS, background_choices=background.choices,
                             enhancer_controls=enhancement.CONTROLS, enhancer_presets=enhancement.PRESETS,
                             enhancer_available=enhancement.choices)
templates.env.filters["dt"] = lambda t: time.strftime("%d %b %Y %H:%M", time.localtime(t)) if t else ""
templates.env.filters["fromjson"] = json.loads

CODE_RE = re.compile(r"^[A-Za-z0-9]{6,8}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,40}$")
AGE_GROUPS = {"adult": "Adult / 6+", "child": "Child 1–5", "baby": "Baby under 1"}
EXCEPTION_CATEGORIES = {"child": "Child / baby", "disability": "Disability", "health": "Health / medical", "other": "Other documented allowance"}
# Named document allowances remain available for existing clients. Trained staff
# may separately acknowledge any quality failure with staff_override; that
# responsibility decision is recorded without converting failed checks to passes.
EXCEPTION_KEYS = {"eyes", "expression", "tilt", "facing", "headsize", "eyeposition", "facewidth", "glare", "glasses"}


# ---------------------------------------------------------------- helpers
def _photo_path(pid, preview=False):
    if not ID_RE.match(pid):
        raise HTTPException(404)
    return config.PHOTO_DIR / (f"{pid}_prev.jpg" if preview else f"{pid}.jpg")


@contextlib.contextmanager
def _edit_job(pid, pending_only=True):
    if not ID_RE.fullmatch(pid):
        raise HTTPException(404)
    try:
        token = db.claim_edit(pid, pending_only=pending_only)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    try:
        yield token
    finally:
        db.release_edit(pid, token)


def _clear_candidate(pid):
    for suffix in ("_ai_source", "_ai.jpg", "_ai_prev.jpg", "_ai_before.jpg"):
        (config.PHOTO_DIR / f"{pid}{suffix}").unlink(missing_ok=True)


def _store_result(pid, result):
    for suffix in (".jpg", "_prev.jpg", "_before.jpg", "_clean_before.png", "_clean_after.png", "_clean_mask.png"):
        (config.PHOTO_DIR / f"{pid}{suffix}").unlink(missing_ok=True)
    if result.jpeg:
        _photo_path(pid).write_bytes(result.jpeg)
        _photo_path(pid, True).write_bytes(result.preview_jpeg)
        if result.before_jpeg:
            (config.PHOTO_DIR / f"{pid}_before.jpg").write_bytes(result.before_jpeg)
        for name in ('before','after','mask'):
            if name in result.cleaner_assets:
                (config.PHOTO_DIR / f"{pid}_clean_{name}.png").write_bytes(result.cleaner_assets[name])


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
        options = dict(auto_adjust=config.AUTO_ADJUST, fix_shadows=config.FIX_SHADOWS,
                       even_bg=config.EVEN_BG, replace_bg=config.BG_REPLACE)
    else:
        options = {k: form.get(k) == "on" for k in ("auto_adjust", "fix_shadows", "even_bg", "replace_bg")}
    try:
        options["adjustments"] = local_adjustments.validate({c["key"]: form.get(c["key"],0) for c in local_adjustments.CONTROLS} if form else None)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from None
    options["print_only"] = bool(form and form.get("print_only") == "on")
    try:
        options["background_engine"] = background_models.validate((form.get("background_engine") if form else None) or config.BACKGROUND_ENGINE)
        options["enhancement_options"] = enhancement.validate({key:form.get('enhancer_'+key,default)
            for key,default in enhancement.DEFAULTS.items()} if form else None)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from None
    return options


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
        angle = float(form.get("angle", 0))
        if not (0.5 <= zoom <= 2 and -30 <= x <= 30 and -30 <= y <= 30 and -15 <= angle <= 15 and rotation in (0, 90, 180, 270)):
            raise ValueError()
        return dict(zoom=zoom, x=x, y=y, rotation=rotation, angle=angle)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid crop adjustment")


async def _process_and_store(data, age, source, opts=None, profile=None, layout=None, **contact):
    profile = profile or photomatic.country()
    layout = layout or photomatic.default_print(profile)
    options = dict(opts or _opts())
    options.setdefault("crop", _crop_options())
    result = await run_in_threadpool(lambda: processing.process(data, age, country_id=profile["id"], **options))
    pid = db.new_id()
    _store_result(pid,result)
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
    path = config.PHOTO_DIR / f"{row['id']}_code.jpg"
    recorded_hash = json.loads(row["issue_review"]).get("photo_sha256")
    if not path.exists() and not recorded_hash:  # Preserve legacy codes only.
        path = _photo_path(row["id"])
    if not path.exists():
        db.log_fetch(code, False, "file missing", ip)
        return Response(status_code=404)
    photo = path.read_bytes()
    if recorded_hash and hashlib.sha256(photo).hexdigest() != recorded_hash:
        db.log_fetch(code, False, "issued photo hash mismatch", ip)
        return Response(status_code=404)
    db.mark_fetched(code)
    db.log_fetch(code, True, "ok", ip)
    return Response(
        photo,
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
            "measurement_sections": [], "ai_status": {},
        })
    form, data, age = await _read_upload(request)
    if form.get("use_ai") == "on":
        if not config.OPENAI_API_KEY:
            raise HTTPException(503, "Configure the OpenAI connection before using AI preparation")
        if form.get("ai_consent") != "on":
            raise HTTPException(400, "Confirm customer permission for OpenAI photo processing")
    profile, layout = _selection(form)
    pid, _ = await _process_and_store(
        data, age, "shop", dict(_opts(form), crop=_crop_options(form)), profile, layout,
        name=(form.get("name") or "").strip() or None,
        email=(form.get("email") or "").strip() or None,
        phone=(form.get("phone") or "").strip() or None,
    )
    if form.get("use_ai") == "on":
        await _prepare_candidate(pid, lighting=True, colour=True)
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
    ai_status = json.loads(row["ai_state"])
    stored_measurements = json.loads(row["measurements"])
    review = json.loads(row["issue_review"])
    last_validation = stored_measurements.get("code_validation", {})
    final_values = review.get("final_measurements") or last_validation.get("measurements")
    metric_checks = review.get("final_checks") or last_validation.get("checks") or checks
    return templates.TemplateResponse(request, "station.html", {
        "row": row, "checks": checks, "groups": photomatic.summary(checks), "ages": AGE_GROUPS,
        "profile": profile, "layout": layout, "choices": photomatic.print_choices(profile, layout["printer"]),
        "options": options, "crop": options.get("crop", _crop_options()),
        "has_photo": _photo_path(row["id"]).exists(),
        "editable": row["status"] == "pending" and not row["edit_token"] and (config.PHOTO_DIR / f"{row['id']}_source").exists(),
        "measurement_sections": measurements.report(final_values or stored_measurements, metric_checks, profile),
        "measurement_title": "Final code JPEG measurements" if final_values else "Photo measurements",
        "ai_measurement_sections": measurements.report(ai_status.get("measurements", {}), ai_status.get("checks", []), profile),
        "ai_status": ai_status,
        "exception_categories": EXCEPTION_CATEGORIES,
        "exception_checks": [c for c in checks if c["status"] == "fail" and c["key"] in EXCEPTION_KEYS],
        "nonwaivable_checks": [c for c in checks if c["status"] == "fail" and c["key"] not in EXCEPTION_KEYS],
        "emailed": request.query_params.get("emailed"),
    })


async def admin_reprocess(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    form = await request.form()
    profile, layout = _selection(form)
    options = dict(_opts(form), crop=_crop_options(form))
    with _edit_job(pid) as token:
        row = db.get(pid)
        previous = json.loads(row['options'])
        if (options['enhancement_options']['blemish_keep'] and
            str(form.get('cleaner_revision',row['revision']))!=str(row['revision'])):
            raise HTTPException(409,'Photo changed; refresh before using saved keep areas')
        if (row['country_id']!=profile['id'] or previous.get('crop',_crop_options())!=options['crop'] or
            bool(previous.get('print_only'))!=options['print_only']):
            options['enhancement_options']['blemish_keep'] = []
        source = config.PHOTO_DIR / f"{pid}_working_source"
        if not source.exists():
            source = config.PHOTO_DIR / f"{pid}_source"
        if not source.exists():
            raise HTTPException(409, "Upload a new photo to change this crop")
        result = await run_in_threadpool(lambda: processing.process(source.read_bytes(), row["age_group"], country_id=profile["id"], **options))
        db.assert_edit(pid, token)
        if previous.get("ai"):
            options["ai"] = previous["ai"]
        _store_result(pid, result)
        _clear_candidate(pid)
        db.update_processing(pid, profile["id"], layout["id"], options, result, token)
    return RedirectResponse(f"/admin/p/{pid}", status_code=303)


async def _prepare_candidate(pid, *, lighting, colour):
    with _edit_job(pid) as token:
        row = db.get(pid)
        options = json.loads(row["options"])
        _clear_candidate(pid)
        db.set_ai_state(pid, token, {"status": "running", "started": time.time()})
        try:
            original = (config.PHOTO_DIR / f"{pid}_source").read_bytes()
            # Measure original detail/framing for evidence; staff decide whether
            # to request preparation despite quality failures.
            local_options = dict(auto_adjust=False, fix_shadows=False, even_bg=False, replace_bg=False,
                                 background_engine=options.get("background_engine",config.BACKGROUND_ENGINE),
                                 print_only=options.get("print_only",False),
                                 crop=options.get("crop", _crop_options()))
            original_result = await run_in_threadpool(lambda: processing.process(
                original, row["age_group"], country_id=row["country_id"], **local_options))
            if any(c.status == "fail" and c.key == "file" for c in original_result.checks):
                raise ai_prepare.PreparationError("Upload a readable image before OpenAI preparation")
            full_frame = options.get("print_only",False) or not original_result.jpeg
            if full_frame:
                local_options["print_only"] = True
                prepared = await run_in_threadpool(ai_prepare.prepare, original, lighting=lighting, colour=colour, print_only=True)
            else:
                prepared = await run_in_threadpool(ai_prepare.prepare, original, lighting=lighting, colour=colour)
            result = await run_in_threadpool(lambda: processing.process(
                prepared.image, row["age_group"], country_id=row["country_id"], **local_options))
            if not result.jpeg:
                local_options["print_only"] = True
                result = await run_in_threadpool(lambda: processing.process(
                    prepared.image, row["age_group"], country_id=row["country_id"], **local_options))
            if not result.jpeg:
                raise ai_prepare.PreparationError("The AI result is not a readable photo")
            db.assert_edit(pid, token)
            (config.PHOTO_DIR / f"{pid}_ai_source").write_bytes(prepared.image)
            (config.PHOTO_DIR / f"{pid}_ai.jpg").write_bytes(result.jpeg)
            (config.PHOTO_DIR / f"{pid}_ai_prev.jpg").write_bytes(result.preview_jpeg)
            state = {
                "status": "ready", "candidate_id": secrets.token_urlsafe(16), "revision": row["revision"], "country_id": row["country_id"],
                "options": local_options, "checks": result.as_dict()["checks"], "ok": result.ok,
                "measurements": result.measurements, "model": prepared.model,
                "request_id": prepared.request_id, "prompt_version": prepared.prompt_version,
                "lighting": lighting, "colour": colour, "print_only": local_options.get("print_only",False), "permission_recorded": time.time(),
                "original_checks": original_result.as_dict()["checks"], "original_measurements": original_result.measurements,
                "original_sha256": hashlib.sha256(original).hexdigest(),
                "edited_source_sha256": hashlib.sha256(prepared.image).hexdigest(),
            }
            db.set_ai_state(pid, token, state)
            return state
        except Exception as exc:
            message = str(exc) if isinstance(exc, ai_prepare.PreparationError) else "Photo preparation failed. No edit was applied; keep the original or retry."
            state = {"status": "error", "message": message}
            try:
                db.assert_edit(pid, token)
                _clear_candidate(pid)
                db.set_ai_state(pid, token, state)
            except ValueError:
                pass  # The job expired/deleted while the remote call was running.
            return state


async def admin_ai_prepare(request):
    _require_admin(request)
    form = await request.form()
    if not config.OPENAI_API_KEY:
        raise HTTPException(503, "Configure OPENAI_API_KEY on the server")
    if form.get("ai_consent") != "on":
        raise HTTPException(400, "Confirm customer permission for OpenAI photo processing")
    state = await _prepare_candidate(request.path_params["pid"], lighting=form.get("lighting") == "on", colour=form.get("colour") == "on")
    return Response(json.dumps({"status": state["status"], "message": state.get("message", "")}),
                    status_code=200 if state["status"] == "ready" else 400, media_type="application/json")


async def admin_ai_accept(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    form = await request.form()
    if form.get("review_likeness") != "on":
        raise HTTPException(400, "Compare the original and AI photo and confirm the person's appearance")
    with _edit_job(pid) as token:
        row = db.get(pid)
        state = json.loads(row["ai_state"])
        if state.get("status") != "ready" or state.get("revision") != row["revision"]:
            raise HTTPException(409, "Prepare a new AI preview for the current photo version")
        if form.get("candidate_id") != state.get("candidate_id"):
            raise HTTPException(409, "The AI preview changed. Review the current preview before accepting it")
        source = (config.PHOTO_DIR / f"{pid}_ai_source").read_bytes()
        options = state["options"]
        # Run the checks again on the exact accepted source, rather than trusting
        # values submitted by a browser or an AI-written verdict.
        result = await run_in_threadpool(lambda: processing.process(source, row["age_group"], country_id=row["country_id"], **options))
        db.assert_edit(pid, token)
        (config.PHOTO_DIR / f"{pid}_working_source").write_bytes(source)
        options["ai"] = {k: state[k] for k in (
            "model", "request_id", "prompt_version", "lighting", "colour", "permission_recorded",
            "original_sha256", "edited_source_sha256")}
        options["ai"]["print_only"] = state.get("print_only",False)
        options["ai"]["original_checks"] = state.get("original_checks",[])
        options["ai"]["original_measurements"] = state.get("original_measurements",{})
        options["ai"].update(reviewed_at=time.time(), reviewed_by=config.ADMIN_USER)
        _store_result(pid, result)
        db.update_processing(pid, row["country_id"], row["print_template_id"], options, result, token)
        _clear_candidate(pid)
    return RedirectResponse(f"/admin/p/{pid}", status_code=303)


async def admin_ai_discard(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    with _edit_job(pid) as token:
        _clear_candidate(pid)
        db.set_ai_state(pid, token, {})
    return RedirectResponse(f"/admin/p/{pid}", status_code=303)


async def admin_restore_original(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    with _edit_job(pid) as token:
        row = db.get(pid)
        options = dict(auto_adjust=False, fix_shadows=False, even_bg=False, replace_bg=False,
                       background_engine=json.loads(row["options"]).get("background_engine",config.BACKGROUND_ENGINE),
                       print_only=json.loads(row["options"]).get("print_only",False),
                       crop=json.loads(row["options"]).get("crop", _crop_options()))
        data = (config.PHOTO_DIR / f"{pid}_source").read_bytes()
        result = await run_in_threadpool(lambda: processing.process(data, row["age_group"], country_id=row["country_id"], **options))
        db.assert_edit(pid, token)
        _store_result(pid, result)
        (config.PHOTO_DIR / f"{pid}_working_source").unlink(missing_ok=True)
        _clear_candidate(pid)
        db.update_processing(pid, row["country_id"], row["print_template_id"], options, result, token)
    return RedirectResponse(f"/admin/p/{pid}", status_code=303)


async def admin_original(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    if not ID_RE.fullmatch(pid):
        raise HTTPException(404)
    source = config.PHOTO_DIR / f"{pid}_source"
    if not source.exists():
        raise HTTPException(404)
    photo = await run_in_threadpool(lambda: processing._small_jpeg(processing.load_image(source.read_bytes()), bounds=(1600, 1600), quality=95))
    return Response(photo, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def admin_hotspots(request):
    """Staff-only, read-only diagnostics on a consistent per-job image snapshot."""
    _require_admin(request)
    pid = request.path_params["pid"]
    if not ID_RE.fullmatch(pid):
        raise HTTPException(404)
    row = db.get(pid)
    if not row or row["expires"] <= time.time() or row["status"] == "rejected":
        raise HTTPException(404)
    if row["edit_token"]:
        raise HTTPException(409, "Wait for the current photo operation to finish")
    state = json.loads(row["ai_state"])
    paths = [("Camera original", config.PHOTO_DIR / f"{pid}_source")]
    if row["status"] == "issued":
        paths.append(("Final code JPEG", config.PHOTO_DIR / f"{pid}_code.jpg"))
    else:
        paths.append(("Current prepared photo", _photo_path(pid)))
    if state.get("status") == "ready" and state.get("revision") == row["revision"]:
        paths.append(("AI candidate · not accepted", config.PHOTO_DIR / f"{pid}_ai_source"))
    snapshots = []
    try:
        for label, path in paths:
            if path.exists():
                snapshots.append((label, path.read_bytes()))
    except OSError:
        raise HTTPException(409, "The photo changed. Refresh and inspect again") from None
    if not snapshots:
        raise HTTPException(404, "No photograph is available for inspection")
    reports = []
    for label, data in snapshots:
        report = await run_in_threadpool(hotspots.inspect_photo, data)
        reports.append(dict(report, label=label))
    current = db.get(pid)
    if (not current or current["expires"] <= time.time() or current["status"] != row["status"] or
            current["revision"] != row["revision"] or current["edit_token"] or current["ai_state"] != row["ai_state"]):
        raise HTTPException(409, "The photo changed. Refresh and inspect again")
    return Response(json.dumps({"revision": row["revision"], "stages": reports,
                               "approval": "not_assessed", "calibrated": False}),
                    media_type="application/json", headers={"Cache-Control": "no-store"})


async def admin_ai_preview(request):
    _require_admin(request)
    pid = request.path_params["pid"]
    if not ID_RE.fullmatch(pid):
        raise HTTPException(404)
    row = db.get(pid)
    if not row or json.loads(row["ai_state"]).get("status") != "ready":
        raise HTTPException(404)
    path = config.PHOTO_DIR / f"{pid}_ai.jpg"
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


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
        raise HTTPException(503, "Irish codes are handled by your external provider. Save this photo and submit it through that provider.")
    if profile["code_service"] != "uk":
        raise HTTPException(400, "Online photo codes are only for UK and Irish passports. Other templates can be printed, saved or emailed.")
    if row["code"]:
        return RedirectResponse(f"/admin/p/{pid}", status_code=303)
    with _edit_job(pid) as token:
        row = db.get(pid)
        state = json.loads(row["ai_state"])
        options = json.loads(row["options"])
        staff_override = form.get("staff_override") == "on"
        needs_override = options.get("print_only") or options.get("ai",{}).get("print_only")
        if needs_override and not staff_override:
            raise HTTPException(400, "Confirm staff responsibility to issue from a full-frame / print job")
        if str(form.get("review_revision")) != str(row["revision"]):
            raise HTTPException(409, "The photo changed since this review screen opened. Refresh and review the current photo")
        if state.get("status") in ("ready", "running"):
            raise HTTPException(409, "Review and accept or discard the AI preview before issuing a code")
        failed = {c["key"] for c in json.loads(row["checks"]) if c["status"] == "fail"}
        exception = None
        if failed and not staff_override:
            category = form.get("exception_category")
            reason = (form.get("exception_reason") or "").strip()[:1000]
            covered = set(form.getlist("exception_checks"))
            if failed - EXCEPTION_KEYS:
                raise HTTPException(400, "Technical or image quality checks failed. Correct the photo or retake it; these failures cannot be waived.")
            if category not in EXCEPTION_CATEGORIES or len(reason) < 15 or covered != failed:
                raise HTTPException(400, "Record the exception category, a specific reason and every failed check covered by the document allowance")
            if category == "child" and row["age_group"] == "adult":
                raise HTTPException(400, "A child exception requires a child or baby job")
            if form.get("exception_confirmed") != "on":
                raise HTTPException(400, "Confirm that the selected document allows this exception")
            exception = {"category": category, "reason": reason, "checks": sorted(covered)}
        required = ("review_likeness", "review_visibility", "customer_permission")
        if any(form.get(k) != "on" for k in required):
            raise HTTPException(400, "Complete the staff photo review and customer permission before issuing a code")
        try:
            if staff_override:
                final = await run_in_threadpool(processing.code_photo, _photo_path(pid).read_bytes(), row["country_id"], True)
            else:
                final = await run_in_threadpool(processing.code_photo, _photo_path(pid).read_bytes(), row["country_id"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        final_result = await run_in_threadpool(processing.check_code_photo, final, row["country_id"], row["age_group"])
        final_failed = {c.key for c in final_result.checks if c.status == "fail"}
        allowed = set(exception["checks"]) if exception else set()
        if final_failed - allowed and not staff_override:
            # Surface failures discovered on the encoded/resized deliverable so
            # staff can correct them or record a genuinely applicable allowance.
            combined = {c["key"]: c for c in json.loads(row["checks"])}
            for check in final_result.as_dict()["checks"]:
                if check["status"] == "fail":
                    combined[check["key"]] = dict(check, detail="Final code JPEG: " + check["detail"])
            with db.conn() as connection:
                recorded = json.loads(row["measurements"])
                recorded["code_validation"] = final_result.as_dict()
                connection.execute("UPDATE photos SET checks=?,ok=0,measurements=?,revision=revision+1 WHERE id=? AND edit_token=?",
                                   (json.dumps(list(combined.values())), json.dumps(recorded), pid, token))
            raise HTTPException(400, "The final code JPEG failed checks: " + ", ".join(sorted(final_failed - allowed)) + ". Refresh the review screen and correct the photo or confirm staff responsibility to proceed.")
        override_record = None
        if staff_override:
            override_record = {"confirmed_by":config.ADMIN_USER,"confirmed_at":time.time(),
                               "reason":str(form.get("override_reason") or "").strip()[:1000],
                               "working_failed_checks":sorted(failed),"final_failed_checks":sorted(final_failed),
                               "full_frame_job":bool(needs_override),"quality_assessment":"staff_responsibility"}
            combined = {c["key"]:c for c in json.loads(row["checks"])}
            for check in final_result.as_dict()["checks"]:
                if check["status"] == "fail":
                    combined[check["key"]] = dict(check,detail="Final code JPEG: "+check["detail"])
            with db.conn() as connection:
                connection.execute("UPDATE photos SET checks=?,ok=? WHERE id=? AND edit_token=?",
                                   (json.dumps(list(combined.values())),int(not needs_override and not any(c["status"]=="fail" for c in combined.values())),pid,token))
        db.assert_edit(pid, token)
        (config.PHOTO_DIR / f"{pid}_code.jpg").write_bytes(final)
        options = json.loads(row["options"])
        age_allowances = [c["key"] for c in json.loads(row["checks"]) if c.get("detail", "").startswith("Not required")]
        review = dict(staff=config.ADMIN_USER, reviewed_at=time.time(), revision=row["revision"],
                      country_id=row["country_id"], photo_sha256=hashlib.sha256(final).hexdigest(),
                      confirmations=list(required), ai=options.get("ai"), exception=exception, staff_override=override_record,
                      processing_options=options,
                      final_checks=final_result.as_dict()["checks"], final_measurements=final_result.measurements,
                      age_group=row["age_group"], age_allowances=age_allowances,
                      decision="staff_override" if staff_override else "approved_with_exception" if exception else "approved_with_age_allowance" if age_allowances else "checks_passed_and_reviewed")
        code = db.issue(pid, review, token)
        # Retain enhancement originals as review evidence until normal expiry.
        if not options.get("ai") and not staff_override and not enhancement.active(options.get('enhancement_options')):
            (config.PHOTO_DIR / f"{pid}_source").unlink(missing_ok=True)
        (config.PHOTO_DIR / f"{pid}_working_source").unlink(missing_ok=True)
        _clear_candidate(pid)
    emailed = await run_in_threadpool(_send_code_email, db.get(pid), code)
    return RedirectResponse(f"/admin/p/{pid}?emailed={int(emailed)}", status_code=303)


async def admin_reject(request):
    _require_admin(request)
    with _edit_job(request.path_params["pid"], pending_only=False):
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


async def admin_cleaner_asset(request):
    _require_admin(request)
    pid,name=request.path_params['pid'],request.path_params['name']
    row=db.get(pid) if ID_RE.fullmatch(pid) else None
    if name not in ('before','after','mask') or not row or row['status']=='rejected' or row['expires']<=time.time():
        raise HTTPException(404)
    if row['edit_token']:raise HTTPException(409,'Photo is being processed')
    revision=request.query_params.get('revision')
    if revision is not None and revision!=str(row['revision']):raise HTTPException(409,'Repair preview changed; refresh the photo')
    path=config.PHOTO_DIR/f'{pid}_clean_{name}.png'
    if not path.is_file():raise HTTPException(404)
    return Response(path.read_bytes(),media_type='image/png',headers={'Cache-Control':'no-store'})


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
    Route("/admin/p/{pid}/ai/prepare", admin_ai_prepare, methods=["POST"]),
    Route("/admin/p/{pid}/ai/accept", admin_ai_accept, methods=["POST"]),
    Route("/admin/p/{pid}/ai/discard", admin_ai_discard, methods=["POST"]),
    Route("/admin/p/{pid}/restore-original", admin_restore_original, methods=["POST"]),
    Route("/admin/p/{pid}/original.jpg", admin_original),
    Route("/admin/p/{pid}/hotspots", admin_hotspots),
    Route("/admin/p/{pid}/ai-preview.jpg", admin_ai_preview),
    Route("/admin/p/{pid}/reject", admin_reject, methods=["POST"]),
    Route("/admin/p/{pid}/full.jpg", admin_full),
    Route("/admin/p/{pid}/before.jpg", admin_before),
    Route("/admin/p/{pid}/cleaner/{name}.png", admin_cleaner_asset),
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
