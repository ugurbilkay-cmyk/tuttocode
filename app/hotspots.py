"""Regional highlight diagnostics, not a calibrated passport approval engine.

Measurements use the decoded image's native pixels. Landmarks locate estimated
facial regions; no skin-colour classifier or Photomatic score is substituted.
"""
import base64
import hashlib
import io

import cv2
import numpy as np
from PIL import Image

VERSION = "regional-highlights-v1"
MAX_PIXELS = 16_000_000
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
             397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
             172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
        308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78]
SETTINGS = {"near_clip_channel": 250, "bright_lightness": 80,
            "above_region_median": 15, "minimum_patch_pixels": 3}


def _preview(rgb):
    image = Image.fromarray(rgb)
    image.thumbnail((640, 800), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode()


def _polygon_mask(shape, points):
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], 1)
    return mask.astype(bool)


def measure(rgb, points, person_mask=None):
    """Return diagnostics and normalized overlay coordinates for one face."""
    from .processing import L_IRIS, R_IRIS, FOREHEAD, CHIN, NOSE, FACE_L, FACE_R, LEFT_EYE_RING, RIGHT_EYE_RING
    h, w = rgb.shape[:2]
    points = np.asarray(points, dtype=np.float64)
    if points.shape != (478, 2) or not np.isfinite(points).all():
        raise ValueError("Facial landmarks are incomplete")
    left, right = sorted((points[L_IRIS], points[R_IRIS]), key=lambda p: p[0])
    delta = right - left
    distance = float(np.linalg.norm(delta))
    if distance < 3:
        raise ValueError("Eye positions are too uncertain to locate facial regions")
    u = delta / distance
    v = np.array([-u[1], u[0]])
    origin = (left + right) / 2
    fw = float(np.linalg.norm(points[FACE_R] - points[FACE_L]))
    fh = float((points[CHIN] - points[FOREHEAD]) @ v)
    if fw < 15 or fh < 20:
        raise ValueError("Detected face is too small for regional diagnostics")
    oval = points[FACE_OVAL]
    if cv2.contourArea(oval.astype(np.float32)) < fw * fh * .2:
        raise ValueError("Face outline is too uncertain for regional diagnostics")
    valid = _polygon_mask((h, w), oval)
    if person_mask is not None:
        if person_mask.shape != (h, w) or not np.isfinite(person_mask).all():
            raise ValueError("Foreground mask is incomplete")
        valid &= person_mask > .5
    # Eye whites and lips are not forehead/cheek lighting defects. Glasses glare
    # remains a separate check. Feather-free exclusion keeps counts auditable.
    protected = np.zeros((h, w), bool)
    for indices in (LEFT_EYE_RING, RIGHT_EYE_RING, LIPS):
        hull = cv2.convexHull(points[indices].astype(np.float32)).reshape(-1, 2)
        protected |= _polygon_mask((h, w), hull)
    radius = max(1, round(fw * .015))
    protected = cv2.dilate(protected.astype(np.uint8),
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1,) * 2)).astype(bool)
    valid &= ~protected
    local = lambda point: np.array([(point - origin) @ u, (point - origin) @ v])
    forehead_y = local(points[FOREHEAD])[1]
    nose_y = local(points[NOSE])[1]
    mouth_y = local((points[61] + points[291]) / 2)[1]
    chin_y = local(points[CHIN])[1]
    definitions = [
        ("forehead", "Forehead", (0, forehead_y * .65), (.29 * fw, .13 * fh)),
        ("nose", "Nose", (0, nose_y), (.095 * fw, .16 * fh)),
        ("image_left_cheek", "Cheek · image left", (-.25 * fw, nose_y), (.16 * fw, .16 * fh)),
        ("image_right_cheek", "Cheek · image right", (.25 * fw, nose_y), (.16 * fw, .16 * fh)),
        ("chin", "Chin", (0, (mouth_y + chin_y) / 2), (.18 * fw, .07 * fh)),
    ]
    lightness = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32) * (100 / 255)
    near_any = rgb.max(axis=2) >= SETTINGS["near_clip_channel"]
    near_all = rgb.min(axis=2) >= SETTINGS["near_clip_channel"]
    union, candidates = np.zeros((h, w), bool), np.zeros((h, w), bool)
    rows, outlines = [], []
    angles = np.linspace(0, 2 * np.pi, 49)[:-1]
    for key, label, centre, axes in definitions:
        coords = origin + (centre[0] + axes[0] * np.cos(angles))[:, None] * u + (centre[1] + axes[1] * np.sin(angles))[:, None] * v
        region = _polygon_mask((h, w), coords) & valid
        count = int(region.sum())
        outlines.append({"label": label, "points": (coords / [w, h]).round(6).tolist()})
        row = {"key": key, "label": label, "pixels": count, "status": "measured" if count >= 20 else "unavailable"}
        if count < 20:
            rows.append(row)
            continue
        median = float(np.median(lightness[region]))
        bright = region & ((near_any) | ((lightness >= SETTINGS["bright_lightness"]) &
                                        (lightness >= median + SETTINGS["above_region_median"])))
        candidates |= bright
        union |= region
        pct = lambda mask: round(float((mask & region).sum()) * 100 / count, 3)
        row.update(median_lightness=round(median, 2), peak_lightness=round(float(lightness[region].max()), 2),
                   bright_percent=pct(bright), near_clip_any_percent=pct(near_any),
                   near_clip_all_percent=pct(near_all))
        rows.append(row)
    if not union.any():
        raise ValueError("Facial regions could not be measured")
    # Patches are visual candidates only; they never produce a pass/fail score.
    _, _, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), connectivity=8)
    patches = []
    minimum = max(SETTINGS["minimum_patch_pixels"], round(int(union.sum()) * .0002))
    for x, y, width, height, area in stats[1:]:
        if area >= minimum:
            patches.append({"box": [round(x / w, 6), round(y / h, 6), round(width / w, 6), round(height / h, 6)], "pixels": int(area)})
    patches.sort(key=lambda p: p["pixels"], reverse=True)
    return {"status": "diagnostic", "image_size": [w, h], "regions": rows,
            "outlines": outlines, "patches": patches[:100], "patch_count": len(patches),
            "overlay_truncated": len(patches) > 100, "inspected_pixels": int(union.sum()),
            "near_clip_all_percent": round(float((near_all & union).sum()) * 100 / int(union.sum()), 3),
            "protected_features": "Eye regions and lips excluded; glasses glare needs a separate check"}


def inspect_photo(data, analyzer=None):
    from . import processing
    report = {"engine": VERSION, "image_sha256": hashlib.sha256(data).hexdigest(),
              "settings": SETTINGS.copy(), "calibrated": False, "approval": "not_assessed"}
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("Image exceeds the regional inspector's pixel limit")
        rgb = processing.load_image(data)
        report.update(image_size=[rgb.shape[1], rgb.shape[0]], preview=_preview(rgb))
        analysis = (analyzer or processing.get_analyzer()).analyze(rgb)
        if len(analysis.faces) != 1:
            raise ValueError("Regional inspection requires one detected face")
        report.update(measure(rgb, analysis.faces[0].points, analysis.person_mask))
    except (ValueError, OSError) as exc:
        report.update(status="unavailable", message=str(exc))
    except Exception:
        report.update(status="unavailable", message="The facial-region engine is unavailable; review the photo manually")
    return report
