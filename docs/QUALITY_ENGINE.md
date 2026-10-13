# Passport photo measurement and industrial release requirements

Updated 12 October 2026. Status: engineering specification; OFIQ integration and
industrial validation remain outstanding.

Tuttoprint must explain what it measures, why the selected document requires it,
how reliable the result is, and how staff can resolve a failure. Its approval
decision must combine measurements, document rules and recorded staff review.
OpenAI preparation is one processing stage; it cannot certify its own output.

The current application has MediaPipe/OpenCV measurements, review controls and a
final JPEG gate. Those are a prototype foundation. Passing existing tests does
not establish full ICAO coverage or measured accuracy in shop conditions.

## Proposed measurement stack

| Component | Responsibility | Limit |
|---|---|---|
| MediaPipe | Eye/face landmarks, interactive crop geometry, independent geometry comparison | Estimated landmarks and blendshapes require validation; they are not passport quality scores |
| OpenCV and image decoders | File properties, raster geometry, technical analysis and diagnostic regions | Exact pixel arithmetic does not make estimated anatomical points exact |
| Official native OFIQ | Standardized face image quality measurements | ISO quality measurements do not decide every country's acceptance rules |
| Tuttoprint document policy | Dimensions, anatomical definitions, limits, applicable age/medical allowances and issue decision | Imported Photomatic profiles must be cross-checked against current authority rules |
| Staff review | Likeness, ambiguous visibility/appearance and permitted exceptions | Must be recorded against the exact image and revision |

