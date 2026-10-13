# OpenAI preparation and reviewed UK code issuance

Current user decision, 13 October 2026: staff upload a camera photo and start
with the included local tools. OpenAI lighting/colour preparation is an optional
paid add-on. Quality results remain advisory; trained staff may issue under
explicit recorded responsibility despite red or unapproved checks. Irish codes are outsourced for
now. The rest of the familiar studio workflow is reproduced in our application.
The detailed measurements screen retains failures and documented allowances;
the latest staff-responsibility decision takes precedence over the earlier
request to block issuance on a failed check.

## Implemented workflow

1. Upload the camera original with a country/document and staff age selection.
   OpenAI is unchecked by default even with a configured key. Staff explicitly
   select the optional upgrade and record customer permission before an API call.
2. Save the original locally and measure face detection, source detail and framing.
   Poor quality does not prevent staff-requested preparation. A full-frame job
   fits the whole photograph when a passport crop cannot be produced; source
   warnings remain evidence rather than a claim of recovered detail.
3. Send an orientation-normalized, metadata-stripped PNG to the OpenAI Images
   edit endpoint. Do not send customer contact details. Request only lighting and
   colour corrections, with explicit preservation of appearance, face geometry,
   eyes, expression, distinguishing marks, hair, clothes and composition.
4. Independently detect and crop the edited result and rerun our local checks.
   Keep it as an AI preview; never silently overwrite the working photo.
5. Compare camera original and AI preview. Staff can inspect the preview's own
   detailed measurements, discard it or confirm likeness and accept it. Acceptance
   reruns the checks on the exact edited source. Crop adjustments subsequently use
   that source, avoiding another generative edit. A new AI request always starts
   from the camera original. Restore original removes AI preparation from the job.
6. Enforce code eligibility on the server. A pending AI preview must be accepted
   or discarded. Staff review failures and may use an explicit responsibility
   override, with an optional note; named document allowances remain supported.
   Staff record likeness/visibility review and customer permission for storage/delivery. The reviewed revision
   must match the current photo; stale review forms and replaced AI previews fail.
7. Validate the exact UK code JPEG, rerunning detection and checks after encoding
   and resizing without recropping it. Final failures are shown to staff; explicit
   staff responsibility permits issuance while retaining the failed results.
   Conflicting digital aspect limits can retain the reviewed framing under that
   decision, with delivery-format warnings recorded. Freeze that JPEG after review. Record its SHA-256, country, photo
   revision, processing options, AI request/model/prompt version, review identity,
   age allowances and exception decision. HMPO's signed request retrieves those
   exact bytes. Printing uses a separate master. Repeated issuance reuses the code.

The API key is server-only. Set `OPENAI_API_KEY` in deployment secrets or an ignored
`.env` file, never in JavaScript or a Git commit. `OPENAI_IMAGE_MODEL` defaults to
`gpt-image-2`; `gpt-image-1.5` is also supported with explicit high input fidelity.
The client uses the documented JSON image-reference interface, PNG output, up to
2048-pixel input edges and the documented 2K output-area range, with a bounded
response/timeout. It does not automatically retry billable image edits.
Failures leave the working photo unchanged and show a staff-readable message.
Requests on one job are serialized across application processes.

Source: [OpenAI image edit API](https://developers.openai.com/api/reference/resources/images/methods/edit).
Preservation instructions express the desired edit; they do not guarantee that a
generative model preserves every feature or that a passport service accepts it.

## Measurements and exceptions

The inspector follows the reference screen's grouping: image, biometric, image
quality and lighting measurements. It stores actual input/crop/master dimensions,
eye coordinates in master pixels, source/master inter-eye distance, eye angle,
head/eye/face percentages, Laplacian focus variance, face lightness/contrast,
lighting imbalance, candidate glare area and background colour/variation.

Our measurement units and thresholds are shown. Imported head/eye/width ranges,
maximum eye angle and minimum inter-eye distance are used where implemented.
Out-of-range active geometry is a failure. MediaPipe blendshape values are shown
as model outputs, not a copied Photomatic quality scale. Proprietary confidence,
general quality, motion blur, noise, artefact, compression, skin-colour and several
biometric scores remain explicitly **not tested**. A neutral grey cell is not a pass.
Our current checks are not a complete replica or certification of the native
FaceIt/Photomatic ICAO engine. That remains a release-validation requirement.

Quality failures are advisory. Staff can confirm `staff_override` to issue despite
working or final JPEG failures, including technical quality warnings. The record
contains identity, time, optional note, failed-check keys and full-frame status.
Failures stay failed; the decision is `staff_override`. The old generic
`override=on` field does not silently bypass review. Named document allowances
remain a separate evidence-backed route for existing clients. Missing measurements
never become machine-verified passes through a staff decision.

## Delivery, retention and limits

The normal UK delivery specification is at least 600 × 750 pixels and
50,000–10,000,000 bytes. Explicit staff override permits proceeding with warnings
when those specifications are not met; the exact returned file is still recorded.
Required digital dimensions are used when their aspect agrees with the reviewed
crop. The imported `UK online` 800 × 1150 requirement differs from its working
aspect; staff receive a format warning, and can explicitly retain the reviewed
crop under responsibility. `United Kingdom Online Renewal` (800 × 1120) and the
UK paper profile have coherent working/export aspects.
Originals of AI-prepared and staff-overridden issued jobs remain available for comparison
until the code's expiry/deletion. Accepted AI sources and previews are deleted
when no longer needed. Rejection and expiry remove all photo artefacts and job data.

Irish code buttons are replaced by the manual external-provider workflow: Save
the photo and submit it to the chosen provider. `IRISH_PROVIDER_URL` can open that
provider's HTTPS page; it does not issue or validate Irish codes. No external
provider was contacted or submitted to by this change.

The user has chosen enhancement. The product records that decision without
claiming it supersedes passport requirements: UK guidance requires photos
unaltered by software; Ireland prohibits digitally enhanced or changed photos.
Passing local checks or issuing a transport code does not establish acceptance.
Sources: [UK digital photo rules](https://www.gov.uk/photos-for-passports),
[Irish photo guidelines](https://api.ireland.ie/en/dfa/passports/photo-guidelines/).

## Validation and remaining work

Tests cover the current/legacy API request schemas, metadata stripping, bounded
image validation, redacted provider errors, no-key and timeout behaviour, automatic
upload preparation, preview acceptance/discard/restore, stale reviews, processing
locks, staff-only access, persisted metrics, failure/exception gates, immutable
signed delivery, online export size, child allowance records and complete deletion.
The 25 AI/API workflow tests and 12 catalog/processing tests pass, alongside
   the end-to-end web/signature suite. API tests use synthetic images and a mocked
   OpenAI response, not real API output. The supplied IMG_1012 reference sample
   also passed the real local engine and final UK paper-code JPEG check; its UK
   Online Renewal crop lacked enough original headroom and was correctly blocked.
   Fine rotation at ±2° was checked with the real landmark engine. The measurement
   grouping was visually verified in Safari.

No OpenAI key is configured in the current execution environment, so **real image
edits have not been tested**. Before shop release, test the configured model on
consented samples and check facial details, colour and framing before/after.
Exact native metric equivalence, calibrated DE100-XD physical printing, remaining
country policy exceptions and a real HMPO retrieval after deployment remain open.
See [the full gap audit](SYSTEM_SPEC.md) for the rest of the reproduction work.
