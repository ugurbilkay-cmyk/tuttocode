"""Official native OFIQ assessment bridge, independent of enhancement and policy."""
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageOps
from . import background, config

VERSION = '1.2.0'
COMMIT = 'd9beef8220c3829661d11e2aa3a96aef9a94a5f3'
MODEL_BUNDLE_SHA = '8ceb6cec30c95056044e9191bbf8aa26e3e29a639b40a7636a60e13063987f36'
CONFIG_SHA = 'e117286706d799a1e23130db01cfdff7ef36d157b22ecf68dd196052a8a8d0b3'
NAMES = ('UnifiedQualityScore BackgroundUniformity IlluminationUniformity LuminanceMean '
         'LuminanceVariance UnderExposurePrevention OverExposurePrevention DynamicRange '
         'Sharpness CompressionArtifacts NaturalColour SingleFacePresent EyesOpen MouthClosed '
         'EyesVisible MouthOcclusionPrevention FaceOcclusionPrevention InterEyeDistance HeadSize '
         'LeftwardCropOfTheFaceImage RightwardCropOfTheFaceImage MarginAboveOfTheFaceImage '
         'MarginBelowOfTheFaceImage HeadPoseYaw HeadPosePitch HeadPoseRoll ExpressionNeutrality '
         'NoHeadCoverings').split()
MEASURES = dict(zip(range(0x41, 0x5d), NAMES))
NATIVE_NAMES = dict(MEASURES)
NATIVE_NAMES.update({0x4a:'NoCompressionArtifacts', 0x54:'LeftwardCropOfFace',
    0x55:'RightwardCropOfFace', 0x56:'MarginAboveTheFace', 0x57:'MarginBelowTheFace',
    0x58:'HeadPoseYawFrontal', 0x59:'HeadPosePitchFrontal', 0x5a:'HeadPoseRollFrontal'})


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(4 * 1024 * 1024): h.update(block)
    return h.hexdigest()


def runtime_manifest(root, verify=False):
    """Verify setup before native loading. No downloads or arbitrary native search."""
    root = Path(root).resolve()
    data = json.loads((root / 'manifest.json').read_text())
    if not isinstance(data,dict): raise ValueError('Invalid OFIQ manifest')
    if data.get('version') != VERSION or data.get('source_commit') != COMMIT:
        raise ValueError('OFIQ runtime version differs from the supported release')
    if not isinstance(data.get('files'), dict) or not data['files']:
        raise ValueError('Missing OFIQ asset manifest')
    for key in ('library', 'config'):
        if data.get(key) not in data['files']: raise ValueError('Incomplete OFIQ manifest')
    if data.get('model_bundle_sha256') != MODEL_BUNDLE_SHA or data['files'][data['config']] != CONFIG_SHA:
        raise ValueError('OFIQ models or canonical mappings differ from the pinned assets')
    for name, expected in data['files'].items():
        file = (root / name).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError('Missing OFIQ runtime asset')
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError('Invalid OFIQ asset digest')
        if verify and digest(file) != expected: raise ValueError('OFIQ runtime asset failed integrity check')
    return data


def validate_measurements(items, return_code):
    """A native success is a measurement, never an uncalibrated passport pass."""
    if not isinstance(items, list) or len(items) > len(MEASURES):
        raise ValueError('Invalid OFIQ vector length')
    seen, rows = set(), []
    for item in items:
        if not isinstance(item, dict): raise ValueError('Invalid OFIQ result row')
        ident = item.get('id')
        if type(ident) is not int or ident not in MEASURES or ident in seen or item.get('name') != MEASURES[ident]:
            raise ValueError('OFIQ metric definitions differ from the pinned ABI')
        seen.add(ident)
        raw, quality, code = item.get('raw'), item.get('quality'), item.get('return_code')
        finite = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                     for v in (raw, quality))
        valid = type(return_code) is int and return_code == 0 and type(code) is int and code == 0 and finite and 0 <= quality <= 100
        rows.append(dict(item, raw=raw if finite else None, quality=quality if finite else None,
                         status='measured' if valid else 'unavailable'))
    for ident in MEASURES.keys() - seen:
        rows.append(dict(id=ident, name=MEASURES[ident], raw=None, quality=None,
                         return_code=None, status='unavailable'))
    rows.sort(key=lambda r: r['id'])
    complete = return_code == 0 and all(r['status'] == 'measured' for r in rows)
    return rows, 'completed' if complete else 'partial' if return_code == 0 else 'failed'


