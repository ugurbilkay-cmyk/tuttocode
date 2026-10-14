# Lighting options · v3

14 October 2026. Staff choose one of three **lighting-only** levels:

| Option | Selected whole-photo exposure |
| --- | ---: |
| Natural | +0.25 EV |
| Balanced | +0.50 EV |
| Recovery | +0.75 EV |

New jobs default to Balanced. **Original lighting** disables this controller.
The internal keys remain `natural`, `balanced` and `recovery` for saved options
and API compatibility. These are explicit exposure choices, not an automatic
decision about a person's complexion or the correct brightness of a capture.

Polishing, denoising, shine reduction, spot cleaning, sharpening and enlargement
are off in all three options. Legacy slider stacks and automatic pixel
adjustments cannot silently combine with them. Explicit standalone local tools
remain separate APIs. Background removal is a separate staff selection and is
composited from the original-based matte after lighting.

## Exposure and local illumination

The common exposure gain covers the **whole source crop**, including the face,
neck, hair, clothing and original background. It is not multiplied by a face
oval. This prevents the earlier common face lift from leaving the neck at a
different exposure.

All three levels use the same restrained, source-relative facial lighting
field. Their only strength difference is the selected whole-photo exposure:

1. The real face model supplies landmarks and foreground evidence. Local
   analysis is bounded by 180 interocular pixels and a 1600-pixel maximum side,
   without increasing resolution.
2. Relative source illumination supplies a small shadow lift after a 0.35-EV
   deadband, capped at 0.35 EV. No fixed skin lightness is targeted.
3. Non-flat measurable faces request the pinned Retinexformer lighting proposal.
   Only a regularized scalar linear-luminance gain is taken from its result.
   Model RGB never supplies pores, eyes, facial geometry or other source detail.
4. The robust median of the measured model EV field is **subtracted**. Its
   common brightness request cannot turn into a nearly constant face lift.
   Positive residual local correction uses a 0.65 fraction and a 0.50-EV cap.
5. Only this local field uses the continuous inward face feather, extending
   across feature gaps with a measured-skin median prior. The local EV terms are
   summed and interpolated to the native working grid before adding scene EV
   and exponentiating. One common-channel linear RGB gain renders original
   source pixels; no spatial image filtering or generated replacement occurs.

Per-pixel headroom can reduce the delivered exposure below the selected level.
Existing samples with any channel at least 250 remain exact; previously
unclipped pixels do not newly cross that threshold. This retains clipping
evidence and does not recover lost highlight detail. Local correction can add
to the selected global exposure in supported regions.

Missing local geometry, uncertain foreground support or an unavailable model
does not cancel the explicit global choice. The whole-photo exposure is
retained and the run reports **partial**, with the missing local stage stated.
Requested scene EV, headroom-limited gain percentiles, changed pixels, clipping
and model provenance are recorded separately.

Automatic white balance and colour calibration remain off. A white backlit
screen can record cream because it is a separate illumination source; it does
not by itself calibrate light or colour on the subject. Source channel ratios
are preserved apart from output rounding. Embedded ICC conversion remains
unfinished.

## Saved runs and verification

Saved v2 results retain their original bytes and version-aware descriptions,
including any historical cleanup evidence. Reprocessing uses the current
lighting-only controller. New evidence has `mode=lighting_only` and version
`adaptive-quality-v3`; it does not claim that skin or feature cleanup ran.

The single-source in-process model cache is keyed by source pixels, versions,
weight location/stat and interpreter. Nested provenance is copied on access;
failed predictions are not cached.

A private local study used 38 varied studio captures, including repeated
subjects in different conditions. The earlier controller reached its Balanced
model cap on every capture while its global exposure remained zero. Controlled
trials separated common scene exposure from the median-centered local field.
The chosen +0.50-EV midpoint is a visual reference, not a calibrated automatic
exposure or biometric quality target.

Implementation verification replays all three production levels on the exact
38 saved working crops and verified real model predictions, comparing 114
outputs pixel for pixel with the reviewed scene trials. Public tests use
synthetic fixtures for scene/neck coverage, removal of common model bias,
identical local fields across strengths, disabled retouching, clipping, cache
isolation, fallback reporting and anti-stack routing. Private images, hashes
and job records remain in ignored local output.

Native OFIQ measured the exact frozen JPEGs in the study. Quality did not
consistently improve; stronger exposure is not universally better. These are
staff lighting choices under continued evaluation, not calibrated automatic
exposure, skin-colour accuracy, identity certification or document acceptance.
See ENGINE_REVIEW_ACTIONS.md and IMAGE_COMPARISON.md.
