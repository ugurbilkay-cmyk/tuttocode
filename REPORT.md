# Tuttoprint Passport Photo Code System: Project Report

*Last updated: 12 October 2026*

## Photomatic AI update (12 October 2026)

The repository now includes the supplied installation's 208 country/document
templates and 169 print layouts, a Photomatic-style station, country-specific AI
crops, pending-photo adjustments and digital exports. This update is prepared
for review; it has not been deployed to the live VPS. See
[implementation and validation](docs/PHOTOMATIC.md). UK code retrieval is retained;
Irish code issuance requires a separate provider connection and remains disabled.
See [Irish integration research](docs/IRISH_CODES.md).

## 1. What it is

An in-shop system that turns a customer's photo into a **UK passport photo code**.
The customer enters the code on gov.uk, and HM Passport Office (HMPO) collects the
photo directly from our server. It replaces the retiring Fujifilm ID service.

**UK service status before the Photomatic update: live and working.** On 12 Oct 2026 a test code (`tpcode.uk/nKAeerjA`) was
entered on gov.uk and HMPO successfully retrieved the photo.

## 2. How it works

1. Staff open **https://staff.tpcode.uk/admin** in any browser and log in.
2. **+ New photo**: take or upload the photo (e.g. from the Canon camera).
3. The earlier system automatically:
   - finds the face and crops to passport size (35×45 mm ratio, 1050×1350 px)
   - offered automatic colour/exposure correction, face-shadow softening and background evening
   - runs checks: one face, head straight, facing camera, eyes open, neutral expression, sharpness, lighting, background, glasses glare, resolution
4. The staff member reviews **Before / After** and the checklist, then clicks **Issue photo code**.
5. Print the **Photomatic sheet** (the selected imported layout; UK defaults to six photos) on the Mitsubishi, and/or the **code slip** for the customer.
6. The customer applies at gov.uk and enters the code. HMPO fetches the photo.

### Security
- The code address (`tpcode.uk/XXXXXXXX`) only returns the photo to **HMPO**. Every
  request must carry HMPO's digital signature, which the server checks against
  HMPO's published key. Anyone else gets "not found".
- The staff page is password-protected.
- Original uploads are not kept. Photos without a code are deleted after 24 hours,
  and issued codes and photos after 30 days. Every HMPO collection is logged.

## 3. What we set up

| Item | Detail |
|---|---|
| Server | Hostinger VPS **KVM 1**, Ubuntu 24.04, 1-month plan (£6.99 + VAT), renews at £10.99/mo |
| Domain | **tpcode.uk** (bought at Hostinger) |
| DNS | `A @ → server IP`, `A staff → server IP` |
| Code address | `https://tpcode.uk/<8-character code>`, used by HMPO only |
| Staff page | `https://staff.tpcode.uk/admin`, user `admin` (password shown once at install, not stored here) |
| HTTPS | Automatic (Caddy) |
| Code | GitHub `ugurbilkay-cmyk/tuttocode`, branch `main` |
| Firewall | Only SSH, web (80) and secure web (443) open |

**HMPO rules followed** (from passport.service.gov.uk/help/photo-codes):
JPEG between 50 KB and 10 MB, short URL format (domain 1–6 chars, TLD 2–3 chars,
path 6–8 chars), HTTPS, returns the image directly, and verifies HMPO's JWS token
including the `sub` matching the code URL.

## 4. Everyday commands (Hostinger → VPS → Web console)

**Update to the latest version:**
```
git -C /opt/tpcode pull && systemctl restart tpcode && sleep 4 && systemctl is-active tpcode
```

**Check it's running:**
```
systemctl is-active tpcode caddy
```

**See recent errors:**
```
journalctl -u tpcode -n 40 --no-pager -o cat
```

**See the last HMPO collections:**
```
/opt/tpcode/venv/bin/python -c "import sqlite3;c=sqlite3.connect('/var/lib/tpcode/tuttoid.sqlite3');[print(r) for r in c.execute('select * from fetch_log order by ts desc limit 10')]"
```

**Settings** (shop name, password, retention, enhance defaults) are in `/etc/tpcode.env`.
After changing them, run `systemctl restart tpcode`.

## 5. Problems fixed during setup

| Problem | Fix |
|---|---|
| App crashed: missing `libGL` | Added `libgl1 libglib2.0-0` to the installer |
| Photo processing error: missing `libEGL` | Added `libegl1 libgles2` to the installer |
| gov.uk "We can't find your code" | HMPO's token timestamp was treated as "in the future". Time checks were made tolerant (10 min, and milliseconds are handled). After the fix, gov.uk retrieved the photo. |

## 6. Still to do

1. **Test auto-enhance on real Canon photos** and fine-tune the crop (head size, space above head).
2. **Match the Fujifilm look**: send before/after pairs and settings screenshots from the Fujifilm system.
3. **Print test** of the 6×4 sheet on the Mitsubishi (check size and borders).
4. **ICO registration** (UK data protection fee), since we store customer photos.
5. **Hosting decision** after the 1-month trial (keep monthly, or switch to a longer plan).
6. Optional: email codes to customers (needs email settings), card payments, and auto-import straight from the Canon camera.
7. Optional: make the GitHub repo **private** (updates on the server would then need an access token).

## 7. Note on auto-enhance

HMPO's published rules say photos should be unedited. Colour and exposure fixes are
standard photo-lab adjustments. Face-shadow softening and background replacement go
further. Facial features are never reshaped, but HMPO could still reject a photo. Each
option can be switched off per photo, and the defaults are in `/etc/tpcode.env`
(`AUTO_ADJUST`, `FIX_SHADOWS`, `EVEN_BG`, `BG_REPLACE`). Keep an eye on the first
applications.

## 8. Code overview (for a developer)

- `app/main.py`: web app (staff pages, HMPO endpoint, printing, auto-delete)
- `app/processing.py`: face detection, crop, auto-enhance, checks, 6×4 print sheet
- `app/hmpo_auth.py`: HMPO signature verification
- `app/db.py`: database (SQLite in `/var/lib/tpcode`)
- `scripts/install.sh`: one-command server install/update
- `tests/test_e2e.py`: automated tests (all passing)