def assess(images):
    """Assess named encoded images in one isolated process and one native instance."""
    if not config.OFIQ_ENABLED:
        return dict(engine='OFIQ', status='off', stages=[], message='OFIQ is not enabled for this installation.')
    try:
        runtime_manifest(config.OFIQ_RUNTIME_DIR)
        with tempfile.TemporaryDirectory(prefix='tuttocode-ofiq-') as folder:
            folder = Path(folder); inputs = []
            for index, (stage, encoded) in enumerate(images.items()):
                # Decoding is bounded by the application's existing upload protection.
                with Image.open(io.BytesIO(encoded)) as im:
                    size = im.size
                if min(size) < 32 or max(size) > 32767:
                    raise ValueError('Image exceeds the safe OFIQ anatomical coordinate range')
                f = folder / f'image-{index}.bin'; f.write_bytes(encoded)
                inputs.append(dict(stage=stage, path=str(f), sha256=hashlib.sha256(encoded).hexdigest()))
            request, target = folder / 'request.json', folder / 'result.json'
            request.write_text(json.dumps(inputs))
            with background._worker_slot():
                reply = subprocess.run([config.OFIQ_PYTHON, str(config.BASE_DIR / 'scripts/ofiq_worker.py'),
                    '--runtime', str(config.OFIQ_RUNTIME_DIR.resolve()), '--inputs', str(request),
                    '--output', str(target)], env=background._worker_environment(), capture_output=True,
                    timeout=config.OFIQ_TIMEOUT_SECONDS, check=False)
            if reply.returncode or not target.is_file(): raise ValueError('Native OFIQ worker did not complete')
            result = json.loads(target.read_text())
            if not isinstance(result, dict): raise ValueError('Invalid OFIQ response')
            if result.get('version') != VERSION or result.get('source_commit') != COMMIT:
                raise ValueError('Unexpected OFIQ worker version')
            if len(result.get('stages', [])) != len(inputs): raise ValueError('Incomplete OFIQ image assessment')
            for expected, actual in zip(inputs, result['stages']):
                if not isinstance(actual,dict):raise ValueError('Invalid OFIQ stage evidence')
                if actual.get('stage') != expected['stage'] or actual.get('image_sha256') != expected['sha256']:
                    raise ValueError('OFIQ image evidence does not match this preparation')
                actual['measurements'], actual['status'] = validate_measurements(actual.get('measurements'), actual.get('return_code'))
            result['status'] = 'completed' if all(s['status'] == 'completed' for s in result['stages']) else 'partial'
            result['policy'] = 'Diagnostic quality measurements; country thresholds are not calibrated. No passport approval implied.'
            return result
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return dict(engine='OFIQ', version=VERSION, status='unavailable', stages=[],
                    message='OFIQ could not assess this photo. Check runtime assets and the native worker; no quality pass is inferred.')


def source_png(data):
    """Bake EXIF orientation for native BGR decoding; preserve the original hash separately."""
    with Image.open(io.BytesIO(data)) as im:
        if min(im.size) < 32 or max(im.size) > 32767: raise ValueError('Unsafe OFIQ source dimensions')
        im = ImageOps.exif_transpose(im).convert('RGB')
        out = io.BytesIO(); im.save(out, format='PNG')
    return out.getvalue()
