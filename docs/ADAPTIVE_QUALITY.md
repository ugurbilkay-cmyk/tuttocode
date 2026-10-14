# Adaptive photo-quality profiles · trial v2

14 October 2026. Staff choose **Natural**, **Balanced** or **Recovery**; the engine
chooses tools and strengths. New jobs default to Balanced. Original finish
disables enhancement. OpenAI remains a separate optional service.

The sequence is **analysis → lighting → highlights/shine → skin polish → local
cleaning → detail verification → background composition**. Protecting facial
regions means retaining structure and sharp detail. Smooth tonal correction may
cross eyes, brows, nose and lips; cleanup has narrower support than lighting.

## Source analysis and correction

1. The real face model supplies landmarks and foreground evidence. Analysis is
   bounded by 180 interocular pixels and a 1600-pixel maximum side, without
   increasing resolution. Invalid geometry retains input pixels.
2. `portrait_finish.analyse` measures relative highlights, chroma dilution,
   original clipping, texture residuals, source marks and feature regions.
   These are appearance heuristics, not a trained material classifier,
   demographic class or passport decision. Texture is assessed independently
   from the diagonal-MAD noise estimate.
3. Globally dark scenes can receive bounded linear exposure; relative facial
   illumination can receive shadow lift. Non-flat faces request the pinned
   Retinexformer proposal even below the old scene/face brightness gate. Only
   a smooth scalar linear-luminance field is transferred to original RGB.
   Generated model pixels never become facial detail. Profile fractions are
   applied before EV ceilings, so weak proposals also respond to strength.
4. Sparse skin samples estimate a continuous field with a median prior. Gaps
   around eyes/nose cannot punch zero-gain holes in it. A smoothstep inward
   feather spans 20% of face width. Controlled trials compared 15/20/25% widths,
   0.45/0.60/0.75-EV caps and linear versus smoothstep falloff.
5. Relative-highlight correction uses a bounded negative scalar EV field. It
   detects moderate shine below the old absolute hotspot cutoff and retains
   source geometry and texture. Existing near-clipped samples remain visible
   and recorded; reducing brightness cannot recover saturated source detail.
6. Sufficient noise evidence requests modest NAFNet cleanup on a bounded native
   face ROI. Texture appearance independently selects guided skin polish, even
   when denoising is zero. A real local blemish detector then selects small
   candidate spots for gentle repair. Source marks, feature cores and explicit
   keep areas are excluded from local cleanup. This is conservative protection,
   not reliable temporary-blemish versus identifying-mark classification.
7. Cleanup and a separate feature/mark guard compare against source pixels after
   the **same lighting and highlight fields**. Cleanup blends back when normalized
   source detail collapses. Feature projection floor is 0.98; skin floors depend
   on profile. These trial residual metrics do not certify native-resolution
   pores, identity or perfect focus. Existing blur is not claimed repaired.
8. The original-based matte is composited after facial editing. Exact final JPEG
   hotspots and native OFIQ original/master/Save assessments remain separate.
   Country checks and existing staff responsibility overrides are unchanged.

Source diagnosis, strengths, per-stage execution, actual changed pixels, model
hashes, clipping and detail rollback are recorded. Zero repaired pixels report
**unchanged**, even if the detector genuinely ran. Partial/unavailable preparation
takes precedence over a zero-edit success message.

## Trial maximum budgets

| Profile | Exposure | Relative shadow | Learned lighting | Proposal fraction | Highlight reduction | Denoise | Skin polish | Local cleaning | Skin detail floor |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Natural | 0.25 EV | 0.20 EV | 0.25 EV | 35% | 0.10 EV | 10% | 10% | 10% | 0.95 |
| Balanced | 0.50 EV | 0.35 EV | 0.50 EV | 65% | 0.20 EV | 18% | 25% | 20% | 0.90 |
| Recovery | 0.75 EV | 0.50 EV | 0.75 EV | 100% | 0.30 EV | 25% | 40% | 30% | 0.85 |

These are ceilings, not targets. Total positive lighting is also capped at the
exposure-plus-shadow budget. Bright-tail exposure reference is linear Y=0.22;
shadow deadband is 0.35 EV. Lighting proposals require skin range >4 L*. Zero or
darker proposals can remain exact no-ops. Skin polish and cleaning depend on
measured texture appearance; noise alone does not decide whether they run.
Automatic colour calibration is unchanged without a reliable neutral reference.
Embedded ICC handling remains unfinished.

The in-process lighting cache holds one source, keyed by pixels, controller/model
versions, weight location/stat and interpreter. Another source evicts it. Nested
metadata is copied so cleanup models cannot contaminate cached lighting evidence.
Failed predictions are never cached. Legacy fixed recipes cannot silently stack
with adaptive requests.

## Verification and limits

Controller tests cover clean uniform complexions, low-disparity faces, weak
proposal scaling, exact no-op proposals, clipping, continuous fields, cache
isolation, low-noise texture selection, polish-before-cleaning order, exhausted
cleanup support and adversarial cleanup against source features/marks. Separate
portrait, blemish, workflow, crop, comparison and DOM tests cover stage APIs and
honest staff outcomes. See the adaptive, portrait-finish, blemish and pipeline
status test files.

Three local camera captures ran with genuine face, lighting and blemish models;
polish and shine correction ran independently from noise. Some detector runs
found candidates but repaired zero pixels. A real high-detail background-removal
composite was tested too. Matched actual controller inputs and 100% feature crops
were inspected. Private images, records and full run evidence remain in ignored
local output folders.

Native overall OFIQ scores did **not** consistently improve; stronger edits often
reduced them. These studies establish controlled execution and visible changes,
not calibrated overall quality improvement or government acceptance. Remaining
work includes varied held-out captures, native/final-JPEG detail validation,
semantic hair/beard masks, colour/ICC handling, temporary-mark classification and
performance studies. These profiles are not industrially validated or automatically
approved. See ENGINE_REVIEW_ACTIONS.md and IMAGE_COMPARISON.md.
