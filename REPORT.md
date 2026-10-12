# Tuttoprint Passport Photo Code System: Project Report

*Last updated: 12 October 2026*

## Tuttoprint Photo Studio update (12 October 2026)

The repository now includes the supplied installation's 208 country/document
profiles and 169 print layouts, an independent studio prototype, country-specific AI
crops, pending-photo adjustments and digital exports. This update is prepared
for review; it has not been deployed to the live VPS. See
[reference import and validation](docs/PHOTOMATIC.md). The confirmed workflow is
file upload and printing on a Fujifilm DE100-XD. The imported default print canvas
is not a calibrated DE100-XD sheet. See the
[system specification and remaining gaps](docs/SYSTEM_SPEC.md). UK code retrieval is retained;
Irish code issuance requires a separate provider connection and remains disabled.
See [Irish integration research](docs/IRISH_CODES.md).

## 1. What it is

An in-shop system that turns a customer's photo into a **UK passport photo code**.
The customer enters the code on gov.uk, and HM Passport Office (HMPO) collects the
photo directly from our server. It replaces the retiring Fujifilm ID service.

**Historical UK service result recorded before the studio update.** On 12 Oct 2026 a test code (`tpcode.uk/nKAeerjA`) was
entered on gov.uk and HMPO successfully retrieved the photo.
This records the earlier deployment; it does not verify the current branch's
production status or complete studio workflow.

## 2. How it works

1. Staff open **https://staff.tpcode.uk/admin** in any browser and log in.
2. **+ New photo**: take or upload the photo (e.g. from the Canon camera).
3. The earlier system automatically:
   - finds the face and crops to passport size (35×45 mm ratio, 1050×1350 px)
   - offered automatic colour/exposure correction, face-shadow softening and background evening
   - runs checks: one face, head straight, facing camera, eyes open, neutral expression, sharpness, lighting, background, glasses glare, resolution
4. The staff member reviews **Before / After** and the checklist, then clicks **Issue photo code**.
5. Preview the selected photo sheet and/or code slip. The target shop printer is
   the **Fujifilm DE100-XD**; physical layout calibration is still required.
6. The customer applies at gov.uk and enters the code. HMPO fetches the photo.

### Security
- The code address (`tpcode.uk/XXXXXXXX`) only returns the photo to **HMPO**. Every
  request must carry HMPO's digital signature, which the server checks against
  HMPO's published key. Anyone else gets "not found".
- The staff page is password-protected.
- Original shop uploads are kept while pending and removed when issued, rejected
  or expired. Photos without a code are deleted after 24 hours,
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

1. Complete profile-specific rules, final export validation and the job lifecycle.
2. Complete familiar crop controls, measurement/background inspectors and output dialogs.
3. Calibrate the DE100-XD sheet, driver settings and print colour management.
4. Record staff review/consent and validate the own UK code service after deployment.
5. Establish independent Irish provider onboarding and retrieval.
6. Run paired reference-photo and physical-print acceptance jobs.

The [system specification](docs/SYSTEM_SPEC.md) gives the detailed scope and
completion checks. Native camera control is outside the confirmed upload workflow.

## 7. Note on auto-enhance

UK and Irish published photo rules prohibit digital alteration. The prototype's
enhancement options default off, but server-side document/output restrictions
remain to be implemented. Treat passport analysis/cropping, general ID editing
and print colour management as separate operations. Sources:
[UK photo rules](https://www.gov.uk/photos-for-passports/photo-requirements),
[Irish photo guidelines](https://api.ireland.ie/en/dfa/passports/photo-guidelines/).

## 8. Code overview (for a developer)

- `app/main.py`: web app (staff pages, HMPO endpoint, printing, auto-delete)
- `app/processing.py`: face detection, crop, auto-enhance, checks, 6×4 print sheet
- `app/hmpo_auth.py`: HMPO signature verification
- `app/db.py`: database (SQLite in `/var/lib/tpcode`)
- `scripts/install.sh`: one-command server install/update
- `tests/test_e2e.py`: automated tests (all passing)
