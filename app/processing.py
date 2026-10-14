"""Passport photo processing: face analysis, HMPO crop, compliance checks.

Auto enhance: colour/exposure, face-shadow softening, background evening or
replacement, with optional learned restoration. Geometry is measured from the
source; staff compare the enhanced detail before output.
"""
from __future__ import annotations

import io
import hashlib
import threading
import time
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import config, photomatic, local_adjustments, background, background_models, enhancement, skin, hotspots, blemishes, ofiq, adaptive_quality, raw_development

try:  # iPhone HEIC uploads
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

# Output: 35x45mm ratio. 1050x1350 px is well above HMPO minimum (600x750).
OUT_W, OUT_H = 1050, 1350
MIN_SRC_W, MIN_SRC_H = 600, 750

# Head (chin to crown) as fraction of photo height. UK print spec 29-34mm of 45mm.
HEAD_TARGET = 0.70
HEAD_MIN, HEAD_MAX = 29 / 45, 34 / 45
CROWN_MARGIN = 0.09  # space above crown, fraction of height

# Face mesh landmark indices (MediaPipe 478-point model).
L_IRIS, R_IRIS = 468, 473
CHIN, FOREHEAD, NOSE = 152, 10, 1
FACE_L, FACE_R = 234, 454
LEFT_EYE_RING = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
RIGHT_EYE_RING = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]


@dataclass
class FaceData:
    points: np.ndarray            # (478, 2) pixel coordinates
    blendshapes: dict[str, float]


@dataclass
class Analysis:
    faces: list[FaceData]
    person_mask: np.ndarray | None  # float 0..1, same HxW as image
    evidence: dict = field(default_factory=dict)


@dataclass
class Check:
    key: str
    label: str
    status: str  # pass | warn | fail
    detail: str = ""


@dataclass
class Result:
    ok: bool
    checks: list[Check] = field(default_factory=list)
    jpeg: bytes | None = None
    preview_jpeg: bytes | None = None
    before_jpeg: bytes | None = None
    measurements: dict = field(default_factory=dict)
    cleaner_assets: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "ok": self.ok,
            "checks": [c.__dict__ for c in self.checks],
            "measurements": self.measurements,
        }


class MediaPipeAnalyzer:
    """Face landmarks + person segmentation using MediaPipe Tasks models.

    Models (download with scripts/download_models.sh):
      models/face_landmarker.task
      models/selfie_segmenter.tflite
    """

    def __init__(self, model_dir=config.MODEL_DIR):
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions

        self.mp = mp
        self.lock = threading.RLock()
        lm_path = model_dir / "face_landmarker.task"
        seg_path = model_dir / "selfie_segmenter.tflite"
        if not lm_path.exists():
            raise RuntimeError(f"Missing {lm_path}. Run scripts/download_models.sh")
        self.model_sha256 = hashlib.sha256(lm_path.read_bytes()).hexdigest()
        self.landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(lm_path)),
                num_faces=2,
                output_face_blendshapes=True,
            )
        )
        self.segmenter = None
        self.segmentation_sha256 = None
        if seg_path.exists():
            self.segmentation_sha256 = hashlib.sha256(seg_path.read_bytes()).hexdigest()
            self.segmenter = vision.ImageSegmenter.create_from_options(
                vision.ImageSegmenterOptions(
                    base_options=BaseOptions(model_asset_path=str(seg_path)),
                    output_confidence_masks=True,
                )
            )

    def analyze(self, rgb: np.ndarray) -> Analysis:
        # The shared MediaPipe Tasks instance must not process two jobs at once.
        with self.lock:
            return self._analyze(rgb)

    def _analyze(self, rgb: np.ndarray) -> Analysis:
        started = time.perf_counter()
        h, w = rgb.shape[:2]
        img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self.landmarker.detect(img)
        faces = []
        for i, lms in enumerate(res.face_landmarks):
            pts = np.array([[p.x * w, p.y * h] for p in lms], dtype=np.float32)
            bs = {}
            if res.face_blendshapes and i < len(res.face_blendshapes):
                bs = {c.category_name: float(c.score) for c in res.face_blendshapes[i]}
            faces.append(FaceData(pts, bs))
        mask = None
        if self.segmenter is not None:
            seg = self.segmenter.segment(img)
            if seg.confidence_masks:
                mask = np.asarray(seg.confidence_masks[-1].numpy_view(), dtype=np.float32)
                if mask.ndim == 3:
                    mask = mask[..., 0]
        return Analysis(faces, mask, {
            'engine':'mediapipe', 'method':'MediaPipe FaceLandmarker', 'status':'completed',
            'model_sha256':self.model_sha256, 'face_count':len(faces),
            'landmark_counts':[len(face.points) for face in faces],
            'input_size':[w,h], 'inference_seconds':round(time.perf_counter()-started,4),
            'segmentation':{'status':'completed' if mask is not None else 'unavailable',
                            'model_sha256':self.segmentation_sha256},
        })


_analyzer = None


def get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = MediaPipeAnalyzer()
    return _analyzer


def load_source(data: bytes, raw_settings=None):
    """Return model RGB, optional float RAW master, and development provenance.

    CR2 must be intercepted before Pillow, which can otherwise silently expose
    only the camera's embedded JPEG. Ordinary image decoding stays unchanged.
    """
    if raw_development.is_raw_container(data[:16]):
        if not raw_development.is_raw_signature(data[:16]):
            raise raw_development.InvalidRaw('Unsupported Canon RAW version. Use a supported CR2, JPEG or PNG.')
        if len(data) > getattr(config, 'MAX_RAW_UPLOAD_MB', 64) * 1024 * 1024:
            raise raw_development.InvalidRaw('RAW image exceeds the upload limit')
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='raw-source-', dir=config.DATA_DIR) as folder:
            source = Path(folder) / 'source.cr2'
            source.write_bytes(data)
            developed = raw_development.decode(source, raw_settings)
        return developed.preview, developed.linear, developed.report
    im = Image.open(io.BytesIO(data))
    if im.format == 'TIFF':
        # Pillow can expose a TIFF-based camera RAW's thumbnail as if it were
        # an ordinary image. Until TIFF/other RAW families have a verified
        # source path, require a supported CR2 or an explicitly rendered image.
        im.close()
        raise raw_development.InvalidRaw('TIFF and other camera RAW formats are not supported yet. Use CR2, JPEG or PNG.')
    im = ImageOps.exif_transpose(im).convert("RGB")
    return np.asarray(im), None, None


def load_image(data: bytes, raw_settings=None) -> np.ndarray:
    return load_source(data, raw_settings)[0]


def _encode_jpeg(rgb: np.ndarray, min_kb=60, max_kb=9500) -> bytes:
    im = Image.fromarray(rgb)
    for q in (95, 92, 88, 84, 80, 75):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, subsampling=0 if q >= 92 else 2, dpi=(600, 600))
        size = buf.tell() / 1024
        if size <= max_kb:
            if size < min_kb:  # tiny files only happen on near-blank images
                break
            return buf.getvalue()
    return buf.getvalue()


def _small_jpeg(rgb, bounds=(350, 450), quality=85):
    buf = io.BytesIO()
    im = Image.fromarray(rgb)
    im.thumbnail(bounds, Image.LANCZOS)
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _lum(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32) * (100 / 255)


# --- auto colour & lighting ----------------------------------------------
# Whole-image corrections only (white balance, exposure, highlight roll-off),
# the same adjustments a photo lab makes. Nothing local is done to the face.
BG_TARGET = 0.86      # target background brightness (sRGB 0..1), light grey/cream
MAX_GAIN, MIN_GAIN = 3.0, 0.6   # exposure limits (about +1.6 / -0.7 stop)


