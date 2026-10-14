"""Local frozen-JPEG queue with staff-observed external checks; no remote calls."""
import hashlib
import io
import json
import secrets
import shutil
import tempfile
import time
import zipfile

from PIL import Image

from . import config, db, photomatic

GOV_STATES = {'not_checked':'Not checked', 'good':'Good', 'flagged':'Flagged / other rating', 'unavailable':'Unavailable'}
COLOURS = {'not_tested':'Not tested', 'dark_green':'Dark green', 'light_green':'Light green', 'amber':'Amber', 'red':'Red', 'grey':'Grey'}
GROUPS = [('image_quality','Image quality'),('geometry','Face size and position'),('background','Background')]


def engine_reference():
    digest = hashlib.sha256()
    for name in ('processing.py','photomatic.py','enhancement.py','background.py','hotspots.py','local_adjustments.py','ofiq.py','skin_guided.py','portrait_tone.py','adaptive_quality.py','comparison.py'):
        digest.update(name.encode())
        digest.update((config.BASE_DIR/'app'/name).read_bytes())
    digest.update((config.BASE_DIR/'app/photomatic_catalog.json').read_bytes())
    digest.update((config.BASE_DIR/'scripts/ofiq_worker.py').read_bytes())
    return digest.hexdigest()


def create(title,keep_snapshots=False):
    queue_id = secrets.token_urlsafe(12)
    now = time.time()
    folder = config.TEST_QUEUE_DIR/queue_id
    folder.mkdir(parents=True,mode=0o700)
    try:
        with db.conn() as c:
            c.execute('INSERT INTO test_queues (id,title,created,expires,staff,keep_snapshots) VALUES (?,?,?,?,?,?)',
                      (queue_id,title.strip()[:100] or 'Photo validation',now,now+config.RETENTION_DAYS*86400,config.ADMIN_USER,int(keep_snapshots)))
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise
    return queue_id


def get(queue_id):
    with db.conn() as c:
        return c.execute('SELECT * FROM test_queues WHERE id=? AND expires>?',(queue_id,time.time())).fetchone()


def recent():
    with db.conn() as c:
        return c.execute('SELECT q.*,COUNT(t.id) AS count FROM test_queues q LEFT JOIN test_cases t ON t.queue_id=q.id WHERE q.expires>? GROUP BY q.id ORDER BY q.created DESC',(time.time(),)).fetchall()


def cases(queue_id):
    with db.conn() as c:
        return c.execute('SELECT * FROM test_cases WHERE queue_id=? ORDER BY position',(queue_id,)).fetchall()


def case(queue_id,case_id):
    with db.conn() as c:
        return c.execute('SELECT * FROM test_cases WHERE queue_id=? AND id=?',(queue_id,case_id)).fetchone()


def add(queue_id,row,master,export,source_digest):
    queue = get(queue_id)
    if not queue: raise ValueError('Test queue is missing or expired')
    digest = hashlib.sha256(export).hexdigest()
    with Image.open(io.BytesIO(export)) as image:
        size = list(image.size)
    snapshot = {
        'sha256':digest,'master_sha256':hashlib.sha256(master).hexdigest(),'bytes':len(export),'pixels':size,
        'source_sha256':source_digest,'country_id':row['country_id'],'age_group':row['age_group'],
        'engine_reference':engine_reference(),'engine_checks':json.loads(row['checks']),
        'engine_groups':photomatic.summary(json.loads(row['checks'])),
        'engine_measurements':json.loads(row['measurements']),'options':json.loads(row['options']),
        'measurement_stage':'Existing prepared-master checks; the frozen Save JPEG is the external-test input',
        'source':'engine_preparation' if row['external_review']=='{}' else 'preserved_vendor_export',
    }
    native = snapshot['engine_measurements'].get('ofiq', {})
    matching = next((s for s in native.get('stages', [])
                     if s.get('stage') in ('save_jpeg','delivery_jpeg') and s.get('image_sha256') == digest), None)
    snapshot['final_jpeg_ofiq'] = dict(matching,
        version=native.get('version'), config_sha256=native.get('config_sha256'),
        runtime_manifest_sha256=native.get('runtime_manifest_sha256')) if matching else {
        'status':'not_assessed','image_sha256':digest,
        'message':'No native OFIQ assessment matches these exact frozen JPEG bytes.'}
    case_id = secrets.token_urlsafe(12)
    folder = config.TEST_QUEUE_DIR/queue_id/case_id
    with db.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        total = c.execute('SELECT COUNT(*) FROM test_cases WHERE queue_id=?',(queue_id,)).fetchone()[0]
        if total >= 200: raise ValueError('This queue already has 200 cases. Start another queue.')
        if c.execute('SELECT 1 FROM test_cases WHERE queue_id=? AND photo_id=? AND photo_revision=?',(queue_id,row['id'],row['revision'])).fetchone():
            return None
        try:
            folder.mkdir(parents=True,mode=0o700)
            (folder/'input.jpg').write_bytes(export)
            # Retention beyond source expiry requires the explicit study-copy option.
            expires = queue['expires'] if queue['keep_snapshots'] else min(row['expires'],queue['expires'])
            c.execute('INSERT INTO test_cases (id,queue_id,position,photo_id,photo_revision,created,expires,snapshot) VALUES (?,?,?,?,?,?,?,?)',
                (case_id,queue_id,total+1,row['id'],row['revision'],time.time(),expires,json.dumps(snapshot)))
        except Exception:
            shutil.rmtree(folder,ignore_errors=True)
            raise
    return case_id


