# Tuttoprint Photo Studio and passport photo codes

Tuttoprint's independent studio uses TuttoCode for photo processing and its own
UK code service. The confirmed shop workflow is file upload, document selection,
photo review/correction, and printing on a **Fujifilm DE100-XD**.

The prototype imports the supplied reference installation's 208 country/document
profiles and 169 print layouts. `/admin` opens the studio workspace;
`/admin/history` shows previous photos. Select a country, open a photo or use a
browser camera, review the AI crop, then Print, Save or Email. Pending shop photos
can be moved, zoomed, rotated and processed again. These imported layout families
are reference settings, not connected devices or a calibrated DE100-XD profile.
Fine rotation, full template-policy handling, detailed inspectors and DE100-XD
calibration remain incomplete.

The existing UK HMPO code service is retained. Irish passport templates are available
for photo export, but Irish **code issuance is disabled** until a provider connection
is established. No other country can be issued an online passport code.

Read the [workflow specification and gap audit](docs/SYSTEM_SPEC.md) before treating
this prototype as a replacement for the current shop software. See also
[reference template implementation notes](docs/PHOTOMATIC.md) and
[Irish code integration research](docs/IRISH_CODES.md).

## Run
Requires Python 3.10 or later (Ubuntu 24.04 uses Python 3.12).
```
pip install -r requirements.txt
sh scripts/download_models.sh
cp .env.example .env   # edit it
set -a; . ./.env; set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
```

## Domains (both point to this app, HTTPS via Caddy/nginx)
- `staff.tpcode.uk` – staff station `/admin`
- `tpcode.uk` (SHORT_DOMAIN) – serves codes to HMPO only (JWS-verified)

Reverse proxy must pass the original `Host` header.

## Test
```
python3 tests/test_photomatic.py
python3 tests/test_e2e.py
```
