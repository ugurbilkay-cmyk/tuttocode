# Studio clean trial preset

The Enhance step offers **Studio clean · trial**, also listed under Enhancement
options → Image enhancer → Quick starting point. Select it, review the options,
and use Apply changes to process the retained source with the local engine.

| Control | Value |
| --- | ---: |
| Retinexformer lighting recovery | 55% |
| NAFNet noise cleanup | 35% |
| Protected skin smoothing | 50% |
| Detail sharpening | 0% |
| Temperature | −4 |
| Tint | +3 |
| Colour strength | −3 |
| Shadow lift | 10% |
| Enlargement | Off |

Automatic colour/exposure correction and face-shadow softening are off to avoid
stacking them over this recipe. Advanced spot repair is off. The background,
country, crop and OpenAI selections remain separate staff choices.

This recipe was selected from three real local runs against one OpenAI reference
edit. It is a starting point for further testing, not an averaged skin/age
profile, an exact reproduction of the generative edit, or passport acceptance
evidence. The skin operation preserves its protected feature/highlight pixels;
final JPEG regional measurements are recalculated after processing. Geometry
and quality flags retain their actual results, and staff overrides are unchanged.

The new recipe does not change the default settings of newly uploaded photos or
retroactively alter existing photos. Individual comparison artifacts stay in
private output/test storage, outside Git.

## Studio reference trial

**Studio reference · trial** is the next opt-in starting point. It adds source-
guided skin lighting/contrast and regional guided texture finishing to the local
model pipeline. It does not load an OpenAI/reference image during processing.

Skin lighting/contrast derives a bounded illumination field from a guided
lightness base. Bright skin midtones and darker structures receive different
corrections; the nose receives less positive gain. Deriving the field from the
base avoids amplifying fine grain through a nonlinear per-pixel tone curve.
The facial mask feathers inward and excludes inferred neck/clothing areas.
If the background was replaced, its pure background pixels return to the
document template's neutral colour after the preceding colour adjustments.

The new texture method treats the forehead more strongly than cheeks. It keeps
eye/lip/nose feature pixels, bright candidates, detected high-contrast dark
marks and staff keep circles exact relative to this stage's input. It blends
bounded guided-filter residual corrections inside feathered facial regions.
It does not reconstruct faces or transfer reference texture. Earlier lighting
and denoising stages can change pixel colours; those are distinct operations.
JPEG encoding also changes some pixel values, so the final JPEG is inspected
again rather than claiming that its statistics are identical to an earlier
uncompressed raster.

The older bilateral mode remains the default. Unlike its conservative guard,
guided finishing does not restore a whole region merely to force equal
median-relative hotspot counts. It records genuine before/after diagnostics.
Quality flags, source retention and staff override behavior are unchanged.

The reference trial uses Retinexformer 55%, NAFNet 70%, regional guided skin
finish 100% and skin lighting/contrast 100%. Its strength percentages control
bounded blending; 100% is not an approval score or a claim that all face pixels
were replaced/filtered. Sharpening, spot repair and enlargement are off. Manual
corrections remain temperature −4, tint +3, colour strength −3 and shadow lift
10%, with automatic exposure/shadow corrections off.

Research basis: [Guided Image Filtering, original author resources](https://people.csail.mit.edu/kaiming/eccv10/index.html)
and [OpenCV guided-filter documentation](https://docs.opencv.org/4.13.0/da/d17/group__ximgproc__filters.html).
When ximgproc is absent, the implementation uses the same local-linear guided
filter equations through OpenCV box filters, with its actual method recorded.

This is still one-reference appearance tuning. It is not a demographic profile,
an averaged preset, a biometric equivalence certificate, or a Photomatic/GOV.UK
approval. Compare lighting, chroma and texture separately at matched display
resolution; preserve and review source-backed feature crops as well.
