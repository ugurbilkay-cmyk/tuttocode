# Local image enhancer

The station now has four editable starting points: Natural portrait, Difficult
lighting, Clean detail, and Small photo / larger print. They set the existing
colour/exposure controls and the new enhancer controls. They leave background,
country, layout, full-frame mode and the optional OpenAI selection unchanged.
Every operation is reapplied from the saved source, so repeated Apply does not
accumulate sharpening or exposure changes. Restore original clears the tools.

## Controls and methods

| Control | Included implementation | Default |
| --- | --- | --- |
| Low-light recovery | Retinexformer LOL-v1, smooth RGB illumination transfer | Off |
| Noise cleanup | NAFNet SIDD, model/source blend | Off |
| Detail sharpening | Thresholded, bounded Lab-lightness unsharp mask | Off |
| Skin smoothing | Landmark-guided, edge-aware texture softening with hotspot preservation | Off |
| AI enlargement | RealPLKSR natural detail, Real-ESRGAN fast smooth detail, or standard Lanczos; 2× or 4× | Off |
| AI upscale strength | Blend learned enlargement with Lanczos | 70%, used only when enlargement is selected |

Lighting predicts a field at at most 1024 pixels on its longest side, smooths and
bounds its gain to 0.5–4, then multiplies the original pixels. It does not insert
the model's reconstructed texture into the face. Denoising and enlargement do
change pixel detail; compare eyes, hair, skin texture and clothing against the
camera original. No facial reconstruction model is included. NAFNet was trained
on smartphone noise, not this shop's camera fleet, so its suitability and strength
must be checked on actual shop samples.

Skin smoothing is a separate 0–100% control. It filters fine lightness and chroma
texture inside the landmark face outline, with weaker chroma filtering, feathered
edges and strong-edge protection. Eyes, brows, lips, nose-tip boundaries,
background, high highlights and existing hotspot candidate pixels retain their
working RGB values. Regional peak lightness and bright/near-clipped percentages
are compared before/after smoothing; if they change, the affected region is
restored. The operation records the protected/edited pixel counts, mean skin
lightness change and both diagnostics. It can soften texture, but matching an
OpenAI output's appearance is not guaranteed.

These preservation checks apply to the uncompressed smoothing stage. Any
enlargement or JPEG encoding follows separately. Enhanced jobs therefore also
run the regional inspector on the final encoded JPEG and store its exact digest
and diagnostic measurements. The UK code validator also records diagnostics on
the exact deliverable JPEG, after any document-size conversion. These native-pixel diagnostics are not a proprietary
Photomatic hotspot score and do not change code-issuance permissions.

NAFNet and RealPLKSR use fixed ONNX tiles with reflected borders and 32-pixel
context on each side. No rectangular portrait is squashed into a square. Tests
check coverage, remainder strips and geometry; staff comparisons should still
look for tile boundaries on smooth surfaces. RealPLKSR's selected weights are
the MSSIM pretrain stage rather than the GAN-finetuned variant. This is a
conservative choice, not a guarantee of recovered or perfectly faithful detail.
Real-ESRGAN and SwinIR were also considered; no universal “best” claim is made.
Real-ESRGAN's compact general-x4v3 model is included as an alternative. It uses
the official normal/weak-denoise checkpoint interpolation at noise strength
0.25, then the selected upscale blend strength. Its 2× mode downsamples the
model's native 4× result. It was much faster and smoother on the small test photo;
the two models can produce different skin and edge texture, so compare them.
Choosing standard Lanczos requires no learned model. SwinIR was researched but
not integrated or benchmarked.

## Processing and evidence

Geometry, original pixel size and source eye distance are calculated from the
source before enhancement. Normal passport jobs restore a crop on a grid no
larger than the standard master and no larger than the original crop. The
existing local lighting and background tools run next. Quality checks measure
that working grid; enlargement then produces the print master. Output landmark
coordinates are converted to the actual master dimensions, while source
measurements remain unchanged. `quality_sampling_size` records the working grid
when it differs from the final master. Normal jobs record `unadjusted_sharpness`
alongside the existing post-edit sharpness metric.

Full-frame jobs restore and enlarge the native prepared source before fitting
it to the print format. Thus the 355×388 test image reaches the learned upscaler
as a 355×388 raster, rather than an already interpolated print master. The final
print master still matches the selected format, with borders when necessary.
Full-frame jobs stay “not assessed” for passport framing; low original resolution
stays a failed check even after enlargement.

