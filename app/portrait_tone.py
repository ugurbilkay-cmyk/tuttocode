"""Opt-in source-pixel tone separation. No reference images or face synthesis.

An appearance-calibration starting point, not a demographic classifier or a
passport verdict. Skin midtones, dark structure and nose highlights receive
different bounded adjustments; geometry and the background remain unchanged.
"""
import hashlib
import math

import cv2
import numpy as np

from . import hotspots

VERSION = 'portrait-tone-v1'


def _smooth(value):
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def apply(rgb, points, strength, person_mask=None, background_colour=None):
    if not math.isfinite(float(strength)) or not 0 <= strength <= 100:
        raise ValueError('Invalid portrait tone strength')
    if not strength:
        return rgb, dict(phase='portrait_tone', models=[], status='unchanged', strength=0)
    # Reuse validated facial geometry; no skin-colour or identity classification.
    before = hotspots.measure(rgb, points, person_mask, include_masks=True)
    points = np.asarray(points)
    from .processing import FACE_L, FACE_R, NOSE
    h, w = rgb.shape[:2]
    width = float(np.linalg.norm(points[FACE_R] - points[FACE_L]))
    oval = hotspots._polygon_mask((h, w), points[hotspots.FACE_OVAL])
    distance = cv2.distanceTransform(oval.astype(np.uint8), cv2.DIST_L2, 5)
    # Feather inward: no inferred neckline or garment receives facial tones.
    face = _smooth(distance / max(1, width * .045))
    x = np.arange(w, dtype=np.float32)[None, :]
    y = np.arange(h, dtype=np.float32)[:, None]
    lab = cv2.cvtColor(rgb.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    lightness = lab[..., 0]
    # Nonlinear tone curves on individual pixels amplify fine grain and beard
    # texture. Derive a smooth source-guided illumination delta instead; retain
    # the existing high-frequency pixel residual in the final raster.
    from .skin_guided import _guided
    radius = max(2, min(48, round(width * .025)))
    base, algorithm = _guided(lightness, radius, 100)
    colour_base = cv2.GaussianBlur(lab[..., 1:], (0, 0), max(1, width * .012))
    midtones = _smooth((base - 25) / 25)
    dark = _smooth((base - 8) / 16) * (1 - _smooth((base - 25) / 20))
    rolloff = 1 - _smooth((base - 65) / 20)
    chroma = _smooth((np.hypot(colour_base[..., 0], colour_base[..., 1]) - 8) / 20)
    if person_mask is not None:face *= np.clip(person_mask, 0, 1)
    nose = points[NOSE]
    reserve = np.exp(-.5 * (((x - nose[0]) / (width * .115)) ** 2 + ((y - nose[1]) / (width * .22)) ** 2))
    level = strength / 100
    # Limit all changes near already-bright RGB pixels, including chroma shifts.
    alpha = face * level * (1 - _smooth((rgb.max(axis=2) - 220.) / 25))
    delta_l = ((6.8 * midtones * (1 - .57 * reserve) - 5.5 * dark) * rolloff) * alpha
    delta_a = (4.5 * chroma + 1 * (1 - chroma)) * alpha
    delta_b = np.clip(1.5 + .35 * (27 - colour_base[..., 1]), -4, 5) * chroma * alpha
    edited = lab.copy()
    edited[..., 0] = np.clip(lightness + delta_l, 0, 100)
    edited[..., 1] += delta_a
    edited[..., 2] += delta_b
    candidate = np.rint(np.clip(cv2.cvtColor(edited, cv2.COLOR_LAB2RGB), 0, 1) * 255).astype(np.uint8)
    out = rgb.copy()
    editable = alpha > .001
    out[editable] = candidate[editable]
    # Retain bright source samples rather than introducing a new clipped sample.
    # This is a raster edit; final JPEG diagnostics are measured independently.
    rejected = editable & (out.max(axis=2) >= 247) & (rgb.max(axis=2) < 247)
    out[rejected] = rgb[rejected]
    background_pixels = 0
    if background_colour is not None and person_mask is not None:
        pure_background = person_mask < .001
        out[pure_background] = background_colour
        background_pixels = int(pure_background.sum())
    after = hotspots.measure(out, points, person_mask)
    from .skin import _diagnostic
    return out, dict(phase='portrait_tone', models=[], status='applied', version=VERSION,
        strength=float(strength), method='Source-guided illumination field, Lab midtones, dark contrast and nose-gain reservation',
        illumination_filter=algorithm, illumination_radius=radius, illumination_epsilon_L2=100,
        message=f'Local skin lighting and contrast {strength:g}% · source pixels, fixed geometry',
        source_size=[w, h], output_size=[w, h], edited_pixels=int(np.any(out != rgb, axis=2).sum()),
        retained_bright_pixels=int(rejected.sum()), document_background_pixels=background_pixels,
        before_hotspots=_diagnostic(before), after_hotspots=_diagnostic(after),
        source_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(), output_rgb_sha256=hashlib.sha256(out.tobytes()).hexdigest())
