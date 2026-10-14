# Per-photo processing evidence and crop recovery

Updated 14 October 2026. This describes implemented execution evidence, not full
ICAO conformance or calibrated Photomatic parity.

The studio now includes **What actually ran · this photo**, and a separate panel
for a pending OpenAI preview. These use saved measurements and worker evidence.
Selecting a model, having its weights installed, or passing mocked workflow
tests is not recorded as successful inference.

MediaPipe records the actual FaceLandmarker model digest, face count, landmark
count, analysis dimensions and elapsed inference time, plus segmentation
availability. Older jobs show saved geometry without claiming model provenance
that was not recorded. Missing/failed facial analysis returns a visible failure;
subsequent facial stages are not described as completed.

Background-removal evidence distinguishes applied output, a reused verified
source mask, an unavailable worker, a stage not reached and an unselected tool.
NAFNet/Retinexformer use the completed worker's model digest and timings. Detail
sharpening and edge-aware skin smoothing are separate local pixel operations;
they are not labelled learned face reconstruction. Regional hotspot measurements
use estimated facial regions and native JPEG pixels. Their thresholds remain
uncalibrated diagnostics, not proprietary confidence scores.

## The landscape-source failure

An actual 6000×4000 upload detected one face and 478 landmarks. The default UK
online target requested a 3492×4889 crop. Because that height exceeded the camera
image, the previous pipeline returned before the selected background remover,
noise cleanup and skin smoothing. Its OpenAI image had genuinely been returned,
but local preparation fell back to a full-frame print layout with borders. The
old “proposed crop” caption obscured this distinction.

A default automatic crop now moves inside the source and, if needed, reduces
its size at the selected aspect ratio. It preserves the detected head/face
extent, prefers allowed eye placement and never invents padding for this crop.
Head/eye rules still assess the actual result; infeasible rules remain failed.
Explicit manual adjustments and already-framed delivery validation are not
silently replaced. Crops with a detected head extending outside the camera
image still need staff adjustment or a different source. Source, requested and
actual crop rectangles are retained in measurements.

Head-size failure text retains decimals so a boundary estimate is not rounded
into an apparently contradictory integer. Detailed metric colours use recorded
check status before a rounded-value comparison.

## Live zoom and movement preview

The studio's zoom and movement controls now update the visible framing on input,
before Apply changes. For prepared, unrotated jobs with recorded geometry, an
authenticated small raster of the retained working/camera source supplies real
pixels outside the saved crop. Client-side positioning uses the stored source
rectangle and eye anchor; repeated slider movements run no model or OpenAI
request. The preview is explicitly a crop view of source pixels: Apply changes
renders the selected background/enhancement tools and updates measurements.

Manual zoom/offsets now start from the feasible automatic base rectangle rather
than reverting to the impossible nominal target. The actual crop and its base,
anchor and target are recorded. Out-of-source positions still fail on Apply;
the preview warns rather than inventing missing pixels. Reset restores the
saved view when values match. Old jobs without geometry, country switches,
existing rotations and source-load failures use a labelled approximate preview;
new rotation adjustments are also approximate until local reanalysis on Apply.

The source route is staff-only, chooses an accepted working source when present,
and performs only image decoding/resizing. Issued delivery bytes are unchanged.
Eleven crop/status tests, 33 API/workflow tests, 13 catalog tests and DOM checks
pass. A real 6000×4000 camera source verified that 1.1× zoom reduces both crop
dimensions by 1.1 while preserving eye placement; the private preview route and
its access checks passed. No saved customer job was changed and no new paid request
was made in this verification.

## OpenAI preview and local rebuild

New OpenAI previews retain the selected local background, enhancer and manual
pixel choices. Camera-reference checks remain unadjusted; automatic colour and
shadow correction are not stacked over the paid edit by default. A full-frame
fallback is explicitly labelled as a print layout, with no passport-crop claim.

**Refresh crop and selected local tools · no OpenAI call** rebuilds both the
current preparation and its pending preview from retained sources. It checks
authentication, pending status, current revision, candidate ID and camera/AI
source hashes. It preserves the paid source, request ID and transfer provenance,
increments the preparation revision and creates a new candidate ID. The preview
remains unaccepted until staff compare likeness. Unsaved settings disable this
action; apply those changes first. This route makes no OpenAI request.

## Real execution evidence

The affected live job was rebuilt in 194.9 seconds on the Mac CPU. Its camera
result recorded 478 real MediaPipe landmarks, BiRefNet HR inference at 78.235 s,
NAFNet inference at 21.032 s, local skin smoothing and five facial hotspot
regions. The retained paid source was unchanged. Its preview recorded a separate
63.839 s background inference, a proper portrait crop and no full-frame fallback.
The 800×1120 Save JPEG was verified. The camera result retained a head-size
boundary failure; the rebuilt AI preview had no failures among the currently
implemented checks. No government check, new OpenAI request, code, email or
physical print occurred. Private source/output images and full evidence are
outside Git.

The nine crop/execution regressions, 32 API/preparation workflow tests, 13
catalog/print tests, 15 background tests, 14 enhancement tests, seven skin tests,
13 regional-hotspot tests, studio DOM interactions and the end-to-end suite pass.
Synthetic tests exercise branches; the separate live run establishes actual
execution for this photo. Broader accuracy, native OFIQ coverage, identity
preservation and vendor parity remain unproven. The initial Claude review request
was acknowledged on GitHub; acknowledgement is not completed review.
