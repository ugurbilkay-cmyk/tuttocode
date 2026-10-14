# Photo standards decoding notes

The supplied folder contains both stored photo rules and readable application
logic. These can explain the workflow and much of the checking policy. The XML
does not define how the native biometric engine calculates every image-quality
score. The records below distinguish stored values, verified code behaviour and
remaining uncertainty. They describe this installation, not a certification of
current government standards.

## Start with these records

- [Field guide](standards/FIELD_GUIDE.md): all **55 country fields**, all **98 quality
  fields**, and an index of **208 country/document profiles**.
- [Individual profiles](standards/profiles.json): every profile's stored fields,
  effective defaults, quality-profile reference, source hash and calculated mm
  ranges. Inactive limits remain visible as inactive configuration.
- [Engine inspection](standards/engine-inspection.json): selected method metadata
  from two .NET assemblies, with comparison instructions for the verified checks.
  All string literals are omitted; no supplied executable was run.
- [System requirements](SYSTEM_SPEC.md): how these findings affect Tuttoprint's own
  upload, review, print and code workflow.

## 1 Global settings and defaults

The saved settings select `United Kingdom Passport`, `Print2Hotfolder` and
`DefaultISOlevels`. The country can select its own quality file using
`bUseISOtemplate` and `ISOtemplatename`. NSW TAXI does this with `NOlevels.XML`.

The supplied `Photomatic.ControlFrame` constructor in `Bin/Photomatic.DLL`
sets `bDoAutoCrop` and `bDoICAOcheck` to true, and explicit digital requirements to
-1. Therefore their absence in older XML files means automatic processing/checking
is enabled by default. **109 profiles omit each of these two flags.** Missing is
not the same as false. The optional boolean policy fields default false unless
specified. These defaults are recorded separately from explicit XML values.
Constructor method token: `0x06000144`.

The quality-profile constructor has defaults too. `ISOlevels` token `0x06000001`
initialises `CheckInputFormat` to true even though that field is absent from all
three supplied quality XML files. Its inter-eye default is 100 pixels, overridden
to 90 by the selected default XML. Missing later biometric switches in
`NOlevels.XML` retain their constructor/CLR defaults. The profile records include
these effective values and their origins; the name NOlevels does not itself
prove that every possible check is disabled.

The saved global settings do not block Print/Save solely for a failed check. That
does not establish that all online submissions can bypass every check: output
actions, provider requirements and staff exception handling are distinct steps.
Similarly, a check requested by configuration can still be unmeasured in the
running engine; the supplied screenshot contains examples.

## 2 UK paper passport profile decoded

Source: `Packages/Countries/United Kingdom Passport.XML`.

| Stored field | Value | Meaning |
|---|---|---|
| `iCanvasWidth`, `iCanvasHeight` | 35, 45 | Photo is 35 mm wide and 45 mm high |
| `iFaceHeight` | 70 | Target height is 70% of the photo height, calculated as 31.5 mm |
| `iFaceHeightMin`, `iFaceHeightMax` | 64, 75 | Stored height range is 28.8–33.75 mm |
| `iEyesHeight` | 48 | Target eye line is 48% from the top, calculated as 21.6 mm |
| `iEyesHeightMin`, `iEyesHeightMax` | 42, 54 | Stored eye-line range is 18.9–24.3 mm from the top |
| `bUseFaceHeight`, `bUseFaceWidth` | true, false | Height framing enabled; stored width limits are not an active width-framing rule |
| `BackR`, `BackG`, `BackB` | 228, 228, 228 | Preferred neutral background channel values |
| `Back*min`, `Back*max` | 192, 255 | Stored per-channel acceptable background range |
| `DefaultPrintTemplateName` | 35x45 6-up.XML | Named default sheet layout; not the individual photo dimensions |
| `bUseOverlay` | true | Show the named UK guide during review; the guide is not photo content |
| `bUseISOtemplate` | false | Use globally selected quality profile |

The range conversion is simply `photo_height_mm × stored_percent / 100`.
Decoding those arithmetic values does not establish that the engine's head/crown
landmarks match our AI measurements, or that historical rounded template values
are today's official tolerances.

## 3 UK online renewal is a different profile

Source: `Packages/Countries/United Kingdom Online Renewal.XML`, matching the
selected document in the supplied screenshots.

