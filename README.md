# Photomatic AI + Tuttoprint passport photo codes

See **REPORT.md** for the full project report.

The station now imports the supplied Photomatic installation's 208 country/document
templates and 169 printer layouts. `/admin` opens the Photomatic-style workspace;
`/admin/history` shows previous photos. Select a country, open a photo or use a
browser camera, review the AI crop, then Print, Save or Email. Pending shop photos
can be moved, zoomed, rotated and processed again.

The existing UK HMPO code service is retained. Irish passport templates are available
for photo export, but Irish **code issuance is disabled** until a provider connection
is established. No other country can be issued an online passport code.

See [Photomatic implementation notes](docs/PHOTOMATIC.md) and
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
