# Adaptive photo-quality profiles · trial v1

14 October 2026. Staff choose **Natural**, **Balanced** or **Recovery**. They do
not choose model names, model availability or a fixed set of sliders. The new
staff form defaults to Balanced; saved jobs retain their selected intent.
Original finish disables enhancement. Background replacement remains a separate
choice, with the installed high-detail local tool selected by the server.
OpenAI remains a separate optional service and is never selected by this controller.

This is a real measured-pixel controller using the existing face/lighting/noise
models. Its decision rules are **trial engineering heuristics**, not an entirely
trained quality planner, demographic classifier, calibrated ICAO verdict or
proof of Photomatic equivalence. Cropping and code rules have not been retuned.

## Execution path

1. The existing face analyzer locates the source face. The controller receives
   original-derived pixels and transformed landmarks on the working image grid.
   Passport preparation currently uses the existing unedited crop grid; full-frame
   editing uses the original grid. Analysis is normalized toward 180 interocular
   pixels with a maximum side of 1600, without increasing source resolution.
2. Locate forehead/upper-cheek regions, narrow them by the source image's own
   chroma, exclude features, dark marks, candidate highlights and staff keep areas.
   Foreground masks, when available, further narrow editable skin. Masks are
   heuristic, not semantic hair/beard ground truth. Invalid regions return
   unavailable and retain this stage's input pixels.
3. Measure scene bright-tail luminance, facial luminance spread, original skin
   lightness range and diagonal high-pass MAD on smoother skin. MAD includes
   possible texture; it does not certify sensor noise or focus. No light/dark
   demographic profile or pale skin median target is selected.
4. A globally dark scene can receive bounded linear-light exposure. Relative
   facial lighting spread can receive bounded shadow lift. A non-flat face with
   large capture-lighting disparity can request a verified Retinexformer proposal.
   Its pixels are discarded after deriving a smooth, bounded **linear-luminance**
   gain field. The same gain multiplies all three original linear RGB channels;
   it does not supply new skin detail, move anatomy or normalize complexion.
   Lightness versus skin reflectance is still ambiguous from one photo; this
   proposal and its limits need human comparison/calibration across fresh captures.
5. Lighting reserves channel headroom and retains input pixels already near
   clipping. This is a pixel-stage safeguard, not a guarantee about later JPEG
   quantization or government highlight acceptance. Final JPEG hotspots and OFIQ
   are measured separately.
6. Only sufficient residual evidence requests modest NAFNet cleanup and guided
   skin finishing. Learned denoise runs on a bounded native face ROI, not a
   reconstructed whole face. Cleanup can affect only the original eligible skin
   alpha; eyes, lips, features, candidate highlights and detected marks are excluded.
   No automatic spot repair, deblur, sharpening, enlargement or face reconstruction
   is selected in these profiles. A face ROI over 1800 pixels skips learned denoise
   to bound its worker memory, and the reason is recorded.
7. Compare the candidate with **original pixels after the same lighting field,
   before cleanup**. A regional normalized high-frequency projection floor blends
   cleanup back toward that reference when detail collapses. The controller records
   candidate energy ratios, projections, permitted blend and the verified final
   projection on this analysis grid. These are edit safeguards, not identity,
   pore, softness or passport approval metrics. Residuals include noise, and
   final JPEG/native-resolution fidelity still needs evaluation.
8. Retain source/master hashes, source versus prepared hotspot evidence,
   decision reasons, requested/applied/unavailable model provenance and timings.
   Existing OFIQ assesses original, master and the exact Save JPEG independently.
   Missing models produce partial/unavailable evidence rather than invented success.
   Existing staff responsibility overrides remain available.

## Trial correction budgets

| Profile | Global exposure cap | Relative shadow cap | Learned face-lighting cap | Noise cleanup cap | Skin finish cap | Source-detail projection floor |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Natural | 0.25 EV | 0.20 EV | 0.25 EV | 10% | 5% | 0.95 |
| Balanced | 0.50 EV | 0.35 EV | 0.50 EV | 18% | 12% | 0.90 |
| Recovery | 0.75 EV | 0.50 EV | 0.75 EV | 25% | 18% | 0.85 |

These are ceilings, not mandatory corrections or validated tolerances. Total
lighting is additionally capped at global-exposure plus relative-shadow budget.
The whole-scene bright-tail exposure reference is linear Y=0.22. Relative shadow
deadband is 0.35 EV. Lighting proposals require skin lightness range >4 L* plus
scene/face-bright-tail ratio >2.5, spread >0.6 EV, or globally dark exposure.
Cleanup need is clipped `(estimated_noise_L - 0.8) / 2.5`.

Automatic white balance is deliberately left unchanged without a reliable neutral
reference. Embedded ICC conversion is still unfinished; the existing loader's RGB
working-space assumption must be addressed before production colour calibration.
These limits are visible in saved evidence and must be calibrated on a held-out
dataset. They do not replace the user's strict Photomatic comparison targets.

## Reuse and compatibility

One lighting prediction is retained in memory per source. Another source evicts
it. Profile changes reuse the verified proposal while recomputing the bounded
gain and source-detail safeguards. Failed predictions are never cached. Cache
keys include source pixels, controller/model versions, weight location/stat and
worker interpreter; cached model hashes and original inference provenance remain
in evidence. Cache reuse is per process, not a persistent multi-worker service.

The legacy fixed tools remain callable for developer isolation tests, but the
staff form submits only an adaptive intent. Adaptive processing clears the legacy
lighting/denoise/skin/tone strengths and automatic adjustment flags, preventing
the former aggressive stack from being silently added. Trial profile v1 does not
use the prior `studio_match` recipe. Test-queue engine fingerprints include the
controller code. Customer images and measurements stay out of GitHub review.

## Validation and next work

Nine controller tests cover clean uniform complexion samples, bounded exposure,
relative lighting, failed model provenance, rejection of uncertain geometry,
source-detail rollback, cache reuse/model-texture rejection, server intent parsing
and whole-pipeline full-frame isolation. Browser DOM tests exercise three profiles,
separate background/OpenAI controls and dirty-state output protection. Existing
workflow, crop, local-tool and test-queue checks remain applicable.

Two retained poor-light camera photographs were processed through all three
profiles with genuine face-model, lighting-model and native OFIQ execution. Each
profile produced an exact export assessment. The lighting proposal was reused
across the three strengths per photo. Cleanup was not selected on these two
images because measured residuals were low. This demonstrates actual execution
and restrained transfer, **not** 200 successful independent customer comparisons.
A separate deliberately noise-degraded diagnostic verified real NAFNet execution: the
controller selected 7.76% denoise and 5.17% skin finishing, with a minimum final
normalized source-detail projection of 0.93229 against the trial 0.90 floor.
That synthetic degradation is not a new customer validation case.
No OpenAI requests, prints, codes, Photomatic checks or government submissions
were performed in these tests.

Still required: fresh varied/noisy samples; validated noise-versus-skin-texture
separation; semantic hair/beard masking; neutral-reference colour/ICC handling;
source/final landmark-drift assessment; native-resolution and final-JPEG texture
testing; stage memory/Windows performance; comparison dataset and calibrated
correction budgets. Do not call v1 industrially validated or automatically green.
