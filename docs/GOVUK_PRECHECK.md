# GOV.UK browser precheck for development tests

For the current usable local testing routine, use **More → Test queues** and the
[staff-operated queue](STAFF_TEST_QUEUE.md): frozen inputs, normal manual browser
uploads, recorded observations, exact vendor colours and downloadable evidence.
This avoids relying on the blocked standalone runner described below. It does
not automate the external service or remove its access controls.

This optional test runner uploads a specifically selected final JPEG through
the normal public passport browser journey. It captures the visible rating and
feedback and stops at **Photo result**. It does not submit an application or
generate a photo code. It is now available in the studio as **Check with GOV.UK ·
test**, alongside the separate CLI. Staff code-generation controls and overrides
have not changed.

On 14 October 2026 the shared workflow ran through the Codex browser driver in
7.12 seconds and returned **Good**. That timing comes from one repeated sample
with an existing browser session, not a latency guarantee. The same shared
workflow powers the local CLI and button. A subsequent live button-route test
using the standalone browser received **Web Page Blocked** before uploading any
photo or DOB. It was stored as unavailable, with a screenshot; no bypass or retry
was attempted. Earlier Codex-browser success does not establish that this local
automatic route is usable. No supported public validation API has been confirmed.
This is a development proof of concept, not a validated bulk supplier service.

### Block diagnosis — 14 October 2026

Reading the saved screenshot at its original resolution identified Attack ID
**20000051**, with Message ID **000000041021**. Fortinet's published rule mapping
identifies 20000051 as **Known Bots Detection**, which strongly supports an
automation/security-policy rejection rather than an ICAO failure. The precise
site deployment, triggering request signature and any false-positive decision
still require the operator's logs.
[Fortinet rule reference](https://docs.fortinet.com/document/fortiweb/8.0.1/log-message-reference/932525/20000051),
[Attack-ID mapping](https://docs.fortinet.com/document/fortiappsec-cloud/25.4.0/user-guide/806732/attack-logs).

Read-only local diagnostics found no configured macOS proxy, proxy environment
variables or registered system extensions. One normal TLS-verified HTTP request
reached a CloudFront/Queue-it redirect rather than the same block; it did not
reach the upload flow, transmit a photo/DOB, prove automation permission or
establish that the public precheck adapter is usable. Queue tokens and cookies
must not be reused as an access workaround or included in support reports.

The runner now preserves the numeric access-denial references, categorises the
known-bot denial and explicitly distinguishes it from photo-quality rejection.
The diagnostic summary does not copy IP addresses or session tokens. Existing
scores and failure records are not converted to passes. No stealth browser,
identity/header spoofing, proxy routing, TLS weakening or gate bypass was added.

The requested durable resolution is an HMPO-approved supplier validation API,
test environment or explicitly authorised automated-browser integration. None
has been confirmed. The user has no existing supplier technical contact or test
account. A concrete technical enquiry is saved privately at
`output/govuk-access-diagnostics/hmpo-enquiry-draft.txt`, with no customer photos,
DOBs, credentials or network addresses. The user declined sending it; it remains
unsent. The official general
enquiry route can be asked to direct it to the photo-supplier/DCS technical team;
it is not itself a published supplier integration endpoint.
[HMPO contact options](https://www.gov.uk/passport-advice-line).

## Studio test button

Prepare/apply the photo, then click **Check with GOV.UK · test**. Enter the birth
date, label synthetic sample dates where appropriate, and confirm permission
for the selected photo/DOB transfer. Click **Run GOV.UK check**. The page polls
for the result; closing the panel leaves the check running, and reopening shows
its history. Run one photo at a time. New runs explicitly check the saved export,
not the uncropped original or unaccepted OpenAI preview.

Each run freezes the same JPEG bytes returned by Save, with its profile, revision,
master and export digests, staff and timestamp. If the photo changes, the result
is marked as belonging to an earlier version. The panel offers the exact frozen
JPEG and result screenshot through authenticated routes. Unavailable automated
access also has a normal GOV.UK browser link for staff-assisted checking; it does
not turn a manually observed result into an automatic pass.

Enable the optional test feature on the server with `GOVUK_PRECHECK_ENABLED=1`.
`GOVUK_NODE` can select the Node executable; `GOVUK_TIMEOUT_SECONDS` bounds the
worker (90 seconds by default). Install the browser as shown below. The worker
runs locally in the background and receives no OpenAI/SMTP/staff credentials;
its private input manifest carries the photo path and DOB instead of command-line
arguments. Files and records follow the photo's expiry/rejection cleanup. This
feature is enabled in the existing local preview, not deployed to production.

## Run one selected photo

From the repository directory, install the runtime once:

```sh
npm ci
npx playwright install chromium
```

For the authorised installed sample and a clearly labelled placeholder birthday:

```sh
npm run test:govuk-photo -- \
  --photo output/simple-studio-20261014/uk-online-export.jpg \
  --dob 1980-01-01 \
  --synthetic-dob \
  --authorised-upload
```

For customer comparisons, pass the correct birthday and omit `--synthetic-dob`.
`--authorised-upload` records that sharing the selected photo and DOB with
GOV.UK is authorised. Their privacy policy permits retention for up to six
months, including incomplete applications. Select an immutable exported JPEG
between 50 KB and 10 MB; the runner rechecks its fingerprint before upload.
[HMPO privacy policy](https://www.passport.service.gov.uk/help/privacy).

Each invocation opens a separate browser and writes a fresh folder under
`output/govuk-prechecks/`, containing `result.json` and `result.png`. Use
`--output /absolute/directory` to choose another destination. Private photo/DOB
evidence must remain outside source control.

## Result meaning

- `good`: the actual Photo result page contained the Good rating.
- `needs_review`: a photo result appeared without Good; retain its actual
  feedback for staff review. Other rating variants are not live validated yet.
- `unavailable`: a queue, challenge, changed JPEG, unfamiliar page, timeout or
  other failure prevented a verified result. Exit status 2 identifies this case.

The browser uses the tested UK-resident, no-previous-passport navigation context
only to reach the upload check. It submits no final application. Child journeys
and age-dependent exceptions still need separate live verification; an arbitrary
adult DOB must not represent a child validation case. The runner records this
context and marks synthetic birthdays ineligible for customer comparisons.
Only adult age contexts are currently eligible for the runner's validated
comparison marker; child results remain separate until those journeys are verified.

The screenshot and JPEG digest establish what was uploaded and what the page
said. They do not establish the internal government crop, all ICAO metrics,
Photomatic's three dark-green categories, or final passport acceptance.
Passing also does not establish compliance of facial edits with the separate
[official editing rules](https://www.gov.uk/government/publications/photographic-standards/photo-standards-accessible#photo-editing).

Do not speed this up with simultaneous live submissions, guessed private API
calls or repeated automatic retries. First measure ordinary browser reliability
and verify an appropriate HMPO route before scaling beyond controlled tests.
No 200/1000-customer bulk validation has started.

## Verify the workflow logic offline

```sh
npm run test:govuk
```

The tests make no GOV.UK requests. They verify exact-file provenance, birthday
validation, a single upload, stopping before application continuation, unknown
ratings, unavailable states and separate saved evidence for every run.

The implementation follows the documented
[Playwright file-chooser](https://playwright.dev/docs/api/class-filechooser) and
[page APIs](https://playwright.dev/docs/api/class-page), with a small driver
interface so the ordinary Codex browser can exercise the same workflow.
