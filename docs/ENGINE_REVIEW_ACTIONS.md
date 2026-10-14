# Response to the two engineering reviews

14 October 2026. The owner asked to finish OFIQ first and then return to these
reviews. OFIQ is now implemented; this record separates verified defects,
experimental suggestions and unfinished production work.

## Verified implementation facts

* The legacy Retinex worker gain is derived/applied to RGB/255 in gamma-encoded space,
  not linear-light exposure. This must be documented and separately corrected;
  simply relabelling the current strength as exposure would be inaccurate.
* `load_image` applies EXIF orientation and converts to RGB but does not perform
  an embedded ICC-to-working-sRGB transform. Metadata/working colour handling
  needs a defined path before colour-budget calibration.
* NAFNet uses 768-pixel tiles with 32 pixels of contextual halo, a 704-pixel core
  and reflected context. Its output is currently blended as a full restored
  raster. The review's concern about lost original microcontrast is applicable.
* The guided finish self-guides the current input after restoration. It does not
  yet guide from a separately retained original-detail layer. Hair/beard
  exclusion uses geometry/darkness heuristics, not a validated semantic mask.
* Laplacian variance is an uncalibrated diagnostic, sensitive to gain, contrast,
  noise, sampling and denoising. It must not become an arbitrary softness cutoff.
* The regional hotspot test combines RGB >=250 with an absolute L* >=80 and a
  relative median condition. It can miss shiny, flattened texture below those
  values, especially on darker appearance. Zero clipping is not proof of good skin.
* JPEG encoding uses a quality fallback sequence 95,92,88,84,80,75. Subsampling
  is 4:4:4 at 95/92 and 4:2:0 at lower qualities; DPI is 600. The review's general
  chroma-loss concern is valid, but this encoder does **not** always use 4:2:0.
  Encoder build/version, chosen quality and relevant options should be recorded.
* Model execution evidence exists, but a complete stage RSS/current-memory and
  warm/cold/thermal timing study does not. Old samples cannot supply that missing
  instrumentation retrospectively.

## OFIQ work completed first

Official native 1.2.0 passes 787 upstream conformance checks. The C API adapter
matches all 784 mapped fixture components within the upstream tolerance. Real
original/master/Save stages have hashes, native return codes and 28 separate
raw/mapped results. Source and export do not become interchangeable capture
evidence. No proprietary vendor threshold is transplanted. Queue snapshots join
OFIQ to the frozen JPEG only by an exact hash. See [OFIQ](OFIQ.md).

This does not fix painted skin. Case B's native Save sharpness quality of 29 is
diagnostic; it is not a newly invented pass threshold. A single unified scalar
does not settle naturalness or determine government acceptance.

## Recommended correction sequence

1. Freeze original geometry and save settings. Instrument stage duration,
   peak/current memory and cold/warm paths before choosing worker concurrency.
2. Analyze skin-only colour and local texture/noise at scale tied to eye distance.
   Retain region validity and uncertainty. Add contrast-normalized detail-energy
   ratios/correlation and re-detected landmarks on final bytes. Treat these as
   diagnostics until labelled data establishes meaningful tolerances.
3. Run Case B isolation trials: gain alone; fixed gain plus denoise 10/20/30;
   low/medium regional finish; then tone. Cache model fields so blend experiments
   do not repeat expensive inference. Compare source texture, not an OpenAI face
   prior, and include fresh sources before deciding defaults.
4. Move lighting control to an explicitly defined linear-light path and retain
   an original detail layer. Evaluate correction limits and restoration floors;
   do not use a global bright-skin target or infer exemption context from appearance.
5. Evaluate original-guided low-frequency correction and hard semantic hair/beard
   exclusions, along with matte fringe/colour-spill diagnostics. Demonstrate that
   masks and original-detail reinsertion preserve features at final JPEG scale.
6. Calibrate anatomy and country decisions independently. Keep MediaPipe crown
   proxy, OFIQ eye-to-chin size and the unidentified vendor face-height definition
   separate. Do not apply an arbitrary hair-volume offset or adjust the 30-44%
   band to make a sample green. No calibrated numeric uncertainty exists yet.
7. Only then drive automatic Normal/Medium/High correction budgets from validated
   evidence. Staff controls and code responsibility overrides remain available.
8. Benchmark the Windows queue and actual DE100XD output. A dependency on Redis
   or Celery is a proposal, not already a justified shop requirement; choose the
   simplest queue after measuring concurrency and memory needs.

## Suggestions that require evidence before implementation

The second note proposes a softness guard based on a Laplacian baseline. The
first correctly explains why this baseline conflates texture/noise/exposure.
Use the first note's separation before making an automatic guard. A heuristic
cutoff presented as validated would recreate the current quality problem.

Restoring an original high-frequency layer can also restore noise, ringing or
compression damage. A detail floor needs a region-specific noise/texture study,
not unconditional add-back. Human checks remain useful, but never substitute
for honest missing/unknown results. Neither model scores nor unchanged landmark
arrays prove likeness; output redetection and original-based comparisons are needed.

The reviews' observations of large L* lifts and changed detail are material.
They do not establish the exact painted-skin cause without isolation tests.
Case A's imbalance proxy rose from 0.73 to 1.15, despite closer regional tone:
the reference-tone comparison must not be described as a complete quality win.

These reviews do not justify adding GFPGAN, CodeFormer or a stronger face prior.
The next work should improve measurements, colour handling, cached correction
fields and preservation. Adaptive finishing, ICC conversion, linear-light gain,
semantic hair/beard masks and production deployment are not yet completed in the legacy stack.

## Subsequent adaptive-profile implementation

The staff now have Natural, Balanced and Recovery intents instead of model
selectors and fixed stacks. See [the adaptive controller](ADAPTIVE_QUALITY.md).
This trial controller uses a bounded linear-luminance gain field, asks the
verified lighting model for a proposal when capture-disparity cues warrant it,
and retains the original-derived tone image as its cleanup reference. Normalized
regional high-frequency projection limits cleanup by blending back. It avoids
the old aggressive denoise/smoothing/tone stack. One in-memory lighting proposal
is reused across profile strengths for a source; originals and exact exports
retain independent OFIQ evidence.

These are implemented engineering heuristics, not calibrated quality/identity
thresholds. Skin/texture masks are still geometric/chroma heuristics, not semantic
hair/beard segmentation. Capture brightness and skin reflectance remain ambiguous.
ICC conversion, a validated noise-versus-texture model, original/final landmark
drift assessment, stage RSS instrumentation and the advisor isolation dataset
remain unfinished. The two existing camera photographs are smoke comparisons,
not independent acceptance evidence or a completed 200-photo study.
