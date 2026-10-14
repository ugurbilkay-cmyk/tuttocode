# Before / After integrity

14 October 2026. A staff comparison exposed a defect: Before was a 350×450,
quality-85 preview, while After was the full prepared JPEG (1050×1350 in the
reported example). Enlarging only the small Before raster made it look softer
and could falsely suggest detail improvement. This was not acceptable evidence
of an enhancement. Another defect labelled a successfully evaluated adaptive
profile `applied` even when its input/output pixel hashes were identical.

## Corrected comparison

New preparations render an unedited source reference onto the result's same crop,
rotation, pixel grid and source sampling path. Source rendering uses recorded
geometry and the same JPEG encoder; it never calls a face model, background model,
enhancer, OFIQ or OpenAI. The full-size Before is retained with its own byte hash,
the prepared-file hash, source-file hash, dimensions and renderer version.

Before is explicitly a **resampled processing input**, not the original camera
file. The frame may be smaller than the camera capture. In accepted OpenAI jobs,
Before refers to that accepted input before local corrections; the label makes
this distinction. A private download returns the untouched retained camera upload
byte for byte, so staff can inspect native camera detail independently. Full-frame
and freestyle references use the corresponding pad/fit geometry. An enlarged
result's reference follows the actual input sampling grid and standard resizing;
it is not presented as proof that synthetic upscaling recovered capture detail.

Older saved jobs can be corrected at viewing time: the endpoint reconstructs
Before from the retained processing source and recorded geometry. It ignores the
old thumbnail, makes no model/API request and changes neither prepared pixels nor
job revision. An available native source digest is checked before reconstruction.
Missing source/geometry or changed evidence returns unavailable instead of showing
an enlarged thumbnail as the original.

Both comparison image requests carry the page revision. Stored references check
their before/after hashes. An edit, expiry, corrupt comparison or source mismatch
cannot silently show a different saved revision. Before-load failure restores
the After image and displays an unavailable message; the toggle says Show before
or Show after, with an explicit state label. Original downloads and all comparison
routes require staff authentication.

## Correction outcome

Adaptive preparation now records changed-pixel count and mean absolute RGB change.
A completed evaluation with zero changes reports `unchanged` and says no facial
correction was selected. Failed stages remain partial/unavailable. The staff page
shows the saved profile outcome prominently, and also identifies historical jobs
whose recorded input/output hashes were identical. Background replacement is a
separate operation, so it cannot serve as evidence of facial enhancement.

The additional real-photo Recovery audit selected zero exposure, shadow lift,
learned lighting, denoising and skin finishing. With background replacement off,
its result was byte-identical to the source rendered at the same 1050×1350 crop
and grid. Face detection and native OFIQ did run, but no facial enhancement did.
The corrected comparison is therefore intentionally identical. This demonstrates
a limitation of the current selection rules; it does not establish that the
photograph is ideal or that the intended enhancement quality is achieved.

## Verification

Nine comparison tests cover identical no-edit bytes, exposure-only After edits,
fine rotation/crop reconstruction without models, full-frame matching, repair of
legacy thumbnails without mutation, revision/file integrity, missing geometry
and source-digest mismatch, private untouched downloads, and accepted-AI input
versus original-camera distinctions. Nine adaptive-controller tests include an
explicit zero-edit state. Studio DOM tests cover the toggle label and failure
display, alongside existing 33 API/workflow checks and OFIQ tests.

Further controller calibration remains necessary. This fix improves evidence
integrity and truthful reporting; it does not manufacture a stronger edit or a
passport-quality pass for a zero-edit result. Private camera images and comparison
artifacts stay outside Git history and GitHub review comments.