def input_bytes(row):
    if row['expires'] <= time.time(): raise ValueError('This test JPEG expired with its source photo')
    data = (config.TEST_QUEUE_DIR/row['queue_id']/row['id']/'input.jpg').read_bytes()
    if hashlib.sha256(data).hexdigest() != json.loads(row['snapshot'])['sha256']:
        raise ValueError('The test JPEG changed; record a new case instead')
    return data


def observe(row,form,assets):
    snapshot = json.loads(row['snapshot'])
    if form.get('photo_sha256') != snapshot['sha256']: raise ValueError('The selected test photo changed')
    input_bytes(row)
    gov = form.get('gov_status','not_checked')
    if gov not in GOV_STATES: raise ValueError('Choose an actual GOV.UK result')
    colours = {key:form.get(key,'not_tested') for key,_ in GROUPS}
    if any(value not in COLOURS for value in colours.values()): raise ValueError('Choose the observed Photomatic colours')
    tested = gov != 'not_checked' or any(value != 'not_tested' for value in colours.values())
    if tested and form.get('same_file') != 'on': raise ValueError('Confirm that the observed results belong to this exact test JPEG')
    dob = form.get('dob','').strip()
    if dob:
        from .govuk_precheck import validate_dob
        validate_dob(dob)
    if gov not in ('not_checked','unavailable') and not dob: raise ValueError('Record the birth date used in the GOV.UK session')
    customer_ref = form.get('customer_ref','').strip()[:80]
    real_case = form.get('real_customer')=='on'
    if real_case and not customer_ref: raise ValueError('Use a non-identifying customer case reference')
    for key in ('assessed_width','assessed_height'):
        value = form.get(key,'').strip()
        if value and (not value.isdigit() or not 1<=int(value)<=20000): raise ValueError('Enter valid assessed pixel dimensions')
    previous = json.loads(row['observation'])
    record = {
        'source':'staff_observed','staff':config.ADMIN_USER,'recorded_at':time.time(),'sha256':snapshot['sha256'],
        'gov_status':gov,'dob':dob,'synthetic_dob':form.get('synthetic_dob')=='on',
        'gov_feedback':form.get('gov_feedback','').strip()[:2000],'same_file_confirmed':tested,
        'photomatic_colours':colours,'comparable_framing':form.get('comparable_framing')=='on',
        'assessed_pixels':[form.get('assessed_width','').strip(),form.get('assessed_height','').strip()],
        'photomatic_notes':form.get('photomatic_notes','').strip()[:2000],
        'real_customer':real_case,'customer_ref':customer_ref,
        'assets':dict(previous.get('assets',{})),
    }
    next_revision = row['observation_revision']+1
    written = []
    with db.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        fresh = c.execute('SELECT observation_revision FROM test_cases WHERE id=? AND expires>?',(row['id'],time.time())).fetchone()
        if not fresh or str(fresh[0]) != form.get('observation_revision'):
            raise ValueError('Another result was saved. Refresh before updating this case.')
        try:
            for key,data in assets.items():
                with Image.open(io.BytesIO(data)) as image:
                    extension = {'PNG':'png','JPEG':'jpg','WEBP':'webp'}[image.format]
                filename = f'{key}-{next_revision}.{extension}'
                file = config.TEST_QUEUE_DIR/row['queue_id']/row['id']/filename
                file.write_bytes(data);written.append(file)
                record['assets'][key] = {'file':filename,'sha256':hashlib.sha256(data).hexdigest()}
            c.execute('UPDATE test_cases SET observation=?,observation_revision=? WHERE id=?',(json.dumps(record),next_revision,row['id']))
            c.execute('INSERT INTO test_observations VALUES (?,?,?,?,?)',(row['id'],next_revision,time.time(),config.ADMIN_USER,json.dumps(record)))
        except Exception:
            for file in written: file.unlink(missing_ok=True)
            raise


