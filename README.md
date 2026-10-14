# Tuttoprint Photo Studio and passport photo codes

Tuttoprint's independent studio uses TuttoCode for photo processing and its own
UK code service. The confirmed shop workflow is file upload, document selection,
photo review/correction, and printing on a **Fujifilm DE100-XD**.

The engine runs independently of Photomatic. Open `/admin/new` to upload and
process photos with our local tools and optional OpenAI preparation. Changes to
crop controls take effect on Prepare and check photo or Apply changes. Import
Photomatic export is a separate, optional vendor-review workflow. The immediate
priority is our working engine; Photomatic analysis/integration is a progressive
research track, not a requirement for using it.

Each prepared job now shows **What actually ran**, separating completed local
model inference from skipped/failed/unselected tools. Default landscape crops
fit the camera pixels while keeping real template failures. Existing OpenAI
previews can be rebuilt locally without another API request. See
[pipeline execution evidence](docs/PIPELINE_EXECUTION.md).

For validation studies, **More → Test queues** (`/admin/tests`) freezes selected
Save JPEGs and lets staff record normal GOV.UK browser feedback and separate
Photomatic category colours. Batch downloads include exact files and evidence;
the external upload/check steps remain manual. See [the queue workflow](docs/STAFF_TEST_QUEUE.md).

The prototype imports the supplied reference installation's 208 country/document
profiles and 169 print layouts. `/admin` opens the studio workspace;
`/admin/history` shows previous photos. The main screen has four steps: Upload,
Country and crop, Background, and Enhance. Choose Natural, Balanced or Recovery
enhancement; the engine analyses the source, selects bounded lighting and shine
correction, polishes skin independently from noise and checks local spots while
guarding source feature detail. The
separate OpenAI service remains optional. See [adaptive profiles](docs/ADAPTIVE_QUALITY.md).
UK print and UK online code have separate shortcuts. Online Renewal uses a 5:7
crop and 800 × 1120 digital export. Prepare or Apply updates the crop and checks;
Print, Save and Email use the current result. Pending shop photos
can be moved, zoomed, rotated and processed again. These imported layout families
are reference settings, not connected devices or a calibrated DE100-XD profile.
Fine rotation and a detailed measurements inspector are now available. Full native
quality-score parity, template-policy handling and DE100-XD calibration remain
incomplete.
The staff **Inspect hotspots** control compares estimated facial regions on the
camera original, current photo and any pending AI candidate. It reports actual
native-pixel highlight measurements with matching overlays. These diagnostics
are not calibrated approval scores; see [the hotspot inspector](docs/HOTSPOT_INSPECTOR.md).

The existing UK HMPO code service is retained. Irish passport templates are available
for photo export; Irish codes are **outsourced for now**. Save the photo and
submit it through your chosen external provider. No other country can be issued an online passport code.

OpenAI preparation uses one setup for exposure, lighting, colour, gentle skin
cleanup, reduced excessive shine and natural detail. Explicit preservation
instructions cover facial features, geometry and identifying marks; the result
has a separate preview, staff likeness review
and local rechecks before code issuance. Configure `OPENAI_API_KEY` on the server
to enable the optional upgrade; it is not selected by default. Included local
tools provide exposure, brightness, white balance, highlights, shadows, contrast,
colour strength and local contrast, alongside background and facial lighting
tools. Full-frame jobs allow adjustment and printing of poor sources. Quality
checks are advisory: staff can explicitly take responsibility for issuing despite
failed checks, which remain red and are stored in the issue record. Read the
[AI workflow and validation limits](docs/AI_WORKFLOW.md).
See [local tools and staff responsibility](docs/LOCAL_TOOLS.md) for the workflow.
Local background removal now offers HR-matting (default maximum detail),
BiRefNet-portrait, MODNet and the existing basic mask. See the
[background-removal setup and evaluation](docs/BACKGROUND_REMOVAL.md) for
the optional worker runtime, model installation and measured limitations.
The [local image enhancer](docs/IMAGE_ENHANCER.md) adds editable portrait presets,
Retinexformer lighting, NAFNet noise cleanup, detail sharpening and optional
RealPLKSR or Real-ESRGAN 2×/4× enlargement. All are off until selected; OpenAI remains optional.

Read the [workflow specification and gap audit](docs/SYSTEM_SPEC.md) before treating
this prototype as a replacement for the current shop software. See also
[reference template implementation notes](docs/PHOTOMATIC.md) and
[Irish code integration research](docs/IRISH_CODES.md).

The [standards decoding notes](docs/STANDARDS_DECODING.md) and generated
[field guide](docs/standards/FIELD_GUIDE.md) document individual settings, defaults
and verified application comparisons. They distinguish stored thresholds from
native engine algorithms and current government requirements.

[Official-rule comparisons](docs/OFFICIAL_VALIDATION.md) record the first country
cross-checks. [Print pipeline evidence](docs/PRINT_PIPELINE.md) covers the Backup
jobs, Frontier installer and DE100 colour data, including differences between
saved templates and completed output.

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
pip install -r requirements-dev.txt
python3 tests/test_photomatic.py
python3 tests/test_ai_preparation.py
python3 tests/test_hotspots.py
python3 tests/test_local_tools.py
python3 tests/test_background.py
python3 tests/test_enhancement.py
python3 tests/test_skin.py
python3 tests/test_blemishes.py
python3 tests/test_e2e.py
```

For studio interaction tests, install the development DOM dependency with
`npm ci`, render isolated fixtures with `python3 tests/render_station_fixtures.py`,
then run `npm run test:station`. These tests exercise the real station JavaScript
in a simulated DOM; they do not replace visual browser verification.

Queue checks: `python3 tests/test_test_queue.py`, then
`python3 tests/render_test_queue_fixtures.py` and `npm run test:queue`.
