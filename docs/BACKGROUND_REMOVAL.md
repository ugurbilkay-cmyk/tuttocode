# Background-removal selection for the independent studio

Research, initial local evaluation and integration: 13 October 2026. The studio
now offers the three tested matting engines alongside the existing MediaPipe
baseline. The selection experiment is not a validated claim of best accuracy.
No paid provider was called during this evaluation. Model downloads contain no
customer images; inference uses local files with Hugging Face offline mode.

## Recommended direction

Use specialist continuous-alpha **portrait matting** for the included offline
background tool. BiRefNet HR-matting and BiRefNet-portrait are the leading
candidates to evaluate first. Keep face landmarks and document measurements as
separate tasks; neither a good matte nor a white background proves compliance.
The user's selected default is HR-matting, with portrait and MODNet alternatives.
Continue evaluating shop-photo performance and target hardware. Staff can
compare results; a manual mask-brush/refinement interface is not implemented.
Do not declare a universal winner from two examples or model-card rankings.

| Candidate | Relevant evidence | Proposed role / limitation |
|---|---|---|
| [BiRefNet HR-matting](https://huggingface.co/ZhengPeng7/BiRefNet_HR-matting) | Official MIT-labelled weights; trained at 2048 × 2048 for matting with transparency | Main high-detail candidate; CPU latency and hair edges need evaluation |
| [BiRefNet-portrait](https://huggingface.co/ZhengPeng7/BiRefNet-portrait) | Official MIT-labelled portrait weights; P3M portrait training/validation | Compare against HR on passport portraits rather than infer superiority from resolution |
| [MODNet](https://github.com/ZHKKKe/MODNet) | Official code, models and demos Apache-2.0; trimap-free portrait matting | Lightweight alternative for shop PCs; upstream-linked ONNX export tested locally |
| [BEN2](https://huggingface.co/PramaLLC/BEN2) | Open base model labelled MIT; author describes a separate full/commercial model with confidence-guided refinement | Additional challenger; do not equate open base with the vendor's full refiner |
| [withoutBG open weights](https://github.com/withoutbg/withoutbg-python) | Local ONNX bundle routes between matting and BiRefNet; composite Apache-2.0 / DINOv3 / MIT terms | Additional challenger; preserve component attribution and exact bundled licence versions |
| [ViTMatte](https://github.com/hustvl/ViTMatte), [Matting Anything](https://github.com/SHI-Labs/Matting-Anything) | Trimap-guided and interactive prompt-guided refinement approaches | Consider for staff correction; guidance quality is part of the result, not a free accuracy gain |
| [BRIA RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0) | Non-commercial weights; commercial self-host agreement or licensed API offered | Optional licensed comparison, not a free included commercial download |

The BiRefNet code's [MIT licence](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE)
and official model-card licences support the commercial shortlist. Keep the
licence, notices and model revision with any shipped bundle. The withoutBG
[composite licence](https://withoutbg.com/open-model/license) includes additional
DINOv3 attribution and use terms; its SDK licence alone is insufficient.

## Initial experiment

Two supplied photos: the deliberately difficult 355 × 388 window-background
image and the 3456 × 5184 reference portrait previously used in the Photomatic
test. There are no hand-labelled reference alpha mattes, so this experiment
measures execution and exposes edge differences for visual review, **not SAD,
MSE, failure rate or passport acceptance accuracy**. Two photos cannot establish
performance across hairstyles, ages or lighting conditions.

The candidate script uses each model's published square input/normalization,
keeps continuous alpha, resamples it back to the original image size, and composites
the original RGB onto grey, black and white. It does not reconstruct facial RGB,
warp the person, hard-threshold the outline or invent hair. Semitransparent edge
pixels are blended; an incorrect alpha can still remove a real feature. Edge
colour contamination is not corrected in this first experiment. Current studio
results retain the current sigma-2 edge blur, so visual differences reflect both
the mask and the existing compositor.

| Local model | Pinned revision | Verified weight SHA-256 | Inference size |
|---|---|---|---|
| BiRefNet HR-matting | `5d6b6f8adcb5b417c871b1d84ceaae9871355b7f` | `a5a4de698739ea5e0e8bbab28e1b293dde95092b87a442d566cbc585c53cef55` | 2048 × 2048 |
| BiRefNet-portrait | `b6561965a70070d9143fd9e558f6ca3c481510db` | `4a4eb3a5469b75f0cccaec6772c22fc30e6c12ed429c2c0ba71b43e3d8d97182` | 1024 × 1024 |

Weights and source snapshots are in ignored `output/matting-evaluation-20261013`.
Architecture code was inspected before running; custom architecture execution
uses only the explicit local snapshot. Nothing is auto-downloaded by the studio.
MODNet's [upstream ONNX instructions](https://github.com/ZHKKKe/MODNet/tree/master/onnx)
link the tested community export on Google Drive (file ID
`1cgycTQlYXpTh26gB9FTnthE7AvruV8hd`). Its local SHA-256 is
`07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9`
and size is 25,888,640 bytes. This is a local artifact digest, not an upstream
signature. `--engine modnet` selects this snapshot without `--resolution`.
The isolated matting environment uses Python 3.12, torch 2.8.0,
torchvision 0.23.0, transformers 4.51.3, timm 1.0.16, einops 0.8.1 and
kornia 0.8.0. Heavy dependencies stay outside the web runtime; optional
`requirements-background.txt` reproduces them, including ONNX Runtime 1.22.1.

Run with that isolated environment after obtaining and reviewing the pinned
snapshot and verifying the model digest:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/benchmark_background.py \
  --snapshot /absolute/path/to/reviewed/local/snapshot \
  --resolution 2048 --output /absolute/path/to/private/results \
  /absolute/path/to/photo.jpg
```

The script saves floating alpha, PNG alpha/cutout/composites and measured CPU
execution timings. Original photos, model binaries and customer outputs remain
outside Git. Preserve original source hashes, alpha/model provenance and final
file hashes when integrating the selected engine.

## Observed results

| Engine | Difficult photo inference | Reference photo inference | Initial visual observation |
|---|---:|---:|---|
| Current MediaPipe studio mask | 0.020 s | 0.039 s | Blurred hair/shoulder outline; baseline timing includes landmarks and segmentation, excludes compositing |
| MODNet ONNX | 0.201 s | 0.241 s | Fast; reference curls have softer boundaries and more visible light fringing |
| BiRefNet-portrait | 12.299 s | 13.068 s | Cleaner outline than the current baseline and more reference hair detail |
| BiRefNet HR-matting | 68.355 s | 63.088 s | Best-looking fine reference hair of these tested outputs; clean shoulder edges on the difficult image |

These are individual CPU runs without dedicated warm-up on this ARM Mac, not Windows/GPU
performance or full job latency. The BiRefNet processes used six CPU threads
and FP32 computation. MODNet used ONNX Runtime 1.22.1 CPU with six threads and
the official aspect-preserving reference-short-side-512 preprocessing (512 ×
544 / 512 × 768); continuous output is resized without first reducing alpha to
eight bits. Inference excludes loading, image preparation and PNG export.
The reference portrait was processed at its native raster size after inference.

Selection from this small test: **HR-matting for maximum detail; portrait as the
faster high-detail alternative**. MODNet remains a useful low-resource contender.
This is subjective visual evidence, not an absolute ranking of every available
tool. BEN2, withoutBG, BRIA and guided refiners were researched but not executed.
Windows speed/memory optimization and manual edge refinement remain future work.

Ignored `comparison.png` and `hair-comparison.png` show the original alongside
all four engine outputs. Small approximate inner-face alpha diagnostics were
also saved: HR's minimum was 0.99987 on the difficult image, and 1.0 on the
reference; the other evaluated masks had 1.0 in those sampled cores. This only
checks a small region, not every facial feature or semantic faithfulness.

## Criteria for choosing the production default

Evaluate fine curly/straight/light/dark/grey hair, bald heads, ears, glasses,
headwear, shoulders and dark/light clothing; include children, varied complexions,
flat and window backgrounds, shadows, low contrast, JPEG noise and normal shop
capture resolutions. Review at native resolution and actual passport print size.

Use a separate held-out set, with independently labelled mattes where possible.
Report alpha SAD/MSE and gradient/connectivity errors, annotated edge errors,
face/ear feature loss, visible halos, background remnants, manual-correction rate,
warm/cold latency and peak memory on the actual Windows shop PC. Public model
benchmarks can include different training/test data; their numbers do not form
a fair combined ranking. Pixel alpha values are not calibrated confidence scores.

Integration should retain soft hair detail, composite a document-specific plain
colour, protect reviewed opaque facial regions, and expose original/matte/result
comparison plus staff keep/remove edge corrections. Recheck the exact final
JPEG. Flag uncertainty or feature loss without turning it into a machine pass;
staff retain their recorded responsibility override. Missing high-detail models
must visibly identify any baseline fallback. OpenAI remains a separately requested
optional upgrade, never an automatic paid background-removal fallback.

## Integrated staff workflow

Under **Local photo tools**, select **Replace background**, then the tool:
Maximum detail (HR-matting, the default), Faster detail (portrait), Fast
(MODNet), or the existing basic MediaPipe mask. Apply changes uses the chosen
engine and the document's configured plain background colour. It runs for
passport crops, full-frame print jobs and freestyle templates. HR/portrait/MODNet
retain continuous alpha without the baseline's Gaussian edge blur. The source
matte is computed before tone adjustments and follows the exact existing crop
transform; head/crown crop calculations still use the existing landmark/mask
engine, keeping geometry behavior independent of the replacement tool.

The one-shot worker verifies pinned model, configuration and architecture hashes
before loading anything. Inference is explicitly offline and CPU FP32. No API
or shop credentials are passed into its environment. Private temporary source
and mask files are deleted after each invocation. A bounded single-entry
in-memory cache reuses the same source mask for subsequent lighting/crop changes,
with source/model changes invalidating it. Models are not retained in the web
process. Expiry/rejection purges clear its in-memory mask. An OS file lock serializes expensive workers across threads/web workers;
queue/execution timeouts are bounded. This also bounds background-model RAM use.

If an engine is missing, corrupt, unavailable or times out, the photo remains
usable, its background is left in place, and a visible warning identifies that
engine. The system never silently substitutes a lower-detail tool. Staff can
choose another tool and retain their responsibility override. Regular quality
checks are rerun on the result. Model revision/digest, native source and matte
hashes, processing version, input sizes, measured inference time and cache use
are stored as `background_removal` evidence. These identify processing; alpha
values and runtime timings are not passport approval scores.

## Installation

Use Python 3.12 for the separate worker environment. On macOS/Linux:

```sh
python3.12 -m venv .background-venv
.background-venv/bin/python -m pip install -r requirements-background.txt
python3 scripts/download_background_models.py hr portrait modnet
```

On Windows, create the environment with `py -3.12 -m venv .background-venv`
and install using `.background-venv\Scripts\python.exe -m pip install -r
requirements-background.txt`. Set server `BACKGROUND_PYTHON` to that Python's
absolute path; `BACKGROUND_ENGINE=hr` is the default. `BACKGROUND_MODEL_DIR`
defaults to `models/background`. `BACKGROUND_TIMEOUT_SECONDS` defaults to 300
(execution and queue each bounded separately). Restart the app after config
changes. The installer verifies fixed asset hashes and installs pinned licence
texts/notices with every model. The installer requires download access; ordinary
photo processing does not. Model binaries and the worker environment are ignored
by Git. The development preview is configured and all three bundles are installed.

Automated tests cover opaque/soft-edge composition, native crop geometry,
selection persistence, no OpenAI requests, credential-free offline workers,
source/model cache invalidation, serialization, cleanup, corrupt bundles,
invalid results, timeouts and visible availability warnings. These are integration
tests, separate from real model execution and wider accuracy calibration.

Live integration verification: all three tools were exercised through authenticated
reprocess requests on the existing demonstration jobs, including normal cropped
output and the deliberately low-resolution full-frame photo. The requested engine
was recorded as applied in every successful run; the poor source retained its
resolution failure. End-to-end times were 1.129 s (MODNet), 15.515 s (portrait),
58.533 s (HR), and 0.378 s for a repeat HR adjustment reusing the source mask.
These are local examples, not latency guarantees. Master JPEG and print-sheet
routes succeeded. No provider code, physical print, email or OpenAI request was
initiated. A first setup-path failure was shown as unavailable with the background
left unchanged, then corrected and retested.
