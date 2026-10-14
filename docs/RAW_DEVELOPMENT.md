# Local Canon CR2 development

`app.raw_development.decode()` develops CR2 sensor data with pinned rawpy/LibRaw
in a separate local process. It does not read the embedded camera JPEG as the
RAW master and does not fall back to Pillow when the decoder is unavailable.
JPEG/PNG and the existing HEIC decoder path remain available. Other RAW
container families and ordinary TIFF input are currently rejected. Recognised
Canon TIFF RAW markers with unsupported versions fail before Pillow is called;
TIFF-family files cannot silently become 8-bit embedded RAW previews. Export
other RAW/TIFF sources explicitly as JPEG/PNG until their source paths are
verified.

Install `requirements-raw.txt` in the Python runtime selected by `RAW_PYTHON`.
`RAW_TIMEOUT_SECONDS` controls the bounded worker wall time (default 120,
maximum 600 seconds). The worker receives no application/API/shop credentials.
No download or remote image processing happens during development.

```python
from app import raw_development as R

source = R.decode(path, R.RawSettings(wb="auto", exposure_ev=1.0, tone="neutral"))
linear_rgb = source.linear       # read-only float32, linear sRGB primaries / D65
analysis_rgb = source.preview   # read-only uint8, declared display rendering
provenance = source.report
```

Exposure is explicitly selected from -2 to +3 EV. It is applied in float after
16-bit linear decoding; values above one remain in the master. White balance is
`camera` (as-shot) or `auto` (LibRaw's whole-image estimate). LibRaw auto is not
Adobe Auto, and Camera Raw temperature/tint numbers are not rawpy coefficients.
No histogram auto-bright, noise reduction, sharpening, smoothing, shine removal
or hidden exposure selection is applied by this decoder.

LibRaw Ignore highlight mode reserves WB headroom by scaling its applied gains.
The decoder records those actual postprocess gains and explicitly reverses only
the common normalization (`1 / min(positive reported gains)`) in float. It does
not guess new per-channel coefficients. The intermediate RGB decode remains
bounded uint16: float precision cannot recover sensor or decoder samples that
were already clipped. Decoder ceiling counts and sensor black/white levels are
reported separately from post-exposure values above one.

`neutral` preview tone applies only the IEC sRGB transfer and display clipping.
`photographic` adds an explicit common-RGB highlight shoulder above linear 0.75;
it affects the preview, never the linear master. This curve is a development
option, not an Adobe Color profile, a calibrated camera look, or an automatic
exposure algorithm. The engine must record which profile it selects.

Geometry is the full visible native LibRaw output with its camera orientation
applied. Sensor sizes, margins, crop metadata, flip code and final developed
size are recorded. There is no assumption that this grid matches the in-camera
JPEG crop; downstream face analysis and crop coordinates must use the developed
grid. Customer image geometry/crops are not committed as public fixtures.

The bridge validates the CR2 v2 TIFF marker, a 96 MB input limit, at most 60 MP
sensor dimensions and 40 MP developed RGB before/after demosaic. A cross-process
lock serializes expensive decodes; the worker has CPU/output-size bounds and a
wall timeout. Native memory-address bounds are also set on Linux. On macOS,
input/dimension bounds and process isolation are used because `RLIMIT_AS` does
not provide a useful native memory limit there.

Private temporary source snapshots, float arrays and previews live beneath
`DATA_DIR` and are deleted after transport. A single read-only native frame may
be retained in memory. Its key includes source bytes, WB/exposure/tone, protocol,
worker/module code, pinned rawpy version and runtime identity. `clear_cache()`
releases it. No source-file writes occur. Original sensor bytes should remain
the immutable job source; model previews and final JPEG exports are derivatives.

Synthetic tests cover float/sub-byte precision, over-one values, normalization,
geometry limits, explicit failure, secret-free transport and cache separation.
Private RAW/JPEG comparisons supplement those tests; they do not establish an
exact Adobe match or biometric certification.

## Current engine integration and precision boundary

The processing loader intercepts the CR2 marker before Pillow. The passport
path analyses the declared preview, rotates both coordinate grids together,
resamples the actual float master onto the chosen crop, and applies the
lighting controller's smooth common-channel field to that float crop. Display
encoding then produces the sRGB8 input for the existing optional local tools
and JPEG delivery. No inverse-preview reconstruction supplies the RAW master.

The saved crop rectangle is the canonical sampling geometry for both result and
before comparison. RAW comparisons redevelop the source with the saved settings
and reject changed decoder version, settings, source hash or native geometry.
With edits off, the before and result JPEGs are byte-identical on that grid.
Small fractional float32 landmark coordinates matter: both paths reconstruct
the affine matrix from the same recorded Python-float rectangle to avoid a
one-ULP matrix difference moving a subpixel sample.

Full-frame print and free-style paths currently encode the developed native
preview before fitting/local tools. Their provenance reports this earlier
precision boundary explicitly; they do not claim float processing through those
legacy paths. Ordinary JPEG/PNG decoding and editing remain unchanged.

OFIQ receives a PNG of the declared developed RAW preview, with the sensor-file
hash recorded separately. It does not receive the CR2 container under a JPEG
label. Decoder installation/failure is a visible processing failure; it cannot
silently select an embedded JPEG or turn into a native-quality pass.