def _to_lin(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _shoulder(x, knee=0.85):
    """Soft highlight roll-off so bright areas don't clip to pure white."""
    over = np.maximum(x - knee, 0)
    span = 1 - knee
    return np.where(x > knee, knee + span * (1 - np.exp(-over / span)), x)


def enhance(rgb: np.ndarray, person_mask, face_box, even_bg=False, adjust=True):
    """Returns (adjusted_rgb, notes). face_box = (x0, y0, x1, y1) in pixels."""
    notes = []
    h, w = rgb.shape[:2]
    small_scale = 800 / max(h, w)
    img = rgb.astype(np.float32) / 255
    lin = _to_lin(img)

    if person_mask is None:
        return rgb, ["No background reference — colour left as taken"]
    bg = person_mask < 0.15
    # ignore very dark / clipped pixels when sampling background
    y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    ref = bg & (y > 0.02) & (lin.max(axis=2) < 0.995)
    if ref.sum() < max(2000, 0.02 * h * w):
        return rgb, ["Background too small to use as reference — colour left as taken"]

    if adjust:
        # 1. white balance: make the (plain, light) background neutral
        bg_rgb = np.median(lin[ref], axis=0)
        gains = bg_rgb.mean() / np.maximum(bg_rgb, 1e-4)
        gains = np.clip(gains, 0.6, 1.7)
        if np.abs(gains - 1).max() > 0.02:
            lin = lin * gains
            notes.append("colour cast removed")

        # 2. exposure: bring the background to a light, even level
        y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        bg_y = float(np.median(y[ref]))
        target_lin = float(_to_lin(np.float32(BG_TARGET)))
        gain = float(np.clip(target_lin / max(bg_y, 1e-4), MIN_GAIN, MAX_GAIN))
        # never push the face into clipping
        x0, y0, x1, y1 = [int(v) for v in face_box]
        face_y = y[max(y0, 0):max(y1, 1), max(x0, 0):max(x1, 1)]
        if face_y.size:
            p99 = float(np.percentile(face_y, 95))  # ignore eye whites / speculars
            if p99 * gain > 0.92:
                gain = max(min(gain, 0.92 / max(p99, 1e-4)), MIN_GAIN)
        if abs(gain - 1) > 0.04:
            lin = lin * gain
            stops = np.log2(gain)
            notes.append(f"exposure {'+' if stops > 0 else ''}{stops:.1f} stop")

        # 3. highlight roll-off
        if (lin > 0.85).mean() > 0.001:
            lin = _shoulder(lin)
            notes.append("highlights softened")

        out = _to_srgb(lin)
    else:
        out = img.copy()

    # 4. optional: even out the background only (face/body untouched)
    if even_bg:
        m = cv2.GaussianBlur(person_mask.astype(np.float32), (0, 0), 3)
        bgw = np.clip((0.35 - m) / 0.25, 0, 1)[..., None]  # 1 = background, 0 = person
        sw, sh = int(w * small_scale), int(h * small_scale)
        lum = cv2.cvtColor((out * 255).astype(np.uint8), cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
        lum_s = cv2.resize(lum, (sw, sh), interpolation=cv2.INTER_AREA)
        bg_s = cv2.resize(bgw[..., 0], (sw, sh)) > 0.5
        # fill person area with nearby background, then blur → smooth light field
        fill = cv2.inpaint(lum_s.astype(np.uint8), (~bg_s).astype(np.uint8) * 255, 15, cv2.INPAINT_TELEA)
        field = cv2.GaussianBlur(fill.astype(np.float32), (0, 0), sw / 12)
        field = cv2.resize(field, (w, h), interpolation=cv2.INTER_LINEAR)
        target = np.median(field[bgw[..., 0] > 0.5]) if (bgw > 0.5).any() else field.mean()
        corr = np.clip(target / np.maximum(field, 1), 0.7, 1.6)[..., None]
        out = out * (1 - bgw) + np.clip(out * corr, 0, 1) * bgw
        notes.append("background evened")

    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), notes


def soften_face_shadows(rgb, face_box, person_mask=None, strength=1.0):
    """Evens out large-scale light across the face (e.g. one side darker).

    Only the low-frequency lighting is changed; fine detail (features, skin
    texture, eyes) is kept, so the face itself is not reshaped. The gain is
    applied in linear light to all channels so skin colour stays natural.
    Returns (rgb, amount) where amount is the max brightening applied (0 = none).
    """
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = face_box
    fw, fh = x1 - x0, y1 - y0
    if fw < 40 or fh < 40:
        return rgb, 0.0
    cx = (x0 + x1) / 2
    lin = _to_lin(rgb.astype(np.float32) / 255)
    Y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)

    # face oval (forehead down to the neck), limited to the person, feathered
    region = np.zeros((h, w), np.float32)
    cy = (y0 + y1) / 2 + fh * 0.08
    cv2.ellipse(region, (int(cx), int(cy)), (int(fw * 0.55), int(fh * 0.66)), 0, 0, 360, 1.0, -1)
    # skin only: colour close to the centre of the face (excludes clothes, hair, background)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    core = lab[int(y0 + fh * 0.45):int(y0 + fh * 0.7), int(cx - fw * 0.15):int(cx + fw * 0.15)]
    if core.size:
        ref_ab = np.median(core[..., 1:].reshape(-1, 2), axis=0)
        d2 = ((lab[..., 1:] - ref_ab) ** 2).sum(-1)
        skin = np.exp(-d2 / (2 * 14.0 ** 2)).astype(np.float32)
        region *= cv2.GaussianBlur(skin, (0, 0), max(fw * 0.02, 2))
    region[int(min(y1 + fh * 0.25, h)):] = 0
    # skin only: colour close to the centre of the face (excludes clothes, hair, background)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    core = lab[int(y0 + fh * 0.45):int(y0 + fh * 0.7), int(cx - fw * 0.15):int(cx + fw * 0.15)]
    if core.size:
        ref_ab = np.median(core[..., 1:].reshape(-1, 2), axis=0)
        d2 = ((lab[..., 1:] - ref_ab) ** 2).sum(-1)
        skin = np.exp(-d2 / (2 * 14.0 ** 2)).astype(np.float32)
        region *= cv2.GaussianBlur(skin, (0, 0), max(fw * 0.02, 2))
    region[int(min(y1 + fh * 0.25, h)):] = 0
    region = cv2.GaussianBlur(region, (0, 0), max(fw * 0.03, 2))
    if person_mask is not None:  # keep the correction off the background (no halo)
        inside = (person_mask > 0.5).astype(np.uint8)
        k = max(int(fw * 0.04), 3)
        inside = cv2.erode(inside, np.ones((k, k), np.uint8)).astype(np.float32)
        region *= cv2.GaussianBlur(inside, (0, 0), k / 2)

    # large-scale light inside the face (normalised blur: background doesn't leak in)
    sigma = max(fw / 14, 3)
    num = cv2.GaussianBlur(Y * region, (0, 0), sigma)
    den = cv2.GaussianBlur(region, (0, 0), sigma)
    illum = num / np.maximum(den, 1e-3)

    # mirror around the face centre and aim for the brighter side
    mirrored = np.fliplr(illum)
    shift = int(round(2 * cx - w + 1))
    mirrored = cv2.warpAffine(mirrored, np.float32([[1, 0, shift], [0, 1, 0]]), (w, h),
                              borderMode=cv2.BORDER_REPLICATE)
    # per-row reference level (bright side of each row), so the middle isn't left darker
    rows = np.zeros(h, np.float32)
    inside = region > 0.5
    for yy in range(max(int(y0), 0), min(int(y1 + fh * 0.3), h)):
        vals = illum[yy][inside[yy]]
        if vals.size > 10:
            rows[yy] = np.percentile(vals, 90)
    rows = cv2.GaussianBlur(rows[:, None], (0, 0), sigma)[:, 0]
    target = np.maximum(np.maximum(illum, mirrored), 0.94 * rows[:, None])
    gain = 1 + strength * (target / np.maximum(illum, 1e-4) - 1)
    gain = cv2.GaussianBlur(np.clip(gain, 1.0, 3.0), (0, 0), sigma / 2)
    gain = 1 + (gain - 1) * region

    amount = float((gain - 1).max())
    if amount < 0.05:
        return rgb, 0.0
    out = _to_srgb(_shoulder(lin * gain[..., None]))
    return (out * 255 + 0.5).astype(np.uint8), amount


def replace_background(rgb, mask, colour=(228, 228, 228)):
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 2)[..., None]
    plain = np.empty_like(rgb)
    plain[:] = colour
    return (rgb * soft + plain * (1 - soft)).astype(np.uint8)


def _background_mask(rgb, baseline, engine, measurements, checks):
    """Select an explicit tool; unavailable engines never silently substitute."""
    try:
        if engine == "mediapipe":
            if baseline is None:
                raise background.Unavailable("Basic foreground mask unavailable")
            alpha = baseline
            evidence = dict(engine=engine, label=background_models.LABELS[engine], status="applied",
                            source_size=[rgb.shape[1],rgb.shape[0]], version="mediapipe-baseline", blur_sigma=2)
        else:
            alpha, evidence = background.matte(rgb,engine)
        measurements["background_removal"] = evidence
        checks.append(Check("background_tool","Background removal tool","pass",evidence["label"]))
        return alpha
    except background.Unavailable as exc:
        message = str(exc) + "; background left unchanged"
        measurements["background_removal"] = dict(engine=engine,label=background_models.LABELS[engine],
                                                    status="unavailable",detail=message)
        checks.append(Check("background_tool","Background removal tool","warn",message))
        return None