| Property | Stored rule |
|---|---|
| Photo geometry | 50 × 70 mm, format 5:7 |
| Digital JPEG dimensions | 800 × 1120 pixels |
| Digital file size | 50–10000 legacy KB; exact byte-unit conversion still needs tracing |
| Head target | 36%, calculated as 25.2 mm |
| Head range | 30–44%, calculated as 21–30.8 mm |
| Eye target | 32% from top, calculated as 22.4 mm |
| Eye range | 24–50% from top, calculated as 16.8–35 mm |
| Background | Preferred RGB 248; per-channel range 192–255 |
| Geometry mode | Height on; width off |
| Overlay | Off, even though an overlay filename remains stored |

The separate `UK online.XML` file specifies **800 × 1150**, not 800 × 1120.
The selector must preserve these as separate profiles. A default, an inactive
setting and a currently selected setting must not be conflated.

## 4 Quality thresholds and actual comparison behaviour

`DefaultISOlevels.XML` has **50 check switches** within its 98 fields. Some
thresholds have physical units; most refer to legacy scores.

| Check | Stored value | Verified interpretation |
|---|---|---|
| Input width/height | 300 × 400 | Pixel dimensions; inspected `GeometryCheck7` returns early below these minima |
| Eye angle | MaxAngle = 6 | Accepted within -6 to +6 degrees when enabled |
| Eye distance | MineyeDistance = 90 | At least 90 pixels when enabled; measurements belong to the score's image space |
| Confidence | MinConfidence = 30 | Legacy confidence score must be at least 30 when enabled |
| General quality | MinGenQuality = 30 | Legacy general score must be at least 30 when enabled |
| Eyes open | MinEyesOpen = 39 | Legacy score must be at least 39, or equal -1 in the inspected comparator |
| Sharpness | MinSharpness = 18 | Legacy score must be at least 18; this is not Laplacian variance 18 |
| Noise | MinNoise = 18 | Legacy score must be at least 18; this is not a directly transferable AI/noise unit |
| Overexposure/hotspots | Minimum = 36 | Legacy quality scores, rather than luminance or percent of bright pixels |
| Face large/small | Minimum = 30 | Geometry scores compared against minima when their switches are enabled |

### Verified quality comparator

`Photomatic.Photo.CheckICAOlevelsNoGeometry`, token `0x060000eb`, reads each
supported check switch and compares its associated measurement with the configured
minimum. Its basic pattern is:

```text
if check_enabled and measured_score < configured_minimum:
    return false
```

Some biometric checks add a sentinel exception:

```text
if check_enabled and measured_score < configured_minimum and measured_score != -1:
    return false
```

The inspected routine skips -1 for eye clarity, eyes open, face unobstructed,
glare, suitability, sunglasses/dark eye area, mouth closed, smile and headwear.
Its angle comparison also has a -1 exception. It does not apply this exception
to all checks: confidence, general quality, eye distance, image-quality and
lighting comparisons have different branches. A -1 result is **not a measured
pass**, even where the old routine does not fail it.

### Verified geometry comparator

`Photomatic.Photo.CheckICAOlevelsGeometry`, token `0x060000ec`, conditionally
checks the face-large, face-small, high, low, left and right scores, then angle and
eye distance. Equality with a minimum passes; an angle at either configured
boundary passes. It returns true only after all its enabled comparisons pass.

This is one layer of the system. Geometry measurement routines generate those
scores; the caller decides which result to display and whether an output is
allowed. `CheckExpression`, `CheckPose` and other switches present in the XML are
not all read by the inspected no-geometry comparator. Their absence from that
routine does not prove they are unused throughout the application.

## 5 Crop logic and an important Irish difference

`AutoCrop7` and `AutoCrop7N` in `Photomatic.DLL` test `bUseFaceWidth` before
`bUseFaceHeight`. Their inspected branches show:

```text
if use_face_width:
    crop_width = measured_face_width × 100 / target_face_width_percent
    crop_height follows the format ratio
else if use_face_height:
    crop_height = measured_face_height × 100 / target_face_height_percent
    crop_width follows the format ratio
```

The vertical placement then uses the configured eye percentage and eye position.
Integer conversions occur in the original logic; exact rounding and boundary
handling still need to be traced for equivalent pixel results.

**Ireland Passport online and Ireland Public Services Card online enable both
width and height.** In these inspected crop routines width therefore takes
precedence. The current Tuttoprint implementation chooses height first, so it
does not yet reproduce that behaviour. The geometry-check routine can evaluate
both dimensions separately from the crop-selection precedence.