The exact code JPEG is checked again by the existing issuance workflow. This
feature adds no mandatory quality gate: staff can still use the recorded
responsibility override. No enhancer performs code generation, remote upload,
email or physical printing. The final review retains processing settings, exact
code-file digest, and the existing final checks. Enhanced originals remain until
the normal retention expiry; stage evidence records model hashes, strengths,
runtime and input/output RGB digests. Unsupported ICAO/Photomatic measurements
remain untested; enhancement does not establish checker parity or certification.

## Setup

The web environment needs no Torch or ONNX dependency. Reuse the isolated
background runtime, or create one and install `requirements-background.txt`:

```sh
python3.12 -m venv .background-venv
.background-venv/bin/python -m pip install -r requirements-background.txt
python3 scripts/download_enhancement_models.py retinex nafnet plksr realesrgan
```

Set `BACKGROUND_PYTHON` to that environment's absolute interpreter path, or set
`ENHANCER_PYTHON` separately. Do not resolve the interpreter symlink to the base
Python executable. Optional `ENHANCER_MODEL_DIR` defaults to `models/enhancement`;
`ENHANCER_TIMEOUT_SECONDS` defaults to 300 per worker. Windows uses the venv's
`Scripts/python.exe`. CPU FP32 inference currently uses six threads. GPU tuning
and Windows shop benchmarks are future work.

Weights install explicitly, with fixed SHA-256 verification, and never download
during an edit. A missing, corrupt or timed-out model leaves that stage unchanged
and adds a visible warning. Background and enhancement workers share one OS lock
to limit simultaneous heavy inference. Temporary photo files are cleaned after
success or failure; the worker receives no shop/API credentials. Selecting these
tools makes no OpenAI request and has no API charge.

## Sources, licences and evaluation

Model digests and upstream revisions are in `app/enhancement_models.py`.
Retinexformer architecture is vendored at its pinned revision, with the upstream
MIT notice. NAFNet's full combined MIT/Apache-2.0 licence is retained. RealPLKSR's
MIT notice is retained. The ONNX assets are digest-pinned exports from
darktable-ai release-5.6.0; its application/converter code is not included.
The Real-ESRGAN compact architecture retains the BSD-3-Clause licence; only the
BasicSR registry import and decorator were removed to avoid loading its unrelated
framework. Both checkpoints and the adapted architecture have pinned digests.

- [Retinexformer and official LOL checkpoint](https://github.com/caiyuanhao1998/Retinexformer)
- [NAFNet and SIDD denoising](https://github.com/megvii-research/NAFNet)
- [RealPLKSR architecture](https://github.com/dslisleedh/PLKSR)
- [Real-ESRGAN compact general model and official interpolation](https://github.com/xinntao/Real-ESRGAN)
- [RealPLKSR export, MSSIM pretrain and model provenance](https://github.com/darktable-org/darktable-ai/blob/f1a46e2d3feebc917a94f14705d128316fcf8114/models/upscale-realplksr/README.md)

On this Mac, the user's deliberately difficult 355×388 image took 6.8 seconds of
inference for 50% lighting plus 25% noise cleanup. A separate native 4× upscale
at 70% strength took 25.1 seconds, producing 1420×1552 pixels. The tiny source
still has limited detail and uneven lighting; these results are exploratory
comparisons, not an industrial validation set or a promise of acceptance.
The live print-only test used native restoration, portrait matting and a 60%
RealPLKSR 2× upscale in 35.8 seconds, with the original resolution failure
retained. Its prepared source reached the upscaler at 355×388. A normal live
crop used NAFNet at 15% and sharpening at 10% with HR matting in 70.9 seconds;
its enhancement grid was 746×852, its master 1050×1200 and it recorded the
unadjusted sharpness. Master, save, original and digital print-sheet routes were
verified for both jobs. No code, physical print or OpenAI call was made.
The final live skin-smoothing checks used 60% on the small print-only photo with
Real-ESRGAN 2× (30.0 seconds total) and 70% on the normal crop (71.0 seconds with
HR matting). All five regional peaks and bright/near-clipped percentages were
identical before/after the smoothing stage on both photos; candidate highlight
pixels were unchanged. Mean skin lightness changed by −0.0242 and −0.0538 L*
respectively. The encoded JPEG inspector reported five/two bright candidate
patches and 0% all-channel near-clipping; this is a diagnostic observation, not a
passport acceptance decision. Source failures remained visible.
Private images and measurements remain under ignored `output/`.

Run `python3 tests/test_enhancement.py` for transport, geometry, no-op defaults,
tile coverage, source retention, staff workflow and no-OpenAI regressions. Real
model execution is separately verified against locally installed weights.
Run `python3 tests/test_skin.py` for protected feature pixels, texture reduction,
hotspot/near-clipping preservation across controlled skin-tone fixtures, fallback
on uncertain landmarks and final-JPEG digest checks.