def _composite_background(rgb, alpha, colour, engine):
    if engine == "mediapipe":
        return replace_background(rgb,alpha,colour)
    return background.composite(rgb,alpha,colour)


def _crown_y(points, person_mask):
    """Locate the visible head top; use landmarks if segmentation is unavailable.

    A fixed forehead extension clips tall/curly hair. Require a continuous,
    substantial foreground band above the face so isolated hairs/noise do not
    control the crop. Arms or headwear still require the staff visual check.
    """
    forehead, chin = points[FOREHEAD], points[CHIN]
    face_h = chin[1] - forehead[1]
    estimate = float(forehead[1] - 0.30 * face_h)
    if person_mask is None or face_h <= 0:
        return estimate
    h, w = person_mask.shape
    cx = (points[FACE_L][0] + points[FACE_R][0]) / 2
    fw = abs(points[FACE_R][0] - points[FACE_L][0])
    x0, x1 = max(int(cx - .75 * fw), 0), min(int(cx + .75 * fw), w)
    low, high = max(int(forehead[1] - face_h), 0), min(int(forehead[1]), h)
    band = person_mask[low:high, x0:x1]
    if not band.size:
        return estimate
    visible = (band > .75).sum(axis=1) >= max(.15 * fw, 3)
    run = max(3, int(face_h * .01))
    starts = np.where(np.convolve(visible.astype(int), np.ones(run, int), mode="valid") >= run)[0]
    return float(low + starts[0]) if len(starts) else estimate


def _fit_auto_crop(rect, size, points, crown_y, profile):
    """Fit a default crop to real pixels without clipping the detected head.

    Move the requested crop first; reduce it only if the camera canvas cannot
    contain its dimensions. Country bounds are not relaxed: downstream checks
    still assess the actual head and eye proportions of this feasible crop.
    """
    left, top, crop_w, crop_h = rect
    w, h = size
    ratio = crop_w/crop_h
    crop_h = min(crop_h, float(h), w/ratio)
    crop_w = crop_h*ratio
    eye_mid = (points[L_IRIS]+points[R_IRIS])/2
    face_left,face_right = float(points[:,0].min()),float(points[:,0].max())
    chin_y = float(points[CHIN][1])
    low_x,high_x = max(0.,face_right-crop_w),min(w-crop_w,face_left)
    low_y,high_y = max(0.,chin_y-crop_h),min(h-crop_h,crown_y)
    # Honour allowed eye placement if a head-preserving placement exists.
    eye_low = max(low_y,float(eye_mid[1])-profile['eyes'][2]/100*crop_h)
    eye_high = min(high_y,float(eye_mid[1])-profile['eyes'][1]/100*crop_h)
    if eye_low<=eye_high:low_y,high_y=eye_low,eye_high
    if low_x>high_x or low_y>high_y:return None
    left = float(np.clip(float(eye_mid[0])-crop_w/2,low_x,high_x))
    top = float(np.clip(float(eye_mid[1])-profile['eyes'][0]/100*crop_h,low_y,high_y))
    return left,top,crop_w,crop_h


def _analysis_evidence(analysis, analyzer):
    return getattr(analysis,'evidence',None) or {
        'engine':type(analyzer).__name__, 'status':'completed',
        'face_count':len(analysis.faces), 'landmark_counts':[len(f.points) for f in analysis.faces],
    }


def _local_enhancement(rgb, values, phase, measurements, checks):
    v = enhancement.validate(values)
    if v['adaptive_profile']!='off':return rgb
    if phase == "restore" and not (v['lighting'] or v['denoise'] or v['detail']): return rgb
    if phase == "upscale" and v['scale'] == 1: return rgb
    out, evidence = enhancement.apply(rgb,v,phase)
    record = measurements.setdefault('local_enhancement',dict(settings=v,stages=[]))
    record['stages'].append(evidence)
    if evidence['status'] == 'unavailable':
        checks.append(Check('enhancement_'+phase,'Local enhancer','warn',evidence['message']))
    else:
        description = ', '.join(m['label'] for m in evidence['models']) or evidence.get('method','Detail sharpening')
        checks.append(Check('enhancement_'+phase,'Local enhancer','pass',description))
    return out


def _adaptive_edit(rgb, points, mask, values, measurements, checks, linear_master=None, raw_tone='neutral'):
    profile=enhancement.validate(values)['adaptive_profile']
    if profile=='off':return rgb
    if linear_master is None:
        out,evidence=adaptive_quality.apply(rgb,points,profile,mask,values.get('blemish_keep'))
    else:
        out,evidence=adaptive_quality.apply(rgb,points,profile,mask,values.get('blemish_keep'),
            linear_master=linear_master, raw_tone=raw_tone)
    measurements['adaptive_quality']=evidence
    measurements.setdefault('local_enhancement',dict(settings=values,stages=[]))['stages'].append(evidence)
    checks.append(Check('adaptive_edit','Automatic photo preparation',
        'warn' if evidence['status'] in ('unavailable','partial') else 'pass',evidence['message']))
    return out


def _enlarge_master(rgb, values, measurements, checks, target_size=None):
    old_h,old_w = rgb.shape[:2]
    out = _local_enhancement(rgb,values,'upscale',measurements,checks)
    enlargement = out.shape[1]/old_w
    if target_size:
        target = tuple(round(v*enlargement) for v in target_size)
        if (out.shape[1],out.shape[0]) != target:
            out = cv2.resize(out,target,interpolation=cv2.INTER_LANCZOS4)
    if (out.shape[1],out.shape[0]) != (old_w,old_h):
        # Quality uses the working crop grid above. Exact code JPEG checks run
        # again at issuance. Source resolution and eye-detail verdicts never change.
        measurements['quality_sampling_size'] = [old_w,old_h]
        measurements['output_size'] = [out.shape[1],out.shape[0]]
        factors = (out.shape[1]/old_w,out.shape[0]/old_h)
        for key in ('eye1','eye2'):
            if key in measurements: measurements[key] = [round(v*f,2) for v,f in zip(measurements[key],factors)]
        if 'output_eye_distance' in measurements:
            measurements['output_eye_distance'] = round(float(np.linalg.norm(
                np.array(measurements['eye1'])-np.array(measurements['eye2']))),2)
    return out


def _smooth_skin(rgb, points, values, measurements, checks):
    v = enhancement.validate(values)
    if not v['skin']: return rgb
    try:
        if points is None: raise ValueError('Face landmarks unavailable')
        if v['skin_method']=='guided':
            from . import skin_guided
            out,evidence = skin_guided.apply(rgb,points,v['skin'],v['blemish_keep'])
        else:
            out,evidence = skin.apply(rgb,points,v['skin'],v['blemish_keep'])
        checks.append(Check('enhancement_skin','Skin smoothing','pass',evidence['message']))
    except (ValueError,cv2.error):
        out = rgb
        evidence = dict(phase='skin',models=[],status='unavailable',strength=v['skin'],
            message='Skin smoothing skipped: facial regions could not be located reliably')
        checks.append(Check('enhancement_skin','Skin smoothing','warn',evidence['message']))
    measurements.setdefault('local_enhancement',dict(settings=v,stages=[]))['stages'].append(evidence)
    return out


def _portrait_tone(rgb,points,mask,values,measurements,checks,background_colour=None):
    v=enhancement.validate(values)
    if not v['portrait_tone']:return rgb
    try:
        if points is None:raise ValueError('Face landmarks unavailable')
        from . import portrait_tone
        out,evidence=portrait_tone.apply(rgb,points,v['portrait_tone'],mask,background_colour)
    except (ValueError,cv2.error):
        out=rgb
        evidence=dict(phase='portrait_tone',models=[],status='unavailable',strength=v['portrait_tone'],
                      message='Skin lighting skipped: facial regions could not be located reliably')
    measurements.setdefault('local_enhancement',dict(settings=v,stages=[]))['stages'].append(evidence)
    checks.append(Check('enhancement_portrait_tone','Skin lighting and contrast',
                        'warn' if evidence['status']=='unavailable' else 'pass',evidence['message']))
    return out


def _clean_skin(rgb,points,values,measurements,checks,assets):
    v = enhancement.validate(values)
    if not v['blemish']:return rgb
    out,record,images = blemishes.apply(rgb,points,v)
    measurements.setdefault('local_enhancement',dict(settings=v,stages=[]))['stages'].append(record)
    measurements['skin_cleaning'] = record
    assets.update(images)
    checks.append(Check('enhancement_blemish','Advanced skin cleaning',
        'warn' if record['status']=='unavailable' else 'pass',record.get('message','No repair needed')))
    return out


