# Official native OFIQ integration

Implemented 14 October 2026. Measurements are separate from enhancement,
country decisions, trained staff responsibility and government acceptance.

## Actual build and verification

Native BSI OFIQ **1.2.0**, source commit
`d9beef8220c3829661d11e2aa3a96aef9a94a5f3`, passed **787 official conformance tests**
on this Mac ARM build: three validity tests and 784 component comparisons over
28 supplied images. Upstream tests check mapped values within 1 point and
integer mapping, not exact equality of every raw score. The C adapter also
matches all 784 mapped component values across the 28 official fixtures within
the same tolerance. Neither establishes shop decision accuracy.

Mac's upstream target omits the C wrapper. `scripts/ofiq_macos_capi.cmake` adds
the target using unchanged official C API sources, matching Linux/Windows. No
quality algorithms or canonical mappings change. `ofiq_abi_probe.cpp` compiles
structure sizes from the official headers; the worker checks these and enums.
Its compression enum is `CompressionArtifacts`, native name `NoCompressionArtifacts`.

Official bundle: https://resources.eulisa.europa.eu/research/OFIQ-Models.zip
(also ISO edition-2), 422,400,019 bytes. SHA-256:
`8ceb6cec30c95056044e9191bbf8aa26e3e29a639b40a7636a60e13063987f36`.
Canonical config SHA-256:
`e117286706d799a1e23130db01cfdff7ef36d157b22ecf68dd196052a8a8d0b3`.
Packaging compares actual models against the pinned archive, then records hashes
of models, config, libraries, notices and the build diff. No editing-time downloads.

## Image stages and staff workflow

When enabled, preparation assesses its input before local editing, prepared
master and exact `save_photo` JPEG. Source EXIF orientation is baked into a
lossless RGB PNG; native OFIQReadImage decodes BGR. Original file hash and assessed
raster-file hash are distinct. A processing input can be an accepted AI image;
it is labelled as input to that run, not automatically camera capture evidence.

**Run OFIQ on this photo** independently assesses the retained camera original,
existing master and Save export without new enhancement or OpenAI requests.
The private POST route requires a pending photo and current revision, uses the
edit lease, verifies retained bytes, and increments evidence revision. Pixels
stay unchanged. Results appear in the detailed measurements dialog. Issued and
rejected jobs remain immutable.

Final code validation assesses the actual input delivery JPEG without a second
encode for OFIQ. Every assessment retains image hash, dimensions, native return
code, all 28 metric IDs, raw/mapped values, runtime/config/model/library/adapter
hashes and timing. A queue's `final_jpeg_ofiq` is attached only when its frozen
JPEG hash matches; retained heuristic master measurements remain separate.

## Honest result states

Successful components are **measured**, not green/pass: country limits are not
calibrated. Missing components, nonfinite output, nonzero native/component codes,
mapped -1, timeout or corrupt assets are unavailable. Signed raw pose/classifier
values are legitimate. Partial/unavailable OFIQ adds a warning; it does not
change pixels or restrict existing staff responsibility overrides.

HeadSize is eye-midpoint-to-chin/image-height, not crown-to-chin. OFIQ eye distance
and mappings must not inherit vendor thresholds. Unified quality represents
biometric utility, not document acceptance. Hotspots, motion blur and detail
fidelity still require supplements. Enhanced sharpness does not prove capture focus.

## Reproducible setup

Use the [official build](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/BUILD.md)
for the pinned release/platform. On Mac append the supplied C API CMake block,
reconfigure with `DOWNLOAD_ONNX=OFF` and `DOWNLOAD_MODELS_AND_IMAGES=OFF` after
official downloads, then build/install. Compile the ABI probe against
`OFIQlib/include` and redirect its JSON to `abi-sizes.json`. Package a fresh root:

```sh
python scripts/package_ofiq_runtime.py \
  --source /path/to/OFIQ-Project \
  --libraries /path/to/native/Release/lib \
  --model-bundle /path/to/OFIQ-Models.zip \
  --abi /path/to/abi-sizes.json \
  --destination /path/to/models/ofiq
```

For Windows use its C API/core/runtime DLLs and native ABI probe; validate on the
actual machine. Mac conformance does not certify Windows. Preserve dependency
and model license notices in distributed bundles.

Set `OFIQ_ENABLED=true`, `OFIQ_RUNTIME_DIR`, `OFIQ_PYTHON` (Pillow/NumPy installed),
and `OFIQ_TIMEOUT_SECONDS` (120 default). Native inference runs in a subprocess
sharing the bounded heavy-worker slot, initializes once per batch of up to four
images, and frees native buffers. It is not yet a persistent warm worker across
jobs. API keys and shop credentials are not inherited; runtime integrity is
checked before loading native libraries.

Run `python tests/test_ofiq.py`; `NATIVE_OFIQ_TESTS=1` enables the real fixture
check when the pinned native build exists. Also run the upstream platform's
conformance script. Real Case B returned all 28 valid components on original,
master and 800x1120 Save. Native initialization was about 3 seconds; assessments
about 0.4-0.9 seconds each, excluding hashes/source encoding. Mapped sharpness
was 9/53/29, observations rather than cutoffs or production latency guarantees.
Customer images and records stay in private ignored storage.

Resources: [project](https://github.com/BSI-OFIQ/OFIQ-Project),
[C API](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/OFIQlib/include/ofiq_libc.h),
[native types](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/OFIQlib/include/ofiq_structs_c.h),
[licenses](https://github.com/BSI-OFIQ/OFIQ-Project/blob/v1.2.0/LICENSE.md).
