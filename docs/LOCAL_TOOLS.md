# Included local tools and optional OpenAI upgrade

Implemented 13 October 2026. The core workflow starts with local tools and no
per-photo API call. OpenAI is an optional extra service, unchecked on new jobs
and presented separately from the included tools. This positions the product
for the user's paid add-on model; pricing, payments, shop entitlements and
credit accounting have not been implemented. A configured key enables the
explicit staff-requested API action, not automatic fallback or purchase.

## Local adjustment controls

`local-tones-v1` implements nine bounded, deterministic controls: exposure
(-1.5 to +1.5 EV), brightness, relative white-balance temperature and tint,
highlight compression, shadow lifting, contrast, colour strength and local
contrast. Highlight/shadow curves work in linear light. Brightness/contrast
operate on perceptual Lab lightness. Local contrast blends at most 25% of
OpenCV CLAHE on lightness, with a conservative clip limit. No generative model,
face warping, beautification or network call is part of these operations.
The [OpenCV CLAHE documentation](https://docs.opencv.org/4.12.0/d6/db6/classcv_1_1CLAHE.html)
describes the contrast-limited histogram operation.

Existing automatic colour/exposure, face-shadow softening, background-light
evening and foreground-segmented background replacement remain available.
These tools still require validation across shop lighting and customers. The
white-balance sliders are relative channel adjustments, not a camera-calibrated
Kelvin correction. Highlight compression reduces bright values; it does not
recover absent original detail. Local contrast can also make noise more visible.

Neutral sliders are an exact no-op. Values are validated as finite and within
the stated control range. They are stored in the job and final issue evidence.
Reprocessing always starts from the retained original or accepted AI source,
so applying the same settings again does not accumulate corrections. Reset
clears sliders and local automatic options; Apply changes reruns processing
and checks, and invalidates any unaccepted AI preview. Before/After and the
regional inspector support staff comparison.

## Full-frame / print jobs

Full-frame mode uses the whole EXIF-oriented source without a biometric crop,
fits it to the chosen output format, and adds borders when needed. It does not
stretch faces or generate missing surroundings. Print and Save remain available
even for small sources or an unavailable face detector. Manual whole-image
controls work without landmarks; face-shadow and segmented background tools
depend on their respective measurements. Missing measurements and poor source
resolution remain visible. Enlarging a print master does not certify source detail.

OpenAI can be requested for a readable poor-quality original. The original
diagnostic findings are retained separately from the candidate's results. When
a biometric crop cannot be produced, the candidate uses full-frame output.
The requested API canvas can be enlarged for this edit/print workflow; it is
never described as proving additional original detail. A preview must still be
compared and accepted/discarded by staff, and billable requests are not retried
automatically.

## Staff responsibility

The user's decision is that trained staff retain control. Red checks do not
disable the Issue UK code button. Staff can proceed using **Issue despite failed
or unapproved quality checks — I take responsibility for this decision**.
An optional note, staff identity, timestamp, current and final failed-check keys,
full-frame status, exact delivery SHA-256 and final measurements are recorded.
The original is retained for AI or responsibility-overridden jobs until normal expiry.
The decision is `staff_override`; failures remain failed rather than turning green.
Named document allowances remain supported for existing integrations, but are
not the only route to an accountable staff decision.

The exact delivered JPEG is still assessed. A new final failure is shown for
review when responsibility has not been confirmed; staff can then proceed.
An explicit override can retain a reviewed crop despite a conflicting legacy
digital aspect requirement, and can proceed despite digital size warnings.
Those delivery warnings are recorded as failed checks. Readable files,
authentication, current-revision review, finished AI review and concurrent-edit
protection remain operational requirements. UK own-code scope and outsourced
Irish codes are unchanged. Issuing a delivery code is not government acceptance.

## Validation

Tests cover exact no-op output, deterministic/non-destructive reprocessing,
exposure/brightness/white-balance direction, monotone highlight compression,
shadow lifting, parameter validation, default-off API selection, no API call
for local uploads, low-resolution print output, explicit staff responsibility,
preservation of failed checks and final JPEG failures. Existing crop, export,
privacy and signed-delivery regression tests remain required. These checks
verify implementation, not industrial accuracy or physical DE100-XD calibration.