def _encoded_highlight_review(jpeg, values, measurements, analyzer=None, always=False):
    if not always and not enhancement.active(values): return
    report = hotspots.inspect_photo(jpeg,analyzer)
    # Keep native-pixel measurements and exact JPEG digest, not duplicate images
    # or overlay geometry in the database. The inspector renders overlays on demand.
    measurements['final_highlights'] = {key:value for key,value in report.items()
        if key not in ('preview','outlines','patches')}
    if report.get('status')=='diagnostic':
        measurements['regional_near_clip'] = report['near_clip_all_percent']
        measurements['regional_bright_patches'] = report['patch_count']


def _process(data: bytes, age_group: str = "adult", analyzer=None,
            auto_adjust: bool = config.AUTO_ADJUST, even_bg: bool = config.EVEN_BG,
            fix_shadows: bool = config.FIX_SHADOWS, replace_bg: bool = config.BG_REPLACE,
            country_id: str | None = None, crop=None, framed=False,
            adjustments=None, print_only=False, background_engine=None, enhancement_options=None, raw_settings=None) -> Result:
    """age_group: adult | child (1-5) | baby (under 1)."""
    profile = photomatic.country(country_id)
    out_w, out_h = photomatic.output_size(profile)
    master_size = (out_w,out_h)
    crop = crop or {"zoom": 1, "x": 0, "y": 0, "rotation": 0}
    checks: list[Check] = []
    cleaner_assets = {}
    measurements = {"method": "Tuttoprint CV v1", "country_id": profile["id"]}
    adjustments = local_adjustments.validate(adjustments)
    enhancement_options = enhancement.validate(enhancement_options)
    if enhancement_options['adaptive_profile']!='off':
        # One controller owns the edit budget. Old fixed sliders/recipes cannot
        # silently stack on an adaptive profile, including saved legacy jobs.
        enhancement_options=enhancement.validate(dict(adaptive_profile=enhancement_options['adaptive_profile'],
            blemish_keep=enhancement_options['blemish_keep']))
        auto_adjust=fix_shadows=even_bg=False
        adjustments=local_adjustments.validate()
    background_engine = background_models.validate(background_engine or config.BACKGROUND_ENGINE)
    measurements["local_adjustments"] = {"engine": local_adjustments.VERSION, "values": adjustments}

    def add(key, label, status, detail=""):
        checks.append(Check(key, label, status, detail))

    try:
        rgb, linear_master, raw_report = load_source(data, raw_settings)
    except (raw_development.Unavailable, raw_development.InvalidRaw) as exc:
        add('file', 'RAW development', 'fail', str(exc))
        return Result(False, checks, measurements=measurements)
    except Exception:
        add("file", "Image file", "fail", "Not a readable image. Use JPEG, PNG or a supported CR2.")
        return Result(False, checks, measurements=measurements)

    raw_tone = raw_report['settings']['tone'] if raw_report else 'neutral'
    if raw_report:
        measurements['raw_development'] = raw_report
        measurements['source'] = {'format':'CR2', 'sensor_decoded':True}
        raw_report['precision_boundary'] = 'Float32 source through crop and lighting; sRGB8 before optional local tools and JPEG delivery'

    h, w = rgb.shape[:2]
    measurements["input_size"] = [w, h]
    if print_only:
        result = _print_only_result(rgb, profile, analyzer, adjustments,
                                  auto_adjust, fix_shadows, even_bg, replace_bg, background_engine, enhancement_options)
        if raw_report:
            raw_report['precision_boundary'] = 'Float32 RAW development; native sRGB8 before full-frame editing and print fitting'
            result.measurements.update(raw_development=raw_report, source=measurements['source'])
        return result
    rotation = int(crop.get("rotation", 0)) % 360
    if rotation:
        rgb = np.ascontiguousarray(np.rot90(rgb, -(rotation // 90)))
        if linear_master is not None:
            linear_master = np.ascontiguousarray(np.rot90(linear_master, -(rotation // 90)))
        h, w = rgb.shape[:2]
    angle = float(crop.get("angle", 0))
    if angle:
        # Rotate into an expanded canvas so original edges are not cropped off.
        # Added borders are excluded by the framing check below.
        original_bounds = np.ones((h, w), dtype=np.uint8)
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1)
        nw = int(np.ceil(h * abs(matrix[0, 1]) + w * abs(matrix[0, 0])))
        nh = int(np.ceil(h * abs(matrix[0, 0]) + w * abs(matrix[0, 1])))
        matrix[:, 2] += [(nw - w) / 2, (nh - h) / 2]
        rgb = cv2.warpAffine(rgb, matrix, (nw, nh), borderValue=(0, 0, 0))
        if linear_master is not None:
            linear_master = cv2.warpAffine(linear_master, matrix, (nw, nh), borderValue=(0, 0, 0))
            rgb = raw_development.render(linear_master, raw_tone)
        valid_pixels = cv2.warpAffine(original_bounds, matrix, (nw, nh), flags=cv2.INTER_NEAREST)
        h, w = rgb.shape[:2]
    else:
        valid_pixels = None
    measurements["analysis_size"] = [w, h]
    # Freestyle templates deliberately do not impose biometric framing.
    if not profile["use_head"] and not profile["use_width"]:
        if raw_report:
            raw_report['precision_boundary'] = 'Float32 RAW development and rotation; native sRGB8 before free-style editing and fitting'
        before = None  # Source comparison rendered at the final grid by process().
        original_rgb = rgb
        if enhancement_options['adaptive_profile']!='off':
            skin_points=None
            try:
                face_analyzer=analyzer or get_analyzer()
                analysis=face_analyzer.analyze(original_rgb)
                measurements['face_analysis']=_analysis_evidence(analysis,face_analyzer)
                if len(analysis.faces)==1:skin_points=analysis.faces[0].points
            except Exception:
                measurements['face_analysis']={'status':'unavailable'}
            rgb=_adaptive_edit(rgb,skin_points,None,enhancement_options,measurements,checks)
        rgb = _local_enhancement(rgb,enhancement_options,'restore',measurements,checks)
        if replace_bg:
            baseline = None
            if background_engine == "mediapipe":
                try:
                    baseline = (analyzer or get_analyzer()).analyze(original_rgb).person_mask
                except Exception:
                    pass
            alpha = _background_mask(original_rgb,baseline,background_engine,measurements,checks)
            if alpha is not None:
                rgb = _composite_background(rgb,alpha,profile["background"],background_engine)
        rgb, notes = local_adjustments.apply(rgb, adjustments)
        skin_points = None
        if enhancement_options['skin'] or enhancement_options['blemish'] or enhancement_options['portrait_tone']:
            try:
                face_analyzer=analyzer or get_analyzer()
                analysis=face_analyzer.analyze(original_rgb)
                measurements['face_analysis']=_analysis_evidence(analysis,face_analyzer)
                faces=analysis.faces
                if len(faces)==1: skin_points=faces[0].points
            except Exception:
                pass
        rgb = _portrait_tone(rgb,skin_points,alpha if replace_bg else None,enhancement_options,measurements,checks,
                             profile['background'] if replace_bg and alpha is not None else None)
        rgb = _clean_skin(rgb,skin_points,enhancement_options,measurements,checks,cleaner_assets)
        rgb = _smooth_skin(rgb,skin_points,enhancement_options,measurements,checks)
        im = ImageOps.fit(Image.fromarray(rgb), (out_w, out_h), method=Image.LANCZOS)
        out = np.asarray(im)
        add("framing", "Free-style crop", "pass", "No face-size target in this template")
        measurements["output_size"] = [out_w, out_h]
        out = _enlarge_master(out,enhancement_options,measurements,checks)
        jpeg = _encode_jpeg(out)
        _encoded_highlight_review(jpeg,enhancement_options,measurements,analyzer)
        return Result(True, checks, jpeg, _small_jpeg(out), before, measurements,cleaner_assets)
    try:
        analyzer = analyzer or get_analyzer()
        an = analyzer.analyze(rgb)
        measurements['face_analysis'] = _analysis_evidence(an,analyzer)
    except Exception:
        measurements['face_analysis'] = {'status':'unavailable'}
        add('face','Face analysis','fail','The local face model could not run. Check its installation; selected facial tools have not run.')
        return Result(False,checks,measurements=measurements)

    if len(an.faces) == 0:
        add("face", "Face found", "fail", "No face detected.")
        return Result(False, checks, measurements=measurements)
    if len(an.faces) > 1:
        add("face", "Face found", "fail", "More than one face in the photo.")
        return Result(False, checks, measurements=measurements)
    add("face", "Face found", "pass")

    f = an.faces[0]
    p = f.points
    li, ri = p[L_IRIS], p[R_IRIS]
    eye_mid = (li + ri) / 2
    chin, forehead = p[CHIN], p[FOREHEAD]
    face_l, face_r = p[FACE_L], p[FACE_R]

    # --- pose -----------------------------------------------------------
    roll = np.degrees(np.arctan2(ri[1] - li[1], ri[0] - li[0]))
    if roll > 90:
        roll -= 180
    elif roll < -90:
        roll += 180
    face_w = np.linalg.norm(face_r - face_l)
    face_cx = (face_l[0] + face_r[0]) / 2
    yaw_ratio = abs(p[NOSE][0] - face_cx) / max(face_w, 1)
    max_angle = float(photomatic.CATALOG["quality"].get("MaxAngle", 6))
    measurements.update(eye_angle=round(float(roll), 3), max_eye_angle=max_angle,
                        source_eye_distance=round(float(np.linalg.norm(ri - li)), 2),
                        yaw_ratio=round(float(yaw_ratio), 4))
    min_eye_distance = float(photomatic.CATALOG["quality"].get("MineyeDistance", 90))
    measurements["min_source_eye_distance"] = min_eye_distance
    if photomatic.CATALOG["quality"].get("CheckEyeDistance", "false").lower() == "true":
        add("eyedistance", "Source detail between eyes", "pass" if measurements["source_eye_distance"] >= min_eye_distance else "fail",
            f"{measurements['source_eye_distance']:g} px; minimum {min_eye_distance:g} px in the analysis image.")
    if abs(roll) > max_angle:
        add("tilt", "Head straight", "fail", f"Head tilted {abs(roll):.0f}°. Keep eyes level.")
    elif abs(roll) > 4:
        add("tilt", "Head straight", "warn", f"Slight tilt ({abs(roll):.0f}°).")
    else:
        add("tilt", "Head straight", "pass")
    if yaw_ratio > 0.12:
        add("facing", "Facing camera", "fail", "Turned to the side. Look straight at the camera.")
    elif yaw_ratio > 0.07:
        add("facing", "Facing camera", "warn", "Slightly turned.")
    else:
        add("facing", "Facing camera", "pass")

    # --- expression -----------------------------------------------------
    bs = f.blendshapes
    if bs:
        blink = max(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0))
        jaw = bs.get("jawOpen", 0)
        smile = max(bs.get("mouthSmileLeft", 0), bs.get("mouthSmileRight", 0))
        measurements.update(blink=round(float(blink), 4), jaw_open=round(float(jaw), 4),
                            smile=round(float(smile), 4))
        if age_group == "baby":
            add("eyes", "Eyes open", "pass", "Not required under 1.")
        elif blink > 0.55:
            add("eyes", "Eyes open", "fail", "Eyes look closed.")
        elif blink > 0.4:
            add("eyes", "Eyes open", "warn", "Eyes may be half closed.")
        else:
            add("eyes", "Eyes open", "pass")
        if age_group in ("baby", "child"):
            add("expression", "Plain expression", "pass", "Not required under 6.")
        elif jaw > 0.25:
            add("expression", "Plain expression", "fail", "Mouth open. Keep mouth closed.")
        elif smile > 0.5:
            add("expression", "Plain expression", "fail", "Smiling. Neutral expression needed.")
        elif smile > 0.3 or jaw > 0.15:
            add("expression", "Plain expression", "warn", "Expression not fully neutral.")
        else:
            add("expression", "Plain expression", "pass")

    # --- crop -----------------------------------------------------------
    face_h = chin[1] - forehead[1]
    crown_y = _crown_y(p, an.person_mask)
    head_h = chin[1] - crown_y
    if profile["use_head"]:
        crop_h = head_h / (profile["head"][0] / 100)
        crop_w = crop_h * out_w / out_h
    else:
        crop_w = face_w / (profile["face_width"][0] / 100)
        crop_h = crop_w * out_h / out_w
    zoom = float(crop.get("zoom", 1))
    # Country-template Eyes is the eye-line position as % of image height.
    top = eye_mid[1] - profile["eyes"][0] / 100 * crop_h
    left = eye_mid[0] - crop_w / 2
    target_rect=[float(v) for v in (left,top,crop_w,crop_h)]
    auto_fit=False
    outside=left<0 or top<0 or left+crop_w>w or top+crop_h>h
    if outside and not framed and profile.get('auto_crop',False):
        fitted=_fit_auto_crop(target_rect,(w,h),p,crown_y,profile)
        if fitted is not None:
            left,top,crop_w,crop_h=fitted
            auto_fit=True
    # Manual controls are relative to the usable automatic crop displayed in
    # the studio, rather than jumping back to an impossible nominal rectangle.
    base_rect=[float(v) for v in (left,top,crop_w,crop_h)]
    eye_x,eye_y=map(float,eye_mid)
    anchor_x=(eye_x-float(left))/float(crop_w)
    anchor_y=(eye_y-float(top))/float(crop_h)
    if zoom!=1:
        crop_h,crop_w=crop_h/zoom,crop_w/zoom
        left=eye_x-anchor_x*crop_w
        top=eye_y-anchor_y*crop_h
    left += float(crop.get("x", 0)) / 100 * crop_w
    top += float(crop.get("y", 0)) / 100 * crop_h
    if framed:
        # Validate an already framed deliverable without moving/zooming it again.
        crop_w, crop_h, left, top = float(w), float(h), 0., 0.
    requested_rect = [float(v) for v in (left,top,crop_w,crop_h)]
    measurements['crop_geometry'] = {
        'method':'existing_frame' if framed else 'automatic_source_fit' if auto_fit else 'landmark_target',
        'requested_rect':requested_rect, 'source_rect':[float(v) for v in (left,top,crop_w,crop_h)],
        'base_rect':base_rect,'target_rect':target_rect,'anchor':[anchor_x,anchor_y],
        'automatic_fit':auto_fit, 'crown_y':float(crown_y), 'chin_y':float(chin[1]),
        'head_target_percent':profile['head'][0], 'head_range_percent':profile['head'][1:],
    }
    x0, y0, x1, y1 = left, top, left + crop_w, top + crop_h
    measurements["source_crop_size"] = [round(float(crop_w), 2), round(float(crop_h), 2)]

    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        add("framing", "Head and shoulders in frame", "fail",
            "Not enough space around the head. Step back so head and shoulders fit with space above.")
        return Result(False, checks, measurements=measurements)
    if crop_w < min(MIN_SRC_W, out_w) or crop_h < min(MIN_SRC_H, out_h):
        add("resolution", "Resolution", "fail",
            f"Face area too small ({int(crop_w)}x{int(crop_h)}px). Move closer or use a better camera.")
        return Result(False, checks, measurements=measurements)
    add("framing", "Head and shoulders in frame", "pass",
        'Automatic crop fitted to available camera pixels; head and eye limits are checked below.' if auto_fit else '')
    add("resolution", "Resolution", "pass", f"{int(crop_w)}x{int(crop_h)}px source")

    if enhancement.active(enhancement_options):
        # Do not feed an artificially enlarged small crop into the learned
        # enhancer. Restore on the source crop grid, then prepare the print master.
        working_scale = min(1.,crop_w/out_w,crop_h/out_h)
        out_w,out_h = max(1,round(out_w*working_scale)),max(1,round(out_h*working_scale))
    M = np.array([[out_w / crop_w, 0, -x0 * out_w / crop_w],
                  [0, out_h / crop_h, -y0 * out_h / crop_h]], dtype=np.float32)
    if linear_master is not None:
        # NumPy landmark scalars can keep arithmetic at float32. Reconstruct
        # from the recorded Python-float rectangle so saved comparisons replay
        # the identical matrix even at native 24 MP coordinates.
        cx,cy,cw,ch=measurements['crop_geometry']['source_rect']
        M=np.array([[out_w/cw,0,-cx*out_w/cw],
                    [0,out_h/ch,-cy*out_h/ch]],np.float32)
    out = cv2.warpAffine(rgb, M, (out_w, out_h), flags=cv2.INTER_AREA,
                         borderMode=cv2.BORDER_REPLICATE)
    working_linear = None
    if linear_master is not None:
        working_linear = cv2.warpAffine(linear_master, M, (out_w, out_h), flags=cv2.INTER_AREA,
                                       borderMode=cv2.BORDER_REPLICATE)
        out = raw_development.render(working_linear, raw_tone)
        raw_report['working_size'] = [out_w, out_h]
        raw_report['working_linear_sha256'] = hashlib.sha256(working_linear.tobytes()).hexdigest()
        # Later local models use the crop. Do not keep another request's full
        # float frame alive after the decoder's single-frame cache is evicted.
        linear_master = None
    if valid_pixels is not None:
        coverage = cv2.warpAffine(valid_pixels, M, (out_w, out_h), flags=cv2.INTER_NEAREST)
        if not coverage.all():
            add("framing", "Rotation edges", "fail", "Rotation exposes areas outside the camera photo. Reduce rotation or adjust the crop.")
            return Result(False, checks, measurements=measurements)
    mask = None
    if an.person_mask is not None:
        mask = cv2.warpAffine(an.person_mask, M, (out_w, out_h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    replacement_mask = None
    if replace_bg:
        source_alpha = _background_mask(rgb,an.person_mask,background_engine,measurements,checks)
        if source_alpha is not None:
            replacement_mask = cv2.warpAffine(source_alpha,M,(out_w,out_h),flags=cv2.INTER_LINEAR,
                                               borderMode=cv2.BORDER_REPLICATE)
            mask = replacement_mask
    tp = np.c_[p, np.ones(len(p))] @ M.T  # landmarks in output space
    measurements.update(output_size=[out_w, out_h],
                        eye1=[round(float(v), 2) for v in tp[L_IRIS]],
                        eye2=[round(float(v), 2) for v in tp[R_IRIS]],
                        output_eye_distance=round(float(np.linalg.norm(tp[R_IRIS] - tp[L_IRIS])), 2))

    raw = out.copy()  # unadjusted crop, used for glare detection
    before = None
    if enhancement.active(enhancement_options):
        original_face = raw[max(int(tp[FOREHEAD][1]),0):int(tp[CHIN][1]),
                            max(int(min(tp[FACE_L][0],tp[FACE_R][0])),0):int(max(tp[FACE_L][0],tp[FACE_R][0]))]
        if original_face.size:
            original_gray = cv2.cvtColor(original_face,cv2.COLOR_RGB2GRAY)
            original_gray = cv2.resize(original_gray,(300,max(1,int(300*original_gray.shape[0]/original_gray.shape[1]))))
            measurements['unadjusted_sharpness'] = round(float(cv2.Laplacian(original_gray,cv2.CV_64F).var()),2)
    out = _adaptive_edit(out,tp,mask,enhancement_options,measurements,checks,working_linear,raw_tone)
    out = _local_enhancement(out,enhancement_options,'restore',measurements,checks)
    fb = (min(tp[FACE_L][0], tp[FACE_R][0]), tp[FOREHEAD][1],
          max(tp[FACE_L][0], tp[FACE_R][0]), tp[CHIN][1])
    notes = []
    if fix_shadows:
        out, amt = soften_face_shadows(out, fb, mask)
        if amt:
            notes.append("face shadow softened")
    if auto_adjust or even_bg:
        out, n = enhance(out, mask, fb, even_bg=even_bg and not replace_bg, adjust=auto_adjust)
        notes += n
    if replacement_mask is not None:
        out = _composite_background(out,replacement_mask,profile["background"],background_engine)
        notes.append("background replaced · "+background_models.LABELS[background_engine])
    out, manual_notes = local_adjustments.apply(out, adjustments)
    notes += manual_notes
    out = _portrait_tone(out,tp,mask,enhancement_options,measurements,checks,
                         profile['background'] if replacement_mask is not None else None)
    out = _clean_skin(out,tp,enhancement_options,measurements,checks,cleaner_assets)
    out = _smooth_skin(out,tp,enhancement_options,measurements,checks)
    if auto_adjust or fix_shadows or replace_bg or even_bg or manual_notes:
        add("adjust", "Auto enhance", "pass",
            ("Applied: " + ", ".join(notes)) if notes else "No correction needed")

    # --- quality --------------------------------------------------------
    lum = _lum(out)
    fx0, fx1 = int(tp[FACE_L][0]), int(tp[FACE_R][0])
    fy0, fy1 = int(tp[FOREHEAD][1]), int(tp[CHIN][1])
    fx0, fx1 = sorted((max(fx0, 0), min(fx1, out_w)))
    face_region = lum[max(fy0, 0):fy1, fx0:fx1]
    face_rgb = out[max(fy0, 0):fy1, fx0:fx1]

    gray = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2GRAY)
    g = cv2.resize(gray, (300, int(300 * gray.shape[0] / max(gray.shape[1], 1))))
    sharp = cv2.Laplacian(g, cv2.CV_64F).var()
    measurements["sharpness"] = round(float(sharp), 2)
    if sharp < 25:
        add("sharp", "In focus", "fail", "Photo is blurred.")
    elif sharp < 50:
        add("sharp", "In focus", "warn", "Slightly soft focus.")
    else:
        add("sharp", "In focus", "pass")

    fmean = float(face_region.mean())
    measurements.update(face_lightness=round(fmean, 2), contrast=round(float(face_region.std()), 2))
    if fmean < 30:
        add("exposure", "Lighting", "fail", "Face too dark.")
    elif fmean > 88:
        add("exposure", "Lighting", "fail", "Face overexposed.")
    else:
        add("exposure", "Lighting", "pass")

    mid = face_region.shape[1] // 2
    lmean, rmean = face_region[:, :mid].mean(), face_region[:, mid:].mean()
    shadow = abs(lmean - rmean) / max(fmean, 1)
    measurements["lighting_imbalance"] = round(float(shadow) * 100, 2)
    if shadow > 0.30:
        add("shadow", "No shadows on face", "fail", "One side of the face is in shadow. This can't be corrected: fix the lights and retake.")
    elif shadow > 0.18:
        add("shadow", "No shadows on face", "warn", "Light is a bit uneven across the face.")
    else:
        add("shadow", "No shadows on face", "pass")

    hsv = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2HSV)
    if hsv[..., 1].mean() < 12:
        add("colour", "Colour photo", "fail", "Looks black and white. Must be colour.")
    else:
        add("colour", "Colour photo", "pass")

    # specular glare around eyes (glasses). Eye whites themselves are excluded.
    glare_px, total_px = 0, 0
    eye_mask = np.zeros((out_h, out_w), np.uint8)
    for ring in (LEFT_EYE_RING, RIGHT_EYE_RING):
        cv2.fillPoly(eye_mask, [tp[ring].astype(np.int32)], 255)
    eye_mask = cv2.dilate(eye_mask, np.ones((7, 7), np.uint8))
    for ring in (LEFT_EYE_RING, RIGHT_EYE_RING):
        pts = tp[ring].astype(int)
        x, y, ww, hh = cv2.boundingRect(pts)
        pad = max(int(hh * 1.5), 10)
        ys = slice(max(y - pad, 0), y + hh + pad)
        xs = slice(max(x - pad, 0), x + ww + pad)
        roi = raw[ys, xs]
        if roi.size:
            h2 = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
            bright = (h2[..., 2] > 245) & (h2[..., 1] < 25) & (eye_mask[ys, xs] == 0)
            glare_px += int(bright.sum())
            total_px += roi.shape[0] * roi.shape[1]
    glare = glare_px / max(total_px, 1)
    measurements["glare_area"] = round(glare * 100, 3)
    if glare > 0.04:
        add("glare", "No glare on glasses", "fail", "Reflection near the eyes.")
    elif glare > 0.015:
        add("glare", "No glare on glasses", "warn", "Possible reflection near the eyes.")
    else:
        add("glare", "No glare on glasses", "pass")

    # --- background -----------------------------------------------------
    if mask is not None:
        bg = mask < 0.2
    else:  # fallback: side strips above shoulders
        bg = np.zeros(lum.shape, bool)
        top_band = slice(0, int(tp[CHIN][1] * 0.8))
        bg[top_band, : max(fx0 - 30, 1)] = True
        bg[top_band, min(fx1 + 30, out_w - 1):] = True

    if replacement_mask is not None:
        add("background", "Plain light background", "pass", "Replaced with the template background colour")
    elif bg.sum() < 500:
        add("background", "Plain light background", "warn", "Could not measure background.")
    else:
        bl = lum[bg]
        bmean, bstd = float(bl.mean()), float(bl.std())
        bg_rgb = np.median(out[bg], axis=0)
        measurements.update(background_rgb=[round(float(v), 1) for v in bg_rgb],
                            background_lightness=round(bmean, 2), background_variation=round(bstd, 2))
        lower = np.array(profile["background_min"])
        upper = np.array(profile["background_max"])
        if (bg_rgb < lower - 3).any() or (bg_rgb > upper + 3).any():
            add("background", "Template background colour", "fail",
                f"Background RGB {tuple(bg_rgb.astype(int))}; expected {tuple(lower)} to {tuple(upper)}.")
        elif bmean < 62:
            add("background", "Plain light background", "fail", "Background too dark. Use a plain light wall.")
        elif bstd > 12:
            add("background", "Plain light background", "fail", "Background not plain (pattern, objects or shadow).")
        elif bstd > 7:
            add("background", "Plain light background", "warn", "Background slightly uneven.")
        else:
            add("background", "Plain light background", "pass")
        # shadow behind: compare left/right background halves
        cols = np.where(bg.any(axis=0))[0]
        if len(cols):
            half = out_w // 2
            lb, rb = lum[:, :half][bg[:, :half]], lum[:, half:][bg[:, half:]]
            if lb.size > 200 and rb.size > 200 and abs(lb.mean() - rb.mean()) > 10:
                add("bgshadow", "No shadow behind", "warn", "One side of the background is darker.")

    # --- head size sanity (after crop) ---------------------------------
    head_frac = (chin[1] - crown_y) / crop_h
    if profile["use_head"] and not (profile["head"][1] / 100 <= head_frac <= profile["head"][2] / 100):
        add("headsize", "Head size", "fail", f"Estimated head is {head_frac*100:.4f}% of height; template range {profile['head'][1]:g}–{profile['head'][2]:g}%. The measured limit has not been relaxed.")
    eyes_frac = (tp[L_IRIS][1] + tp[R_IRIS][1]) / 2 / out_h * 100
    if not profile["eyes"][1] <= eyes_frac <= profile["eyes"][2]:
        add("eyeposition", "Eye position", "fail", f"Eyes at {eyes_frac:.0f}%; template range {profile['eyes'][1]:g}–{profile['eyes'][2]:g}%.")
    if profile["use_width"]:
        width_frac = np.linalg.norm(tp[FACE_R] - tp[FACE_L]) / out_w * 100
        if not profile["face_width"][1] <= width_frac <= profile["face_width"][2]:
            add("facewidth", "Face width", "fail", f"Face width {width_frac:.0f}%.")
    measurements.update(head_percent=round(float(head_frac) * 100, 6),
                        eye_height_percent=round(float(eyes_frac), 3),
                        face_width_percent=round(float(np.linalg.norm(tp[FACE_R] - tp[FACE_L]) / out_w * 100), 3))
    if profile["glasses_forbidden"]:
        add("glasses", "Glasses removed", "warn", "This template forbids glasses. Staff must check; AI glare detection does not detect all glasses.")
    if profile["special_mode"]:
        add("special", "Additional document workflow", "warn", "This document requires an external submission/signature step in addition to the photo.")

    ok = not any(c.status == "fail" for c in checks)
    max_kb = profile["digital_kb"][1] if profile["digital_kb"][1] > 0 else 9500
    min_kb = profile["digital_kb"][0] if profile["digital_kb"][0] > 0 else (50 if profile["hmpo_code"] else 0)
    out = _enlarge_master(out,enhancement_options,measurements,checks,master_size)
    jpeg = _encode_jpeg(out)
    if all(v > 0 for v in profile["digital_size"]):
        digital = ImageOps.fit(Image.fromarray(out), photomatic.save_size(profile), method=Image.LANCZOS)
        digital_jpeg = _encode_jpeg(np.asarray(digital), min_kb=min_kb, max_kb=max_kb)
        size_kb = len(digital_jpeg) / 1024
    else:
        size_kb = len(jpeg) / 1024
    if size_kb < min_kb or size_kb > max_kb:
        add("filesize", "Digital file size", "fail", f"{size_kb:.0f} KB; template requires {min_kb:g}–{max_kb:g} KB.")
        ok = False
    measurements["digital_size"] = list(photomatic.save_size(profile))
    measurements["digital_kib"] = round(size_kb, 2)
    _encoded_highlight_review(jpeg,enhancement_options,measurements,analyzer)
    return Result(ok, checks, jpeg, _small_jpeg(out), before, measurements,cleaner_assets)


def process(data: bytes, age_group: str = "adult", analyzer=None,
            auto_adjust: bool = config.AUTO_ADJUST, even_bg: bool = config.EVEN_BG,
            fix_shadows: bool = config.FIX_SHADOWS, replace_bg: bool = config.BG_REPLACE,
            country_id: str | None = None, crop=None, framed=False,
            adjustments=None, print_only=False, background_engine=None, enhancement_options=None, raw_settings=None) -> Result:
    """Prepare and separately measure source/master/exact export using native OFIQ."""
    result = _process(data, age_group, analyzer, auto_adjust, even_bg, fix_shadows,
                      replace_bg, country_id, crop, framed, adjustments, print_only,
                      background_engine, enhancement_options, raw_settings)
    if result.jpeg:
        from . import comparison
        try:
            size=comparison.size(result.jpeg)
            result.before_jpeg=comparison.render(data,result.measurements,{'crop':crop or {}},size,country_id)
            result.measurements['comparison']=dict(version=comparison.VERSION,status='matched',size=list(size),
                reference='Processing input before local edits, resampled onto the same crop and output grid',
                source_file_sha256=hashlib.sha256(data).hexdigest(),
                before_sha256=hashlib.sha256(result.before_jpeg).hexdigest(),after_sha256=hashlib.sha256(result.jpeg).hexdigest())
        except (ValueError,OSError,cv2.error,raw_development.Unavailable):
            result.before_jpeg=None
            result.measurements['comparison']=dict(version=comparison.VERSION,status='unavailable',
                message='Source comparison could not be rendered; no thumbnail substitute is shown.')
    if not config.OFIQ_ENABLED:
        result.measurements['ofiq'] = dict(engine='OFIQ', status='off', stages=[])
        return result
    if any(c.key=='file' and c.status=='fail' for c in result.checks):
        result.measurements['ofiq']=dict(engine='OFIQ',status='unavailable',stages=[],
            message='Source decoding failed; no quality pass is inferred.')
        return result
    try:
        if framed and not raw_development.is_raw_signature(data[:16]):
            # Code validation assesses input delivery bytes without a second encode.
            images = {'delivery_jpeg': data}
        else:
            report=result.measurements.get('raw_development',{})
            images = {'original': ofiq.source_png(data, raw_settings=report.get('settings'),expected_development=report)}
            if result.jpeg:
                images.update(prepared_master=result.jpeg,
                              save_jpeg=save_photo(result.jpeg, country_id))
        record = ofiq.assess(images)
        record['source_file_sha256'] = hashlib.sha256(data).hexdigest()
        if result.measurements.get('raw_development'):
            report=result.measurements['raw_development']
            record['source_development']={key:report[key] for key in ('version','rawpy','libraw','settings')}
        result.measurements['ofiq'] = record
    except (OSError, ValueError, raw_development.Unavailable):
        result.measurements['ofiq'] = dict(engine='OFIQ', status='unavailable', stages=[],
            message='Native quality assessment unavailable; no OFIQ pass is implied.')
    if result.measurements['ofiq']['status'] != 'completed':
        result.checks.append(Check('ofiq_unavailable', 'OFIQ quality measurements', 'warn',
            'Some native quality measurements are unavailable. See OFIQ details; staff responsibility remains available.'))
    # OFIQ quality values have no calibrated country decision limits here.
    # They never manufacture green checks or restrict the existing override.
    return result


def _print_only_result(rgb, profile, analyzer, adjustments, auto_adjust, fix_shadows, even_bg, replace_bg, background_engine, enhancement_options):
    """Full-frame editing for staff output, without a passport framing verdict."""
    h, w = rgb.shape[:2]
    before = None
    out = rgb.copy()
    measurements = {}
    cleaner_assets = {}
    notes, checks = [], [Check("print_only", "Full-frame / print job", "warn",
                              "The whole photograph is fitted to the selected format. Passport framing has not been approved.")]
    mask, box, skin_points = None, None, None
    try:
        analyzer = analyzer or get_analyzer()
        analysis = analyzer.analyze(rgb)
        measurements['face_analysis'] = _analysis_evidence(analysis,analyzer)
        mask = analysis.person_mask
        if len(analysis.faces) == 1:
            points = analysis.faces[0].points
            skin_points = points
            box = (min(points[FACE_L][0], points[FACE_R][0]), points[FOREHEAD][1],
                   max(points[FACE_L][0], points[FACE_R][0]), points[CHIN][1])
            checks.append(Check("face", "Face found", "pass"))
        else:
            checks.append(Check("face", "Face found", "fail", "One face is needed for facial preparation; this image can still be printed."))
    except Exception:
        measurements['face_analysis'] = {'status':'unavailable'}
        notes.append("Facial analysis unavailable; facial tools skipped")
        checks.append(Check("face", "Facial analysis", "fail", "Unavailable; staff review needed"))
    replacement_mask = None
    if replace_bg:
        replacement_mask = _background_mask(rgb,mask,background_engine,measurements,checks)
        if replacement_mask is not None:
            mask = replacement_mask
    out = _adaptive_edit(out,skin_points,mask,enhancement_options,measurements,checks)
    out = _local_enhancement(out,enhancement_options,'restore',measurements,checks)
    if fix_shadows and box is not None:
        out, amount = soften_face_shadows(out, box, mask)
        if amount: notes.append("face shadow softened")
    if auto_adjust or even_bg:
        out, automatic_notes = enhance(out, mask, box or (0,0,w,h),
                                       even_bg=even_bg and not replace_bg, adjust=auto_adjust)
        notes += automatic_notes
    if replacement_mask is not None:
        out = _composite_background(out,replacement_mask,profile["background"],background_engine)
        notes.append("background replaced · "+background_models.LABELS[background_engine])
    out, manual_notes = local_adjustments.apply(out,adjustments)
    notes += manual_notes
    out = _portrait_tone(out,skin_points,mask,enhancement_options,measurements,checks,
                         profile['background'] if replacement_mask is not None else None)
    out = _clean_skin(out,skin_points,enhancement_options,measurements,checks,cleaner_assets)
    out = _smooth_skin(out,skin_points,enhancement_options,measurements,checks)
    if notes: checks.append(Check("adjust", "Local photo tools", "warn", "; ".join(notes)))
    out_w, out_h = photomatic.output_size(profile)
    # Fit rather than stretch or invent framing. Borders retain the whole image.
    border_colour = tuple(profile["background"])
    if replacement_mask is not None:
        background_pixels = out[mask < .15]
        if len(background_pixels) >= 100:
            border_colour = tuple(int(v) for v in np.median(background_pixels,axis=0))
    # Enlarge the prepared source, before fitting it to the print grid. Small
    # camera files therefore reach RealPLKSR with their actual native pixels.
    prepared_w = out.shape[1]
    out = _local_enhancement(out,enhancement_options,'upscale',measurements,checks)
    enlargement = out.shape[1]/prepared_w
    out_w,out_h = round(out_w*enlargement),round(out_h*enlargement)
    master = np.asarray(ImageOps.pad(Image.fromarray(out),(out_w,out_h),
                                    method=Image.Resampling.LANCZOS,color=border_colour))
    measurements.update({"method":"Full-frame local editing", "country_id":profile["id"],
                    "input_size":[w,h], "output_size":[out_w,out_h],
                    "local_adjustments":{"engine":local_adjustments.VERSION,"values":adjustments},
                    "print_only":True, "passport_assessment":"not_assessed"})
    measurements['comparison_padding_colour']=list(border_colour)
    if w < MIN_SRC_W or h < MIN_SRC_H:
        checks.append(Check("resolution", "Original source resolution", "fail",
                            f"{w} × {h} px; enlarging for print does not add real source detail"))
    jpeg = _encode_jpeg(master)
    _encoded_highlight_review(jpeg,enhancement_options,measurements,analyzer)
    return Result(False,checks,jpeg,_small_jpeg(master),before,measurements,cleaner_assets)


def code_photo(jpeg, country_id, staff_override=False):
    """Freeze and validate the exact UK JPEG served to HMPO, without stretching."""
    profile = photomatic.country(country_id)
    if profile["code_service"] != "uk":
        raise ValueError("Only UK code photos can be generated by this service")
    with Image.open(io.BytesIO(jpeg)) as image:
        size = tuple(profile["digital_size"]) if all(v > 0 for v in profile["digital_size"]) else image.size
        # Online templates with a different digital aspect need a fresh framing
        # implementation; never silently crop a second time after checks passed.
        if abs((size[0] / size[1]) / (image.width / image.height) - 1) > .005:
            if not staff_override:
                raise ValueError("Digital aspect ratio differs from the checked crop. Use the UK Online Renewal template or confirm staff responsibility.")
            # Staff chose to retain the reviewed framing; never stretch or
            # silently recrop it just to match a legacy export requirement.
            size = image.size
            output = jpeg
        else:
            output = _encode_jpeg(np.asarray(image.convert("RGB").resize(size, Image.Resampling.LANCZOS)),
                                  min_kb=50, max_kb=10_000_000 / 1024)
    if not staff_override and (size[0] < 600 or size[1] < 750 or not 50_000 <= len(output) <= 10_000_000):
        raise ValueError("The exact code JPEG must be at least 600 × 750 pixels and 50 KB–10 MB")
    return output


def check_code_photo(jpeg, country_id, age_group):
    with Image.open(io.BytesIO(jpeg)) as image:
        size = image.size
    try:
        result = process(jpeg, age_group, country_id=country_id, framed=True,
                         auto_adjust=False, fix_shadows=False, even_bg=False, replace_bg=False)
    except Exception:
        result = Result(False,[Check("quality_unavailable","Final quality assessment","fail",
                                    "The checker is unavailable; staff visual review and responsibility are required")],
                        measurements={"method":"Quality assessment unavailable","input_size":list(size)})
    _encoded_highlight_review(jpeg,None,result.measurements,always=True)
    profile = photomatic.country(country_id)
    target = photomatic.save_size(profile)
    if (size[0] < 600 or size[1] < 750 or not 50_000 <= len(jpeg) <= 10_000_000 or
            (all(v > 0 for v in profile["digital_size"]) and size != target)):
        result.checks.append(Check("delivery_format", "Digital delivery specification", "fail",
                                   f"Actual JPEG: {size[0]} × {size[1]} px, {len(jpeg)} bytes; review the digital document requirements"))
        result.ok = False
    return result


# --- print and save ------------------------------------------------------
SHEET_DPI = 301


def _mm(mm, dpi=SHEET_DPI):
    return int(round(mm / 25.4 * dpi))


def print_sheet(jpeg: bytes, code_text: str | None = None, template_id=None) -> bytes:
    """Render the imported printer's exact canvas, boxes and rotations.

    Code text occupies Photomatic's photo-number position. The separate code
    slip is available when a template has no photo-number field.
    """
    from PIL import ImageDraw, ImageFont

    layout = photomatic.PRINTS[template_id] if template_id else photomatic.default_print(photomatic.country())
    W, H, dpi = layout["width_px"], layout["height_px"], layout["dpi"]
    sheet = Image.new("RGB", (W, H), "white")
    if layout["background"]:
        background = config.BASE_DIR / layout["background"].lstrip("/")
        sheet = Image.open(background).convert("RGB").resize((W, H), Image.LANCZOS)
    photo = Image.open(io.BytesIO(jpeg)).convert("RGB")
    d = ImageDraw.Draw(sheet)
    rectangles = []
    for box in layout["boxes"]:
        x, y = _mm(box["x_mm"], dpi), _mm(box["y_mm"], dpi)
        pw, ph = _mm(box["width_mm"], dpi), _mm(box["height_mm"], dpi)
        # Landscape boxes hold a portrait turned clockwise, not a stretched face.
        source = photo.transpose(Image.Transpose.ROTATE_270) if box["landscape"] else photo
        tile = ImageOps.fit(source, (pw, ph), method=Image.LANCZOS)
        # Some original portrait layouts extend past the paper for borderless
        # bleed. Pillow clips those boxes at the canvas just as the printer does.
        sheet.paste(tile, (x, y))
        rectangles.append((x, y, x + pw, y + ph))
    if layout["cut_marks"]:
        # Draw marks in the surrounding margins, leaving every photo untouched.
        marks = Image.new("RGBA", (W, H))
        md = ImageDraw.Draw(marks)
        length = int(layout["cut_mark_size"])
        for x0, y0, x1, y1 in rectangles:
            for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                md.line((x-length, y, x+length, y), fill=(100, 100, 100, 255), width=1)
                md.line((x, y-length, x, y+length), fill=(100, 100, 100, 255), width=1)
        for x0, y0, x1, y1 in rectangles:
            md.rectangle((x0, y0, x1-1, y1-1), fill=(0, 0, 0, 0))
        sheet.paste(marks, (0, 0), marks)
    if code_text and layout["photo_number"]:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", _mm(3, dpi))
        except OSError:
            font = ImageFont.load_default(size=_mm(3, dpi))
        xy = tuple(_mm(v, dpi) for v in layout["number_position_mm"])
        d.text(xy, code_text, font=font, fill="#0088bd")
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=95, dpi=(dpi, dpi))
    return buf.getvalue()


def save_photo(jpeg: bytes, country_id=None, email=False) -> bytes:
    """Digital export follows the selected country's required/save dimensions."""
    profile = photomatic.country(country_id)
    size = photomatic.save_size(profile, email=email)
    rgb = np.asarray(ImageOps.fit(Image.open(io.BytesIO(jpeg)).convert("RGB"), size, method=Image.LANCZOS))
    maximum = profile["digital_kb"][1] if profile["digital_kb"][1] > 0 else 9500
    return _encode_jpeg(rgb, min_kb=0, max_kb=maximum)