[MediaPipe](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker)
supplies estimated landmarks and expression coefficients. OpenCV pose recovery
using [solvePnP](https://docs.opencv.org/4.13.0/d5/d1f/calib3d_solvePnP.html)
requires camera parameters and 2D/3D correspondences; arbitrary uploaded camera
files do not establish those parameters.

[OFIQ](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/README.md)
is the C/C++ reference implementation for ISO/IEC 29794-5.
Evaluate release v1.2.0, commit
`d9beef8220c3829661d11e2aa3a96aef9a94a5f3`, using its canonical configuration,
official model bundle and supplied conformance fixtures. Its quality vector has
28 outputs: a unified measure and 27 components. Preserve individual results;
an overall score cannot cancel a failed required component.
See the [native result definitions](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/OFIQlib/include/ofiq_structs.h)
and [configuration documentation](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/doc/src/mainpage.h).

The [official Python interface](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/python/ofiq_python.md)
can wrap the native engine. The adapter must verify ABI/enums, image channel
order, buffer ownership and global/per-measure return status. Native 24-bit
images use BGR; a mislabeled RGB boundary changes colour-dependent results.
Validate dimensions before converting to native integer fields. Copy borrowed
arrays before freeing native images, and reject empty or incomplete assessments.
Keep a bounded, isolated worker warm; verify thread safety, resource limits,
timeouts and concurrency on the actual shop operating system.

## Measurement meanings must be preserved

OFIQ raw values, its mapped quality values and Photomatic's proprietary scores
are separate scales. Do not transplant a Photomatic cutoff onto an OFIQ scalar
or invent matching percentages. Keep OFIQ's canonical mapping for conformance;
version country decision limits separately.

OFIQ [HeadSize](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/OFIQlib/modules/measures/src/HeadSize.cpp)
uses eye-midpoint-to-chin distance divided by image height. The
[underlying geometry](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/OFIQlib/modules/utils/src/utils.cpp)
does not measure chin-to-crown height. A country rule requiring crown height
needs a separately defined, validated method. Hair, anatomical crown and face
bounds must not be silently treated as the same point.

OFIQ's [inter-eye geometry](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/OFIQlib/modules/landmarks/src/FaceMeasures.cpp)
and MediaPipe iris-centre distance also have different definitions. Store them
under distinct metric IDs. If independent estimates disagree beyond a validated
tolerance, request review rather than averaging them into a pass.

## Coverage of every recovered reference check

This maps all 50 XML check switches in [FIELD_GUIDE](standards/FIELD_GUIDE.md),
plus the implicit `CheckInputFormat` constructor default. It specifies intended
coverage, not completed integration or numeric equivalence. OFIQ names below
identify candidate component outputs; all proposed automatic decisions require
calibration and validation. Supplement means no direct equivalent has been
established and a separate method or explicit staff result is needed.

| Reference switch | Proposed measurement or review | Why it matters and remaining condition |
|---|---|---|
| CheckAge | Staff-entered age category | Select document allowances; appearance-based age must not grant exemptions |
| CheckArtefacts | OFIQ compression + supplement | Detect damaged/invented detail; compression alone does not cover every artefact |
| CheckBackBright | Segmented background luminance | Check required background range; do not measure the face instead |
| CheckBackColor | Segmented background colour + document policy | Apply the selected document's permitted background colours |
| CheckBackShadows | Background spatial analysis + review | Detect shadows behind the subject; uniformity is only supporting evidence |
| CheckBackUniform | OFIQ BackgroundUniformity | Detect inconsistent backdrop; validate masks around hair and shoulders |
| CheckCompressed | OFIQ CompressionArtifacts | Detect lost detail and JPEG block damage on the encoded output |
| CheckConfidence | Per-method uncertainty and disagreement | Decide whether the measurement can be trusted; no invented aggregate confidence |
| CheckContrast | OFIQ LuminanceVariance/DynamicRange | Ensure usable tonal detail; retain native definitions |
| CheckExpression | OFIQ ExpressionNeutrality + review | Apply expression rules and documented allowances |
| CheckEyeAngle | Landmark eye-line angle; OFIQ roll as corroboration | Detect tilt; eye-line angle and head roll are distinct |
| CheckEyeDistance | Named pixel eye-distance metrics | Ensure sufficient real eye detail; upscaling cannot create source resolution |
| CheckEyes | Landmarks + OFIQ EyesVisible | Establish usable eye locations; failed detection blocks dependent geometry |
| CheckEyesClear | OFIQ EyesVisible + eye-region detail supplement | Visible eyes alone do not prove adequate focus/detail |
| CheckEyesNotFacingCamera | Gaze supplement + review | Head pose does not establish where the eyes look |
| CheckEyesOpen | OFIQ EyesOpen + review | Verify eye opening under the document's age/medical rules |
| CheckFace | Independent face detection | Establish the face region before any anatomical measurement |
| CheckFaceFree | OFIQ FaceOcclusionPrevention | Check obstruction of required facial features |
| CheckFaceLarge | Validated document head/face size | Enforce maximum framing size using the required anatomical definition |
| CheckFaceNotFacingCamera | OFIQ yaw/pitch + review | Detect non-frontal presentation |
| CheckFacePositionHigh | Eye level/crown margin + document policy | Enforce vertical placement; distinguish distance from top versus bottom |
| CheckFacePositionLeft | Document centre offset + OFIQ left crop | Centre the subject and avoid clipping; these are separate criteria |
| CheckFacePositionLow | Eye level/chin/shoulder margins + policy | Enforce vertical placement and required composition |
| CheckFacePositionRight | Document centre offset + OFIQ right crop | Centre the subject and avoid clipping |
| CheckFaceSmall | Validated document head/face size | Enforce minimum framing size; do not substitute OFIQ HeadSize |
| CheckGenQuality | OFIQ UnifiedQualityScore, diagnostic only initially | Summarize biometric utility without concealing component failures |
| CheckGender | Not required for automatic passport approval | Retain reference traceability; no inferred gender gate |
| CheckGlare | Eye/glasses-region reflection supplement + review | Detect reflections obscuring eyes; generic brightness cannot establish this |
| CheckGlasses | Glasses supplement + staff review | Apply document glasses rules and permitted exceptions |
| CheckHat | OFIQ NoHeadCoverings + review | Apply headwear rules with religious/medical context |
| CheckHotspots | Segmented face highlight supplement + review | Detect local loss of texture; global exposure can miss small hotspots |
| CheckInputSize | Decoded source and output dimensions | Reject insufficient source detail or incorrect export dimensions |
| CheckInterlaced | Scan-pattern supplement | Detect combing artefacts; metadata alone is insufficient |
| CheckMotionblur | OFIQ Sharpness + directional blur supplement | General sharpness does not independently establish motion blur |
| CheckMouthClosed | OFIQ MouthClosed + review | Apply mouth position rules and permitted allowances |
| CheckMultipleFaces | Detector count + OFIQ SingleFacePresent | Reject additional faces; OFIQ dominant-face measure is not an integer count |
| CheckNoise | Noise supplement with region masks | Detect obscured detail without confusing hair/skin texture for noise |
| CheckOverexposed | OFIQ OverExposurePrevention + local highlight checks | Detect clipped bright detail |
| CheckPose | OFIQ yaw/pitch/roll | Measure orientation with separate axis limits |
| CheckRealface | Capture provenance + specialist assessment if required | A single uploaded image cannot prove liveness or lack of manipulation |
| CheckRedEyes | Eye-region colour supplement + review | Detect red-eye with calibrated colour handling |
| CheckShadowInEyes | Eye-region lighting supplement + review | Detect local eye obscuration; overall lighting is insufficient |
| CheckShadowInFace | Face-region lighting supplement + review | Detect local shadows on required features |
| CheckSharpness | OFIQ Sharpness + source detail checks | Assess focus; generated sharpening cannot prove original detail |
| CheckSkinColor | OFIQ NaturalColour + original/candidate comparison | Detect casts; generic natural colour does not establish preserved skin appearance |
| CheckSmiling | OFIQ ExpressionNeutrality + mouth review | Apply smile rules; neutral score is not an identical smile detector |
| CheckSuitable | Component policy + OFIQ utility diagnostics | Establish suitability through required checks rather than one opaque score |
| CheckSunGlases | Eye visibility/occlusion + supplement/review | Distinguish tinted lenses, glasses and shadows |
| CheckUnderexposed | OFIQ UnderExposurePrevention + local detail checks | Detect lost dark detail |
| CheckUniform | OFIQ IlluminationUniformity | Assess lighting balance; retain separate local shadow checks |
| CheckInputFormat | Decoder/format/depth checks | Enforce supported files and valid decode; recovered implicit default |

## Each result needs an evidence record

Store metric ID, human meaning and reason, anatomical/region definition, image
stage and SHA-256, coordinate system, engine/version, model/config hashes,
native return status, raw value/unit, mapped value where available, threshold
source/version, method validation version, uncertainty/quality indicators,
applicability, decision, and staff action. Retain diagnostic overlays locally.
Do not describe a model's quality scalar as statistical confidence.

Use explicit `pass`, `fail`, `review`, `unknown`, `unavailable` and
`not_applicable` states. A result can pass only when its method succeeds, returns
valid values, has an approved decision rule and is applicable. Native failure,
missing outputs, timeout, invalid masks, NaN and unvalidated required metrics
cannot become green. `not_applicable` requires a policy reason. Signed raw
angles can legitimately be negative; validate by metric definition rather than
rejecting every negative raw value.

Every red or review result must explain a practical next action: recrop, retake
with better lighting, remove prohibited glasses, obtain permitted exception
review, or resolve an unavailable engine. Borderline model estimates require
review under uncertainty limits measured on the validation set.

## UK code decision and image stages

1. Validate the original file, resolution, faces and available crop before AI.
2. Retain the original and produce a separate preparation candidate.
3. Measure that candidate independently; compare relevant facial geometry and
   visible details with the original, followed by staff likeness review.
4. Apply the selected country/document rules and authorized staff exceptions.
5. Decode and assess the actual final resized/compressed JPEG again. Issue the
   UK code only for the exact reviewed bytes, with an immutable decision record.

Photo quality and faithfulness are separate requirements. High measured quality
does not establish that generative preparation preserved every identifying
detail, or that preparation is permitted by the authority's photo rules. Record
both decisions separately. A code identifies a delivered photo; its issuance is
not government acceptance.

Child, disability, health and other exceptions must identify the particular
document allowance, affected metric, reason and reviewing staff member. They do
not grant a general bypass. Preserve failed measurements and distinguish an
approved exception from a normal pass. Technical quality failures and unavailable required assessments stay visible.
The trained-staff workflow permits explicit responsibility overrides, separately
recorded from machine-verified passes; see [LOCAL_TOOLS](LOCAL_TOOLS.md). Irish code issuance remains external.

## Evidence required for an industrial release

| Release gate | Required evidence |
|---|---|
| Engine conformance | Pinned native source/config/models; official OFIQ fixtures and documented output tolerances on supported platforms |
| Definition accuracy | Annotated anatomical points/regions and rule semantics; verified source/output coordinate transforms |
| Country validity | Current primary authority requirements for every enabled document, with review dates and conflict resolution |
| Measurement validity | Independently labelled shop-representative photos, separate calibration and held-out sets, boundary cases and reviewer disagreement |
| Decision accuracy | False acceptance, false rejection, review/unknown rates and uncertainty intervals, separately for each critical metric and the complete decision |
| Population coverage | Age groups, skin tones, hair styles, headwear, glasses, disability/medical cases and pose/lighting variation, using appropriately permitted images |
| Capture robustness | Multiple cameras, resolutions, orientations, colour profiles, compression and real shop lighting; source versus AI versus final JPEG comparisons |
| Operational reliability | Concurrency, stale review and byte changes cannot substitute a different delivered image; missing/corrupt models and worker failures remain unavailable/failed assessments, with any staff override explicitly recorded |
| Print accuracy | Physical DE100-XD measurements for every supported sheet layout; scale, borderless expansion and colour workflow validated on paper |
| Release control | Versioned licences/model hashes/policies; documented regression results and rollback; no automatic model update changing shop decisions |

Set numerical acceptance targets before the held-out evaluation. Report sample
counts and confidence intervals; avoid an unsupported single accuracy percentage.
The validation owner must approve error rates for each failure's consequences.
Acceptance by a passport authority can be tracked as an additional outcome, with
its own limitations; it cannot replace metric-level validation.

## Commercial model and dependency licences

OFIQ's [core licence](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/LICENSE.md)
requires a separate check of bundled model/dependency terms. The ten model
component licence files read from the official ISO model ZIP on 12 October 2026
contain OFIQ MIT grants and original MIT/Apache-2.0 references where applicable.
The inspected archive endpoint was
`https://standards.iso.org/iso-iec/29794/-5/ed-1/en/OFIQ-MODELS.zip`,
422,400,019 bytes. The archive's README references an ed-2 endpoint: resolve the
version and record full archive/model hashes before deployment. Inspection of
licence entries alone does not establish complete binary provenance. Preserve
all required notices in the distributed product.
The [licence audit manifest](standards/ofiq-licence-audit.json) records the
inspected component paths and licence-text hashes without distributing weights.

InsightFace's [model terms](https://github.com/deepinsight/insightface/blob/master/python-package/docs/model_zoo.md)
restrict its supplied pretrained models to non-commercial research even though
its library code is MIT. Exclude those weights from the shop product unless an
appropriate separate licence is obtained. Identity recognition is not required
to perform the proposed quality checks. Verify the actual MediaPipe model bundle
terms and all native dependencies as well as each library's code licence.

The next implementation milestone is a native OFIQ evaluation adapter plus
official conformance results. Automatic use of new components in code decisions
follows calibration and held-out validation; adding a displayed score alone is
not completion of a release gate.
