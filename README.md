# Tuttoprint passport photo codes

See **REPORT.md** for the full project report.

## Run
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
`python3 tests/test_e2e.py`
