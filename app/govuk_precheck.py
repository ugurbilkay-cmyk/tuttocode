"""Optional public-browser photo precheck for controlled development trials."""
import asyncio
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import time

from . import config, db


def validate_dob(value):
    try:
        dob = date.fromisoformat(value)
        if dob.isoformat() != value or dob > date.today():
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Enter a valid date of birth that is not in the future") from None
    return dob


def start(row, master, export, dob, synthetic):
    """Freeze the exact Save JPEG while the caller holds the photo edit lock."""
    validate_dob(dob)
    if not 50_000 <= len(export) <= 10_000_000 or export[:2] != b'\xff\xd8':
        raise ValueError("GOV.UK requires a JPEG between 50 KB and 10 MB")
    now = time.time()
    run_id = secrets.token_urlsafe(12)
    folder = config.GOVUK_DIR / row['id'] / run_id
    digest = hashlib.sha256(export).hexdigest()
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE govuk_checks SET status='unavailable',finished=?,result=? WHERE status='running' AND created<?",
                  (now, json.dumps({'error': 'The previous checker stopped before returning a verified result.'}),
                   now - config.GOVUK_TIMEOUT_SECONDS - 30))
        if c.execute("SELECT 1 FROM govuk_checks WHERE status='running'").fetchone():
            raise ValueError("Another GOV.UK photo check is running. Wait for its result, then try this photo.")
        try:
            folder.mkdir(parents=True, mode=0o700)
            (folder / 'input.jpg').write_bytes(export)
            (folder / 'input.json').write_text(json.dumps({
                'photo': str((folder / 'input.jpg').resolve()), 'dob': dob,
                'syntheticDob': synthetic, 'authorisedUpload': True,
            }))
            c.execute("INSERT INTO govuk_checks (id,photo_id,revision,country_id,master_sha256,photo_sha256,status,created,staff,synthetic_dob) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (run_id, row['id'], row['revision'], row['country_id'], hashlib.sha256(master).hexdigest(),
                       digest, 'running', now, config.ADMIN_USER, int(synthetic)))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
    return run_id


def get_run(pid, run_id):
    with db.conn() as c:
        return c.execute('SELECT * FROM govuk_checks WHERE photo_id=? AND id=?', (pid, run_id)).fetchone()


def history(row, master=None):
    with db.conn() as c:
        c.execute("UPDATE govuk_checks SET status='unavailable',finished=?,result=? WHERE status='running' AND created<?",
                  (time.time(),json.dumps({'error':'The checker stopped before returning a verified result.'}),
                   time.time()-config.GOVUK_TIMEOUT_SECONDS-30))
        runs = c.execute('SELECT * FROM govuk_checks WHERE photo_id=? ORDER BY created DESC LIMIT 10', (row['id'],)).fetchall()
    master_digest = hashlib.sha256(master).hexdigest() if master else None
    records = []
    for run in runs:
        result = json.loads(run['result'])
        current = (row['revision'] == run['revision'] and row['country_id'] == run['country_id'] and
                   master_digest == run['master_sha256'])
        records.append({
            'id': run['id'], 'status': run['status'], 'created': run['created'], 'current': current,
            'revision': run['revision'], 'photo_sha256': run['photo_sha256'], 'synthetic_dob': bool(run['synthetic_dob']),
            'elapsed_seconds': result.get('elapsedSeconds'), 'text': result.get('resultText', ''),
            'error': result.get('error'), 'screenshot': bool(result.get('screenshot')),
            'access_diagnostics': result.get('accessDiagnostics') or result.get('access_diagnosis'),
            'error_code': result.get('errorCode'),
            'comparison_eligible': bool(result.get('referenceComparisonEligible')) and current,
        })
    return records


async def execute(pid, run_id):
    folder = (config.GOVUK_DIR / pid / run_id).resolve()
    process = None
    result = {'status': 'unavailable', 'error': 'The checker did not return a verified result.'}
    try:
        # Only browser-runtime settings enter the child; never API keys or staff credentials.
        environment = {key: os.environ[key] for key in
                       ('PATH', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'PLAYWRIGHT_BROWSERS_PATH') if key in os.environ}
        process = await asyncio.create_subprocess_exec(
            config.GOVUK_NODE, str(config.BASE_DIR / 'scripts/govuk_precheck.mjs'),
            '--input-manifest', str(folder / 'input.json'), '--output', str(folder), '--headless',
            cwd=str(config.BASE_DIR), env=environment,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, _ = await asyncio.wait_for(process.communicate(), timeout=config.GOVUK_TIMEOUT_SECONDS)
        # The trusted runner returns only status, timing and its local evidence location.
        summary = json.loads(output.decode().splitlines()[-1])
        evidence = Path(summary['evidence']).resolve()
        if not evidence.is_relative_to(folder):
            raise ValueError('Invalid evidence folder')
        result = json.loads((evidence / 'result.json').read_text())
        recorded = get_run(pid, run_id)
        if not recorded or result.get('photoSha256') != recorded['photo_sha256']:
            raise ValueError('The returned result does not match the selected export')
        if result.get('status') not in ('good', 'needs_review', 'unavailable'):
            raise ValueError('Unrecognised checker result')
        if result.get('status') != 'unavailable' and not result.get('uploaded'):
            raise ValueError('The selected JPEG was not uploaded')
        shot = evidence / 'result.png'
        if shot.is_file():
            shutil.copyfile(shot, folder / 'result.png')
            result['screenshot'] = True
    except asyncio.CancelledError:
        result = {'status': 'unavailable', 'error': 'The test server stopped before a verified result was returned.'}
        raise
    except asyncio.TimeoutError:
        result = {'status': 'unavailable', 'error': 'The GOV.UK check timed out. No verified result was recorded.'}
    except Exception:
        result = {'status': 'unavailable', 'error': 'The browser checker is unavailable. Check its local runtime setup and try again manually.'}
    finally:
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        row = db.get(pid)
        if row and row['status'] != 'rejected' and row['expires'] > time.time():
            with db.conn() as c:
                c.execute('UPDATE govuk_checks SET status=?,finished=?,result=? WHERE photo_id=? AND id=?',
                          (result['status'], time.time(), json.dumps(result), pid, run_id))
        else:
            shutil.rmtree(folder, ignore_errors=True)
