"""Render isolated studio pages for DOM interaction tests; no external requests."""
import base64
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='tuttocode-studio-dom-'),
                  ADMIN_PASSWORD='test-only', OPENAI_API_KEY='', HMPO_KEY_URL='', GOVUK_PRECHECK_ENABLED='1')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from starlette.testclient import TestClient
from app import config, db, main, processing
from synthetic import Fake, make_face

logging.getLogger('httpx').setLevel(logging.WARNING)
folder = ROOT / 'output/station-dom-fixtures'
folder.mkdir(parents=True, exist_ok=True)
db.init()
source, analysis = make_face()
processing._analyzer = Fake(analysis)
client = TestClient(main.app, headers={'Authorization': 'Basic ' + base64.b64encode(b'admin:test-only').decode()})
with patch.object(config, 'OPENAI_API_KEY', 'unit-test-only'):
    (folder / 'new.html').write_text(client.get('/admin/new').text)
    response = client.post('/admin/new', data={'opts': '1'},
        files={'photo': ('synthetic.jpg', source, 'image/jpeg')}, follow_redirects=False)
    assert response.status_code == 303
    path = response.headers['location']
    (folder / 'photo.html').write_text(client.get(path).text)
    pid = path.rsplit('/', 1)[-1]
    with db.conn() as conn:
        conn.execute('UPDATE photos SET ai_state=? WHERE id=?', (json.dumps({
            'status': 'ready', 'candidate_id': 'synthetic-preview', 'checks': [],
            'measurements': {}, 'original_checks': [], 'ok': False}), pid))
    (folder / 'ready.html').write_text(client.get(path).text)
    with db.conn() as conn:
        conn.execute("UPDATE photos SET status='issued', ai_state='{}' WHERE id=?", (pid,))
    (folder / 'readonly.html').write_text(client.get(path).text)
print('Rendered isolated new, pending, AI-preview and read-only studio fixtures.')
