"""Passport photo processing: face analysis, HMPO crop, compliance checks.

Auto enhance: colour/exposure, face-shadow softening, background evening or
replacement. Facial features are never reshaped.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import config, photomatic

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

    def as_dict(self):
        return {
            "ok": self.ok,
            "checks": [c.__dict__ for c in self.checks],
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
        lm_path = model_dir / "face_landmarker.task"
        seg_path = model_dir / "selfie_segmenter.tflite"
        if not lm_path.exists():
            raise RuntimeError(f"Missing {lm_path}. Run scripts/download_models.sh")
        self.landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(lm_path)),
                num_faces=2,
                output_face_blendshapes=True,
            )
        )
        self.segmenter = None
        if seg_path.exists():
            self.segmenter = vision.ImageSegmenter.create_from_options(
                vision.ImageSegmenterOptions(
                    base_options=BaseOptions(model_asset_path=str(seg_path)),
                    output_confidence_masks=True,
                )
            )

    def analyze(self, rgb: np.ndarray) -> Analysis:
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
        return Analysis(faces, mask)


_analyzer = None


def get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = MediaPipeAnalyzer()
    return _analyzer


def load_image(data: bytes) -> np.ndarray:
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im).convert("RGB")
    return np.asarray(im)


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


def _small_jpeg(rgb):
    buf = io.BytesIO()
    im = Image.fromarray(rgb)
    im.thumbnail((350, 450), Image.LANCZOS)
    im.save(buf, "JPEG", quality=85)
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
            notes.append("highlights recovered")

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


def process(data: bytes, age_group: str = "adult", analyzer=None,
            auto_adjust: bool = config.AUTO_ADJUST, even_bg: bool = config.EVEN_BG,
            fix_shadows: bool = config.FIX_SHADOWS, replace_bg: bool = config.BG_REPLACE,
            country_id: str | None = None, crop=None) -> Result:
    """age_group: adult | child (1-5) | baby (under 1)."""
    profile = photomatic.country(country_id)
    out_w, out_h = photomatic.output_size(profile)
    crop = crop or {"zoom": 1, "x": 0, "y": 0, "rotation": 0}
    checks: list[Check] = []

    def add(key, label, status, detail=""):
        checks.append(Check(key, label, status, detail))

    try:
        rgb = load_image(data)
    except Exception:
        add("file", "Image file", "fail", "Not a readable image. Use JPEG or PNG.")
        return Result(False, checks)

    h, w = rgb.shape[:2]
    rotation = int(crop.get("rotation", 0)) % 360
    if rotation:
        rgb = np.ascontiguousarray(np.rot90(rgb, -(rotation // 90)))
        h, w = rgb.shape[:2]
    # Freestyle templates deliberately do not impose biometric framing.
    if not profile["use_head"] and not profile["use_width"]:
        im = ImageOps.fit(Image.fromarray(rgb), (out_w, out_h), method=Image.LANCZOS)
        out = np.asarray(im)
        add("framing", "Free-style crop", "pass", "No face-size target in this template")
        return Result(True, checks, _encode_jpeg(out), _small_jpeg(out), _small_jpeg(out))
    analyzer = analyzer or get_analyzer()
    an = analyzer.analyze(rgb)

    if len(an.faces) == 0:
        add("face", "Face found", "fail", "No face detected.")
        return Result(False, checks)
    if len(an.faces) > 1:
        add("face", "Face found", "fail", "More than one face in the photo.")
        return Result(False, checks)
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
    crop_h, crop_w = crop_h / zoom, crop_w / zoom
    # Country-template Eyes is the eye-line position as % of image height.
    top = eye_mid[1] - profile["eyes"][0] / 100 * crop_h
    left = eye_mid[0] - crop_w / 2
    left += float(crop.get("x", 0)) / 100 * crop_w
    top += float(crop.get("y", 0)) / 100 * crop_h
    x0, y0, x1, y1 = left, top, left + crop_w, top + crop_h

    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        add("framing", "Head and shoulders in frame", "fail",
            "Not enough space around the head. Step back so head and shoulders fit with space above.")
        return Result(False, checks)
    if crop_w < min(MIN_SRC_W, out_w) or crop_h < min(MIN_SRC_H, out_h):
        add("resolution", "Resolution", "fail",
            f"Face area too small ({int(crop_w)}x{int(crop_h)}px). Move closer or use a better camera.")
        return Result(False, checks)
    add("framing", "Head and shoulders in frame", "pass")
    add("resolution", "Resolution", "pass", f"{int(crop_w)}x{int(crop_h)}px source")

    M = np.array([[out_w / crop_w, 0, -x0 * out_w / crop_w],
                  [0, out_h / crop_h, -y0 * out_h / crop_h]], dtype=np.float32)
    out = cv2.warpAffine(rgb, M, (out_w, out_h), flags=cv2.INTER_AREA,
                         borderMode=cv2.BORDER_REPLICATE)
    mask = None
    if an.person_mask is not None:
        mask = cv2.warpAffine(an.person_mask, M, (out_w, out_h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    tp = np.c_[p, np.ones(len(p))] @ M.T  # landmarks in output space

    raw = out.copy()  # unadjusted crop, used for glare detection
    before = _small_jpeg(out)
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
    if replace_bg and mask is not None:
        out = replace_background(out, mask, profile["background"])
        notes.append("background replaced")
    if auto_adjust or fix_shadows or replace_bg or even_bg:
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
    if sharp < 25:
        add("sharp", "In focus", "fail", "Photo is blurred.")
    elif sharp < 50:
        add("sharp", "In focus", "warn", "Slightly soft focus.")
    else:
        add("sharp", "In focus", "pass")

    fmean = float(face_region.mean())
    if fmean < 30:
        add("exposure", "Lighting", "fail", "Face too dark.")
    elif fmean > 88:
        add("exposure", "Lighting", "fail", "Face overexposed.")
    else:
        add("exposure", "Lighting", "pass")

    mid = face_region.shape[1] // 2
    lmean, rmean = face_region[:, :mid].mean(), face_region[:, mid:].mean()
    shadow = abs(lmean - rmean) / max(fmean, 1)
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

    if replace_bg and mask is not None:
        add("background", "Plain light background", "pass", "Replaced with plain light grey")
    elif bg.sum() < 500:
        add("background", "Plain light background", "warn", "Could not measure background.")
    else:
        bl = lum[bg]
        bmean, bstd = float(bl.mean()), float(bl.std())
        bg_rgb = np.median(out[bg], axis=0)
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
        add("headsize", "Head size", "warn", f"Head is {head_frac*100:.0f}% of height.")
    eyes_frac = (tp[L_IRIS][1] + tp[R_IRIS][1]) / 2 / out_h * 100
    if not profile["eyes"][1] <= eyes_frac <= profile["eyes"][2]:
        add("eyeposition", "Eye position", "warn", f"Eyes at {eyes_frac:.0f}%; template range {profile['eyes'][1]:g}–{profile['eyes'][2]:g}%.")
    if profile["use_width"]:
        width_frac = np.linalg.norm(tp[FACE_R] - tp[FACE_L]) / out_w * 100
        if not profile["face_width"][1] <= width_frac <= profile["face_width"][2]:
            add("facewidth", "Face width", "warn", f"Face width {width_frac:.0f}%.")
    if profile["glasses_forbidden"]:
        add("glasses", "Glasses removed", "warn", "This template forbids glasses. Staff must check; AI glare detection does not detect all glasses.")
    if profile["special_mode"]:
        add("special", "Additional document workflow", "warn", "This document requires an external submission/signature step in addition to the photo.")

    ok = not any(c.status == "fail" for c in checks)
    max_kb = profile["digital_kb"][1] if profile["digital_kb"][1] > 0 else 9500
    min_kb = profile["digital_kb"][0] if profile["digital_kb"][0] > 0 else (50 if profile["hmpo_code"] else 0)
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
    return Result(ok, checks, jpeg, _small_jpeg(out), before)


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