def summary(rows):
    stats = {'total':len(rows),'gov_good':0,'photomatic_dark_green':0,'comparable_dark_green':0,'unique_customer_matches':0,'with_vendor_evidence':0,'pending':0,'expired':0,'engine_vendor_disagreements':0,'gov_vendor_disagreements':0}
    seen_sources,seen_refs = set(),set()
    for row in rows:
        obs=json.loads(row['observation']);snapshot=json.loads(row['snapshot'])
        if row['expires']<=time.time():
            stats['expired']+=1
            continue
        if not obs: stats['pending']+=1
        if obs.get('gov_status')=='good':stats['gov_good']+=1
        all_dark = bool(obs) and all(obs.get('photomatic_colours',{}).get(key)=='dark_green' for key,_ in GROUPS)
        if not all_dark:continue
        stats['photomatic_dark_green']+=1
        if any(group['status']!='pass' for group in snapshot.get('engine_groups',[])):
            stats['engine_vendor_disagreements']+=1
        if obs.get('gov_status')=='flagged':stats['gov_vendor_disagreements']+=1
        if not obs.get('comparable_framing'):continue
        stats['comparable_dark_green']+=1
        if obs.get('assets',{}).get('photomatic'):stats['with_vendor_evidence']+=1
        source=snapshot.get('source_sha256');ref=obs.get('customer_ref')
        if (obs.get('real_customer') and not obs.get('synthetic_dob') and source and ref and
            source not in seen_sources and ref not in seen_refs and obs.get('assets',{}).get('photomatic') and
            row['expires']>time.time() and snapshot.get('source')=='engine_preparation'):
            stats['unique_customer_matches']+=1;seen_sources.add(source);seen_refs.add(ref)
    return stats


def report(queue,rows):
    with db.conn() as c:
        history = c.execute('SELECT o.* FROM test_observations o JOIN test_cases t ON t.id=o.case_id WHERE t.queue_id=? ORDER BY t.position,o.revision',(queue['id'],)).fetchall()
    return {'version':'staff-test-queue-v1','queue':dict(queue),'summary':summary(rows),
            'external_checks_source':'staff_observed, not automatic government/vendor decisions',
            'observation_history':[{'case_id':r['case_id'],'revision':r['revision'],'created':r['created'],
                                    'staff':r['staff'],'observation':json.loads(r['observation'])} for r in history],
            'cases':[{'id':r['id'],'position':r['position'],'photo_id':r['photo_id'],'photo_revision':r['photo_revision'],
                      'expires':r['expires'],'snapshot':json.loads(r['snapshot']),'observation':json.loads(r['observation'])} for r in rows]}


def bundle(queue,rows):
    file=tempfile.TemporaryFile()
    try:
        manifest = report(queue,rows)
        with zipfile.ZipFile(file,'w',zipfile.ZIP_STORED) as z:
            for row in rows:
                data=input_bytes(row)
                z.writestr(f'{row["position"]:03d}-{row["id"]}.jpg',data)
            evidence = {}
            for entry in manifest['observation_history']:
                for info in entry['observation'].get('assets',{}).values():
                    evidence[(entry['case_id'],info['file'])] = info['sha256']
            for (case_id,filename),digest in evidence.items():
                data=(config.TEST_QUEUE_DIR/queue['id']/case_id/filename).read_bytes()
                if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Test evidence changed; inspect this case before exporting')
                z.writestr(f'evidence/{case_id}/{filename}',data)
            z.writestr('manifest.json',json.dumps(manifest,indent=2))
        file.seek(0);return file
    except Exception:
        file.close();raise


def purge(c,now,removed_sources,rejected_sources):
    rows=c.execute('SELECT id,queue_id FROM test_cases WHERE expires<=? OR photo_id IN (SELECT id FROM photos WHERE status=\'rejected\')',(now,)).fetchall()
    # Caller has already deleted source rows, so also use the explicit removed IDs.
    rows += [r for r in c.execute('SELECT t.id,t.queue_id,t.photo_id,q.keep_snapshots FROM test_cases t JOIN test_queues q ON q.id=t.queue_id')
             if r['photo_id'] in rejected_sources or (r['photo_id'] in removed_sources and not r['keep_snapshots'])]
    for row in rows:
        shutil.rmtree(config.TEST_QUEUE_DIR/row['queue_id']/row['id'],ignore_errors=True)
        # Keep only the aggregate fact that a case existed; clear DOB, feedback and measurements.
        c.execute("UPDATE test_cases SET snapshot='{}',observation='{}',expires=? WHERE id=?",(now,row['id']))
        c.execute('DELETE FROM test_observations WHERE case_id=?',(row['id'],))
    expired=c.execute('SELECT id FROM test_queues WHERE expires<=?',(now,)).fetchall()
    for row in expired:
        for item in c.execute('SELECT id FROM test_cases WHERE queue_id=?',(row['id'],)).fetchall():
            c.execute('DELETE FROM test_observations WHERE case_id=?',(item['id'],))
        c.execute('DELETE FROM test_cases WHERE queue_id=?',(row['id'],))
        c.execute('DELETE FROM test_queues WHERE id=?',(row['id'],))
        shutil.rmtree(config.TEST_QUEUE_DIR/row['id'],ignore_errors=True)
