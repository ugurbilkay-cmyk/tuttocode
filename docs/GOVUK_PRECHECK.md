# GOV.UK browser precheck for development tests

This optional test runner uploads a specifically selected final JPEG through
the normal public passport browser journey. It captures the visible rating and
feedback and stops at **Photo result**. It does not submit an application or
generate a photo code. It is separate from the shop's current preparation UI;
no staff code-generation controls or overrides have changed.

On 14 October 2026 the shared workflow ran through the Codex browser driver in
7.12 seconds and returned **Good**. That timing comes from one repeated sample
with an existing browser session, not a latency guarantee. The same shared
workflow powers the local CLI; its separate browser launcher has not been
live-tested on GOV.UK yet. No supported public validation API has been confirmed.
This is a development proof of concept, not a validated bulk supplier service.

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