These findings are method-specific: the installed program has several crop
variants, and the exact active path needs a complete caller trace or a controlled
input/output comparison. Method tokens are `0x060000cf` and `0x060000d0`.

## 6 Background checks are separate from biometric scores

`PhotoMatic7.Form1.StartBackgroundCheck` references the selected country's
background min/max channels, the four background-region measurements and the
enabled background quality thresholds. Its dependencies include
`DPS_Library.MeasureBackground.Measure` and `FloodFill`. The supplied screenshot's
too-bright, too-dark, uniform and shadow indicators correspond to this separate
background workflow.

The small `Photomatic.Photo.CheckBackground` method simply returns true in this
assembly. **That does not mean the software never checks backgrounds**:
`StartBackgroundCheck` and the substantial `BackgroundCheck7` routines are also
present. A method name alone cannot establish the application's behaviour.
Their formulas, region selection and aggregation are further decoding work.

## 7 What is inside the native engine

The inspected `ImageQualityCheck7` routines call `LocateG6Class.FindFaceAuto`,
`FindHead`, `CheckFaceEx`, `SetQualityMetrics` and `GetQualityEx`, and retrieve
face/eye landmarks through FacePosition objects. `Photomatic.DLL` references
`Interop.FaceItLocate` and `Interop.FaceItMedia`; the corresponding FaceIt DLLs
are native Windows libraries.

The managed wrapper exposes control flow, metric consumption and some score
aggregation. It does not reveal the native sharpness, motion-blur, noise, glare
or biometric score formulas. Exact native equivalents would need deeper binary
analysis and/or paired-output calibration. Tuttoprint can implement and test its
own measurements while preserving document rules and operator workflow; it
must not label an unrelated measurement as a decoded old-engine score.

The executable also contains server-check paths. Their presence establishes
that the application can have more than one analysis route, not which route was
active in the user's session. Static inspection cannot establish a remote
service's internal algorithm or its present API.

## 8 Country exceptions to review individually

| Profile or setting | Why it matters |
|---|---|
| NSW TAXI | Uses `NOlevels.XML`; its checking policy differs from the global default |
| Australia Passport DFAT | Explicitly blocks the background editor |
| Ten profiles with `bForceCutmarks` | Country policy can override a sheet's default cut-mark choice |
| Irish online profiles | Both geometry modes enabled; width-first crop in the inspected routines |
| Free-style profiles | No enabled width/height target; cannot inherit standard biometric crop assumptions |
| France ANTS and Germany driving licence | Additional submission workflow separate from photo generation |
| Missing auto-crop/check fields | Verified constructor defaults apply, not an invented false value |
| Stored specification URLs | Several unrelated profiles point to Dutch guidance; a saved URL is not proof of authoritative rules for that country |

For each of the 208 profiles, review the stored fields, default origin, enabled
geometry, chosen quality profile, digital deliverable and print layout. Record
current-rule verification and paired-output results separately from decoding.

## Repeat the inspection

The standards decoder uses Python's standard library and the verified inspection
record committed alongside it. For the same binary, run:

```sh
python3 scripts/decode_reference_standards.py /path/to/Photomatic7
```

The optional static assembly inspector needs `dnfile` and `dncil` in an inspection
environment; these are not dependencies of the running studio. For a different
binary, regenerate this record first, then run the decoder:

```sh
python3 scripts/inspect_reference_engine.py /path/to/Photomatic7
```

`--full-il` includes all selected method instructions, with every string literal
still redacted. The default output keeps compact references plus the inspected
constructor/comparison instructions. Both tools read the supplied installation;
neither launches it nor changes its settings. The original hashes let a later
inspection establish whether the same binaries/templates were examined.

## Remaining decoding work

1. Trace the active crop/check call chain and every quality switch through the
   application, including asynchronous and server-assisted paths.
2. Decode exact geometry landmark definitions, crop rounding, bounds handling,
   score aggregation and background measurement formulas.
3. Trace digital export byte-size units/encoding and print compliance enum values.
4. Compare paired original/processed jobs, including Irish width-first framing,
   thresholds at boundaries, unmeasured results and correction/recheck behaviour.
5. Validate current country rules independently and implement the verified policy
   in Tuttoprint's own engine. Configurations, algorithms and government acceptance
   are separate things to establish.
