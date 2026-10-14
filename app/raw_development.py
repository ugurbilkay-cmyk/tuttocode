"""Genuine Canon CR2 development with a bounded, isolated local decoder.

The immutable float master is linear sRGB (D65), after explicit WB/exposure and
before the display curve. Its values may exceed one. The uint8 preview is only
for existing analysis/model interfaces; it is not the working master.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np

from . import config

VERSION = "raw-development-v1"
RAWPY_VERSION = "0.27.1"
MAX_SOURCE_BYTES = 96 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SENSOR_PIXELS = 60_000_000
MAX_DIMENSION = 16_384
_cache_lock = threading.Lock()
_cache = None


class Unavailable(RuntimeError):
    """A real RAW decoder is unavailable or could not safely decode this file."""


class InvalidRaw(ValueError):
    """Input or requested development settings are unsupported."""


@dataclass(frozen=True)
class RawSettings:
    wb: str = "camera"
    exposure_ev: float = 0.0
    tone: str = "neutral"

    def __post_init__(self):
        if self.wb not in ("camera", "auto"):
            raise InvalidRaw("RAW white balance must be camera or auto")
        if isinstance(self.exposure_ev, bool):
            raise InvalidRaw("RAW exposure must be a finite value from -2 to +3 EV")
        try:
            value = float(self.exposure_ev)
        except (ValueError, TypeError):
            raise InvalidRaw("RAW exposure must be a finite value from -2 to +3 EV") from None
        if not math.isfinite(value) or not -2 <= value <= 3:
            raise InvalidRaw("RAW exposure must be a finite value from -2 to +3 EV")
        object.__setattr__(self, "exposure_ev", value)
        if self.tone not in ("neutral", "photographic"):
            raise InvalidRaw("RAW tone must be neutral or photographic")


@dataclass(frozen=True)
class DecodedSource:
    linear: np.ndarray
    preview: np.ndarray
    report: dict


def is_raw_container(header):
    """Recognise the Canon TIFF RAW family, including unsupported versions.

    Callers must reject a recognised container that fails is_raw_signature()
    before offering it to a generic image loader with embedded-JPEG support.
    """
    return (isinstance(header, (bytes, bytearray, memoryview)) and len(header) >= 12
            and bytes(header[:4]) in (b"II*\x00", b"MM\x00*")
            and bytes(header[8:10]) == b"CR")


def is_raw_signature(header):
    """Recognise the CR2 v2 marker, rather than trusting a filename extension."""
    return (isinstance(header, (bytes, bytearray, memoryview)) and len(header) >= 16
            and bytes(header[:4]) in (b"II*\x00", b"MM\x00*")
            and bytes(header[8:12]) == b"CR\x02\x00")


def check_source(source):
    """Validate the CR2 container envelope; LibRaw validates its sensor content."""
    source = Path(source)
    try:
        size = source.stat().st_size
        if not source.is_file() or size < 16 or size > MAX_SOURCE_BYTES:
            raise InvalidRaw("RAW file must be a CR2 image smaller than 96 MB")
        with source.open("rb") as handle:
            valid = is_raw_signature(handle.read(16))
    except OSError:
        raise InvalidRaw("RAW source could not be read") from None
    if not valid:
        raise InvalidRaw("The file is not a supported Canon CR2 sensor image")
    return source


def _digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def _settings(value):
    if value is None:
        return RawSettings()
    if isinstance(value, RawSettings):
        return value
    if isinstance(value, dict):
        try:
            return RawSettings(**value)
        except TypeError:
            raise InvalidRaw("Unsupported RAW development settings") from None
    raise InvalidRaw("Unsupported RAW development settings")


def render(linear, tone="neutral"):
    """Encode a preview without mutating or quantising the float working master.

    The optional photographic curve compresses highlights above linear 0.75
    using one common RGB multiplier. It is an explicit local rendering option,
    not an Adobe profile or an automatic exposure estimate.
    """
    if tone not in ("neutral", "photographic"):
        raise InvalidRaw("RAW tone must be neutral or photographic")
    data = np.asarray(linear)
    if data.ndim != 3 or data.shape[2] != 3 or not np.isfinite(data).all() or np.any(data < 0):
        raise InvalidRaw("Invalid linear RAW master")
    data = data.astype(np.float32, copy=False)
    if tone == "photographic":
        peak = data.max(axis=2)
        excess = np.maximum(peak - np.float32(.75), 0)
        target = np.where(peak > .75, .75 + excess / (1 + 4 * excess), peak)
        gain = np.divide(target, peak, out=np.ones_like(peak), where=peak > 0)
        data = data * gain[..., None]
    bounded = np.clip(data, 0, 1)
    encoded = np.where(bounded <= .0031308, 12.92 * bounded,
                       1.055 * np.power(bounded, 1 / 2.4) - .055)
    return np.rint(np.clip(encoded, 0, 1) * 255).astype(np.uint8)


def _public(result, *, cache_hit=False):
    linear, preview = result.linear.view(), result.preview.view()
    linear.setflags(write=False); preview.setflags(write=False)
    return DecodedSource(linear, preview, dict(copy.deepcopy(result.report), cache_hit=cache_hit))


def clear_cache():
    global _cache
    with _cache_lock:
        _cache = None


def _worker_environment():
    allowed = {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
               "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", DO_NOT_TRACK="1")
    return env


@contextmanager
def _worker_slot(data_dir, timeout):
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "raw-worker.lock"
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0"); handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise Unavailable("RAW development is busy; try again") from None
                time.sleep(.05)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def decode(source, settings=None, *, python=None, data_dir=None, timeout=None):
    """Develop a CR2 in an optional RAW_PYTHON runtime; never use its JPEG preview.

    Only one native frame is cached in memory, and every temporary master is
    deleted after transport. The key includes input bytes, all settings, worker
    code, protocol and pinned decoder version. Cache arrays are read-only.
    """
    global _cache
    settings = _settings(settings)
    source = check_source(source)
    source_hash = _digest(source)
    interpreter = str(python or getattr(config, "RAW_PYTHON", sys.executable))
    folder = Path(data_dir or config.DATA_DIR)
    timeout = float(timeout if timeout is not None else getattr(config, "RAW_TIMEOUT_SECONDS", 120))
    if not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise InvalidRaw("RAW timeout must be from 1 to 600 seconds")
    worker = Path(__file__).resolve().parents[1] / "scripts/raw_worker.py"
    try:
        runtime = Path(interpreter).resolve()
        runtime_fingerprint = (str(runtime), runtime.stat().st_size, runtime.stat().st_mtime_ns)
    except OSError:
        raise Unavailable("RAW runtime needs local setup; install requirements-raw.txt") from None
    key = (source_hash, json.dumps(asdict(settings), sort_keys=True), VERSION, RAWPY_VERSION,
           _digest(worker), _digest(Path(__file__)), runtime_fingerprint)
    with _worker_slot(folder, timeout):
        with _cache_lock:
            if _cache is not None and _cache[0] == key:
                saved = _cache[1]
                return _public(saved, cache_hit=True)
        with tempfile.TemporaryDirectory(prefix="raw-development-", dir=folder) as temporary:
            output = Path(temporary)
            # The worker reads a private snapshot, avoiding source replacement
            # between validation and native decoding; original files stay untouched.
            snapshot = output / "source.cr2"
            with source.open("rb") as reader, snapshot.open("wb") as writer:
                while block := reader.read(4 * 1024 * 1024):
                    writer.write(block)
            if _digest(snapshot) != source_hash:
                raise InvalidRaw("RAW source changed while preparing development")
            args = [interpreter, str(worker), "--input", str(snapshot), "--output", str(output),
                    "--settings", json.dumps(asdict(settings), sort_keys=True)]
            try:
                reply = subprocess.run(args, capture_output=True, timeout=timeout, check=False,
                                       env=dict(_worker_environment(), DATA_DIR=str(output / "runtime-data")))
            except subprocess.TimeoutExpired:
                raise Unavailable("RAW development timed out") from None
            except OSError:
                raise Unavailable("RAW runtime needs local setup; install requirements-raw.txt") from None
            if reply.returncode:
                reason = "RAW decoder is unavailable; install requirements-raw.txt in RAW_PYTHON" if reply.returncode == 3 else "RAW sensor image could not be developed"
                raise Unavailable(reason)
            try:
                linear_path, preview_path = output / "linear.npy", output / "preview.npy"
                # Bound files before numpy allocation; do not trust worker payloads.
                if linear_path.stat().st_size > MAX_PIXELS * 12 + 4096 or preview_path.stat().st_size > MAX_PIXELS * 3 + 4096:
                    raise ValueError("Oversized worker image")
                linear = np.load(linear_path, allow_pickle=False, mmap_mode="r")
                preview = np.load(preview_path, allow_pickle=False, mmap_mode="r")
                report = json.loads((output / "report.json").read_text())
                if (linear.dtype != np.float32 or linear.ndim != 3 or linear.shape[2] != 3
                        or min(linear.shape[:2]) < 1 or max(linear.shape[:2]) > MAX_DIMENSION
                        or linear.shape[0] * linear.shape[1] > MAX_PIXELS
                        or preview.dtype != np.uint8 or preview.shape != linear.shape
                        or not np.isfinite(linear).all() or linear.min() < 0
                        or report["version"] != VERSION or report["rawpy"] != RAWPY_VERSION
                        or report["source_sha256"] != source_hash or report["settings"] != asdict(settings)
                        or report["developed_size"] != [linear.shape[1], linear.shape[0]]):
                    raise ValueError("Invalid RAW worker payload")
                # Confirms that models see this master with the declared curve.
                if not np.array_equal(preview, render(linear, settings.tone)):
                    raise ValueError("RAW preview differs from declared development")
                linear = np.array(linear, copy=True)
                preview = np.array(preview, copy=True)
            except (OSError, ValueError, KeyError, TypeError, EOFError):
                raise Unavailable("RAW decoder returned an unusable image") from None
        linear.setflags(write=False); preview.setflags(write=False)
        report.update(cache_hit=False)
        result = DecodedSource(linear, preview, report)
        with _cache_lock:
            _cache = (key, result)
        return _public(result)


def _decode_native(source, settings, rawpy_module=None):
    """Worker-only implementation; injectable decoder permits synthetic tests."""
    source = check_source(source)
    settings = _settings(settings)
    if rawpy_module is None:
        try:
            import rawpy as rawpy_module
        except ImportError:
            raise Unavailable("RAW decoder dependency is missing") from None
    rawpy = rawpy_module
    if rawpy.__version__ != RAWPY_VERSION:
        raise Unavailable("RAW decoder dependency version differs from requirements-raw.txt")
    started = time.perf_counter()
    with rawpy.RawPy() as raw:
        raw.open_file(str(source))
        sizes = raw.sizes._asdict()
        for a, b, limit in (("raw_width", "raw_height", MAX_SENSOR_PIXELS), ("width", "height", MAX_PIXELS)):
            width, height = int(sizes[a]), int(sizes[b])
            if min(width, height) < 1 or max(width, height) > MAX_DIMENSION or width * height > limit:
                raise InvalidRaw("RAW sensor dimensions exceed the supported limit")
        # Separate metadata opening from unpack explicitly so the geometry
        # bounds are checked before allocating the native sensor array.
        raw.unpack()
        params = dict(use_camera_wb=settings.wb == "camera", use_auto_wb=settings.wb == "auto",
                      no_auto_bright=True, no_auto_scale=False, output_bps=16, gamma=(1, 1),
                      output_color=rawpy.ColorSpace.sRGB, highlight_mode=rawpy.HighlightMode.Ignore,
                      demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD, bright=1., adjust_maximum_thr=.75,
                      median_filter_passes=0, fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off)
        rgb16 = raw.postprocess(**params)
        if (rgb16.dtype != np.uint16 or rgb16.ndim != 3 or rgb16.shape[2] != 3
                or min(rgb16.shape[:2]) < 1 or max(rgb16.shape[:2]) > MAX_DIMENSION
                or rgb16.shape[0] * rgb16.shape[1] > MAX_PIXELS):
            raise InvalidRaw("RAW decoder returned unsupported native geometry")
        # LibRaw Ignore reserves headroom by scaling WB so its largest gain is
        # one. Its postprocess-reported gains reveal the exact common factor.
        # Undo that common normalization in float, never per-channel guesswork.
        wb = np.asarray(raw.auto_whitebalance, np.float64)
        positive = wb[wb > 0]
        if not np.isfinite(wb).all() or not positive.size or positive.min() <= 0:
            raise InvalidRaw("RAW decoder did not report valid white-balance gains")
        scale = 1. / float(positive.min())
        if not math.isfinite(scale) or not 1 / 32 <= scale <= 32:
            raise InvalidRaw("RAW white-balance normalization is unsupported")
        linear = rgb16.astype(np.float32) * np.float32(scale * 2 ** settings.exposure_ev / 65535.)
        report = dict(version=VERSION, source_sha256=_digest(source), rawpy=rawpy.__version__,
                      libraw=list(rawpy.libraw_version), settings=asdict(settings), sensor_sizes=sizes,
                      developed_size=[rgb16.shape[1], rgb16.shape[0]],
                      geometry="LibRaw full visible native RGB; metadata orientation applied by LibRaw; no JPEG crop alignment",
                      source_orientation_flip=int(sizes.get("flip", 0)),
                      applied_decoder_wb=wb.tolist(), explicit_wb_normalization_scale=scale,
                      explicit_wb_normalization_ev=float(np.log2(scale)),
                      params={k: (v.name if hasattr(v, "name") else v) for k, v in params.items()},
                      working_space="Linear sRGB primaries, D65; min-WB-normalized LibRaw development units",
                      master_dtype="float32", decoder_dtype="uint16", preview_dtype="uint8",
                      decoder_ceiling_pixels=int((rgb16.max(axis=2) == 65535).sum()),
                      decoder_zero_pixels=int((rgb16.min(axis=2) == 0).sum()),
                      master_channel_min=linear.min(axis=(0, 1)).tolist(),
                      master_channel_max=linear.max(axis=(0, 1)).tolist(),
                      master_above_one_pixels=int((linear.max(axis=2) > 1).sum()),
                      sensor_black_levels=[float(x) for x in raw.black_level_per_channel],
                      sensor_white_level=float(raw.white_level),
                      sensor_camera_white_levels=None if raw.camera_white_level_per_channel is None else list(raw.camera_white_level_per_channel),
                      display_transfer="IEC sRGB", display_tone=settings.tone,
                      smoothing=0, shine=0, sharpening=0, denoise=0,
                      limitation="LibRaw bounded uint16 RGB can already contain clipped samples. Float retains later precision, not lost sensor/decoder detail. LibRaw auto WB and this tone are not Adobe Auto/Adobe Color.",
                      development_seconds=round(time.perf_counter() - started, 3))
    return DecodedSource(linear, render(linear, settings.tone), report)
