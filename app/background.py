"""Local matting bridge with bounded worker execution and one source-mask cache."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import numpy as np
from PIL import Image

from . import config, background_models as models


class Unavailable(RuntimeError):
    pass


_cache_lock = threading.Lock()
_cache = None


def clear_cache():
    global _cache
    with _cache_lock:
        _cache = None


def choices():
    return [dict(key=key, label=label, installed=(key == "mediapipe" or all(
        (config.BACKGROUND_MODEL_DIR / key / name).is_file() for name in models.MODELS[key]["files"])))
        for key, label in models.LABELS.items()]


@contextmanager
def _worker_slot():
    # The OS releases this cross-process lock after an app crash. Threads and
    # multiple web workers share one heavy inference slot to bound RAM usage.
    path = config.DATA_DIR / "background-worker.lock"
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0"); handle.flush()
        deadline = time.monotonic() + config.BACKGROUND_TIMEOUT_SECONDS
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise Unavailable("Background processing is busy; try again or choose a faster tool") from None
                time.sleep(.1)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _worker_environment():
    # No API/shop credentials or customer contact data are passed to the worker.
    allowed = {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
               "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1")
    return env


def matte(rgb, engine):
    """Return native-size alpha and provenance. Never silently downgrade engines."""
    global _cache
    models.validate(engine)
    if engine == "mediapipe":
        raise ValueError("MediaPipe masks come from the existing analyzer")
    specification = models.MODELS[engine]
    snapshot = config.BACKGROUND_MODEL_DIR / engine
    try:
        fingerprint = tuple((name, (snapshot/name).stat().st_mtime_ns, (snapshot/name).stat().st_size)
                            for name in specification["files"])
    except OSError:
        raise Unavailable("Selected background model needs local setup; choose another tool or install the model bundle") from None
    source_hash = hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()
    key = (str(snapshot.resolve()), engine, tuple(rgb.shape), source_hash, fingerprint)

    with _worker_slot():
        with _cache_lock:
            if _cache is not None and _cache[0] == key:
                return _cache[1].copy(), dict(_cache[2], cache_hit=True)
        with tempfile.TemporaryDirectory(prefix="tuttocode-matting-") as folder:
            folder = Path(folder)
            source, output = folder / "source.png", folder / "alpha.npy"
            Image.fromarray(rgb).save(source)
            arguments = [config.BACKGROUND_PYTHON, str(config.BASE_DIR / "scripts/background_worker.py"),
                         "--engine", engine, "--models", str(config.BACKGROUND_MODEL_DIR.resolve()),
                         "--input", str(source), "--output", str(output)]
            try:
                reply = subprocess.run(arguments, capture_output=True, timeout=config.BACKGROUND_TIMEOUT_SECONDS,
                                       env=_worker_environment(), check=False)
            except subprocess.TimeoutExpired:
                raise Unavailable("Background processing timed out; try again or choose a faster tool") from None
            except OSError:
                raise Unavailable("Background runtime needs local setup") from None
            if reply.returncode or not output.is_file():
                raise Unavailable("Background model could not run; check its local installation or choose another tool")
            try:
                alpha = np.load(output, allow_pickle=False)
                evidence = json.loads(output.with_suffix(".json").read_text())
                if alpha.shape != rgb.shape[:2] or not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1 or alpha.max() <= .01:
                    raise ValueError("Invalid matte")
                weight_name = "model.onnx" if engine == "modnet" else "model.safetensors"
                if evidence["engine"] != engine or evidence["model_sha256"] != specification["files"][weight_name]:
                    raise ValueError("Unexpected model provenance")
            except (OSError, ValueError, KeyError, TypeError, EOFError):
                raise Unavailable("Background model returned an unusable mask; background left unchanged") from None
        evidence.update(status="applied", source_rgb_sha256=source_hash, cache_hit=False,
                        alpha_sha256=hashlib.sha256(alpha.astype("<f4").tobytes()).hexdigest(),
                        version=models.VERSION, label=specification["label"])
        with _cache_lock:
            _cache = (key, alpha.copy(), evidence.copy())
        return alpha, evidence


def composite(rgb, alpha, colour):
    """Keep opaque source pixels exact; blend soft hair edges without extra blur."""
    if alpha.shape != rgb.shape[:2] or not np.isfinite(alpha).all():
        raise ValueError("Invalid background alpha")
    alpha = np.clip(alpha, 0, 1)[..., None]
    output = np.rint(rgb.astype(np.float32) * alpha + np.asarray(colour, np.float32) * (1-alpha))
    return np.clip(output, 0, 255).astype(np.uint8)
