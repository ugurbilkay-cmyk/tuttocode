"""Passport photo processing: face analysis, HMPO crop, compliance checks.

Only crops and re-encodes. No face retouching (HMPO rejects edited photos).
Background replacement is optional and off by default (BG_REPLACE).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import config

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


def _lum(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32) * (100 / 255)


def process(data: bytes, age_group: str = "adult", analyzer=None) -> Result:
    """age_group: adult | child (1-5) | baby (under 1)."""
    analyzer = analyzer or get_analyzer()
    checks: list[Check] = []

    def add(key, label, status, detail=""):
        checks.append(Check(key, label, status, detail))

    try:
        rgb = load_image(data)
    except Exception:
        add("file", "Image file", "fail", "Not a readable image. Use JPEG or PNG.")
        return Result(False, checks)

    h, w = rgb.shape[:2]
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
    if abs(roll) > 8:
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
    crown_y = forehead[1] - 0.30 * face_h  # landmark 10 sits below the hair/crown
    head_h = chin[1] - crown_y
    crop_h = head_h / HEAD_TARGET
    crop_w = crop_h * OUT_W / OUT_H
    top = crown_y - CROWN_MARGIN * crop_h
    left = eye_mid[0] - crop_w / 2
    x0, y0, x1, y1 = left, top, left + crop_w, top + crop_h

    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        add("framing", "Head and shoulders in frame", "fail",
            "Not enough space around the head. Step back so head and shoulders fit with space above.")
        return Result(False, checks)
    if crop_w < MIN_SRC_W or crop_h < MIN_SRC_H:
        add("resolution", "Resolution", "fail",
            f"Face area too small ({int(crop_w)}x{int(crop_h)}px). Move closer or use a better camera.")
        return Result(False, checks)
    add("framing", "Head and shoulders in frame", "pass")
    add("resolution", "Resolution", "pass", f"{int(crop_w)}x{int(crop_h)}px source")

    M = np.array([[OUT_W / crop_w, 0, -x0 * OUT_W / crop_w],
                  [0, OUT_H / crop_h, -y0 * OUT_H / crop_h]], dtype=np.float32)
    out = cv2.warpAffine(rgb, M, (OUT_W, OUT_H), flags=cv2.INTER_AREA,
                         borderMode=cv2.BORDER_REPLICATE)
    mask = None
    if an.person_mask is not None:
        mask = cv2.warpAffine(an.person_mask, M, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    tp = np.c_[p, np.ones(len(p))] @ M.T  # landmarks in output space

    # --- quality --------------------------------------------------------
    lum = _lum(out)
    fx0, fx1 = int(tp[FACE_L][0]), int(tp[FACE_R][0])
    fy0, fy1 = int(tp[FOREHEAD][1]), int(tp[CHIN][1])
    fx0, fx1 = sorted((max(fx0, 0), min(fx1, OUT_W)))
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
        add("shadow", "No shadows on face", "fail", "Uneven light — one side of the face is in shadow.")
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
    eye_mask = np.zeros((OUT_H, OUT_W), np.uint8)
    for ring in (LEFT_EYE_RING, RIGHT_EYE_RING):
        cv2.fillPoly(eye_mask, [tp[ring].astype(np.int32)], 255)
    eye_mask = cv2.dilate(eye_mask, np.ones((7, 7), np.uint8))
    for ring in (LEFT_EYE_RING, RIGHT_EYE_RING):
        pts = tp[ring].astype(int)
        x, y, ww, hh = cv2.boundingRect(pts)
        pad = max(int(hh * 1.5), 10)
        ys = slice(max(y - pad, 0), y + hh + pad)
        xs = slice(max(x - pad, 0), x + ww + pad)
        roi = out[ys, xs]
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
        bg[top_band, min(fx1 + 30, OUT_W - 1):] = True

    if config.BG_REPLACE and mask is not None:
        soft = cv2.GaussianBlur(mask, (0, 0), 2)[..., None]
        plain = np.full_like(out, (238, 238, 236))
        out = (out * soft + plain * (1 - soft)).astype(np.uint8)
        lum = _lum(out)
        add("background", "Plain light background", "warn",
            "Background replaced — HMPO may treat this as editing.")
    elif bg.sum() < 500:
        add("background", "Plain light background", "warn", "Could not measure background.")
    else:
        bl = lum[bg]
        bmean, bstd = float(bl.mean()), float(bl.std())
        if bmean < 62:
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
            half = OUT_W // 2
            lb, rb = lum[:, :half][bg[:, :half]], lum[:, half:][bg[:, half:]]
            if lb.size > 200 and rb.size > 200 and abs(lb.mean() - rb.mean()) > 10:
                add("bgshadow", "No shadow behind", "warn", "One side of the background is darker.")

    # --- head size sanity (after crop) ---------------------------------
    head_frac = (tp[CHIN][1] - (tp[FOREHEAD][1] - 0.30 * (tp[CHIN][1] - tp[FOREHEAD][1]))) / OUT_H
    if not (HEAD_MIN - 0.02 <= head_frac <= HEAD_MAX + 0.02):
        add("headsize", "Head size", "warn", f"Head is {head_frac*100:.0f}% of height.")

    ok = not any(c.status == "fail" for c in checks)
    jpeg = _encode_jpeg(out)
    prev = io.BytesIO()
    Image.fromarray(out).resize((350, 450)).save(prev, "JPEG", quality=85)
    return Result(ok, checks, jpeg, prev.getvalue())


# --- print sheet --------------------------------------------------------
SHEET_DPI = 300


def _mm(mm):
    return int(round(mm / 25.4 * SHEET_DPI))


def print_sheet(jpeg: bytes, code_text: str | None = None) -> bytes:
    """6x4in (152x102mm) landscape sheet, 4 photos at 35x45mm with cut marks."""
    from PIL import ImageDraw, ImageFont

    W, H = _mm(152.4), _mm(101.6)
    sheet = Image.new("RGB", (W, H), "white")
    photo = Image.open(io.BytesIO(jpeg)).convert("RGB").resize((_mm(35), _mm(45)), Image.LANCZOS)
    pw, ph = photo.size
    gap = _mm(2)
    total = 4 * pw + 3 * gap
    x0 = (W - total) // 2
    y0 = _mm(12)
    d = ImageDraw.Draw(sheet)
    for i in range(4):
        x = x0 + i * (pw + gap)
        sheet.paste(photo, (x, y0))
        for cx, cy in ((x, y0), (x + pw, y0), (x, y0 + ph), (x + pw, y0 + ph)):
            d.line([(cx - 12, cy), (cx - 4, cy)], fill="#999", width=1)
            d.line([(cx + 4, cy), (cx + 12, cy)], fill="#999", width=1)
            d.line([(cx, cy - 12), (cx, cy - 4)], fill="#999", width=1)
            d.line([(cx, cy + 4), (cx, cy + 12)], fill="#999", width=1)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
        small = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font = small = ImageFont.load_default()
    ty = y0 + ph + _mm(5)
    if code_text:
        d.text((x0, ty), "Passport photo code:", font=small, fill="black")
        d.text((x0, ty + 36), code_text, font=font, fill="black")
        d.text((x0, ty + 96), "Enter at gov.uk/apply-renew-passport → “I have a code”",
               font=small, fill="#333")
    d.text((W - x0, H - _mm(5)), f"{config.SHOP_NAME} · {config.SHOP_CONTACT}",
           font=small, fill="#555", anchor="rs")
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=95, dpi=(SHEET_DPI, SHEET_DPI))
    return buf.getvalue()
