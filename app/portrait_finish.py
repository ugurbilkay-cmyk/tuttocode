"""Source-derived portrait diagnosis and restrained relative-highlight correction.

These measurements are appearance heuristics, not material/identity classifiers
or passport scores. Tone multiplies existing linear RGB; it never supplies pixels
from a generated face or claims to recover saturated source channels.
"""
import hashlib
import math

import cv2
import numpy as np

from . import hotspots

VERSION = 'portrait-finish-v1'


def _digest(rgb):
    return hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()


def _smooth(x):
    x = np.clip(x, 0, 1)
    return x*x*(3-2*x)


def _linear(rgb):
    x = rgb.astype(np.float32)/255
    return np.where(x <= .04045, x/12.92, ((x+.055)/1.055)**2.4)


def _weighted(value, weight, sigma):
    prior = float(np.median(value[weight > .2]))
    numerator = cv2.GaussianBlur(value*weight, (0, 0), sigma)
    denominator = cv2.GaussianBlur(weight, (0, 0), sigma)
    return (numerator+1e-5*prior)/(denominator+1e-5)


def analyse(rgb, points, person_mask=None, keep=None):
    """Diagnose one source grid; internal arrays must not be saved as JSON."""
    before = hotspots.measure(rgb, points, person_mask, include_masks=True)
    points = np.asarray(points)
    shape = rgb.shape[:2]
    width = float(np.linalg.norm(points[454]-points[234]))
    oval = hotspots._polygon_mask(shape, points[hotspots.FACE_OVAL])
    distance = cv2.distanceTransform(oval.astype(np.uint8), cv2.DIST_L2, 5)
    face_alpha = _smooth(distance/max(2, width*.20)).astype(np.float32)
    if person_mask is not None:
        face_alpha *= np.clip((person_mask-.5)*2, 0, 1)
    valid = before['_skin_mask'] & (face_alpha > .05)
    if valid.sum() < 100:
        raise ValueError('Too little measurable facial skin for portrait diagnosis')
    weight = valid.astype(np.float32)
    lab = cv2.cvtColor(rgb.astype(np.float32)/255, cv2.COLOR_RGB2LAB)
    lightness = lab[..., 0]
    luminance = _linear(rgb) @ np.array([.2126, .7152, .0722], np.float32)
    log_light = np.log2(np.maximum(luminance, 1e-5))
    fine = _weighted(log_light, weight, max(1, width*.005))
    broad = _weighted(fine, weight, max(2, width*.06))
    relative = fine-broad
    chroma = _weighted(np.linalg.norm(lab[..., 1:], axis=2), weight, max(1, width*.008))
    near_clip = rgb.max(axis=2) >= 250
    saturated = (rgb == 255).any(axis=2)
    shine = np.zeros(shape, np.float32)
    rows = []
    cleanup_region = np.zeros(shape, bool)
    for index, row in enumerate(before['regions']):
        coords = np.asarray(before['outlines'][index]['points'])*[shape[1], shape[0]]
        region = hotspots._polygon_mask(shape, coords) & valid
        if region.sum() < 20:
            rows.append(dict(region=row['key'], status='unavailable'))
            continue
        if index in (0, 2, 3):
            part = region.copy()
            if index in (2, 3):
                part &= np.indices(shape)[0] < float((points[1, 1]+points[61, 1])/2)
            cleanup_region |= part
        upper_start = float(np.percentile(fine[region], 65))
        diffuse = region & (fine <= upper_start)
        own_chroma = float(np.median(chroma[diffuse]))
        chroma_loss = np.clip((own_chroma-chroma)/max(own_chroma, 6), 0, 1)
        upper = _smooth((fine-upper_start)/.20)
        colour_cue = _smooth((chroma_loss-.01)/.08)
        # Relative brightness is necessary; chroma dilution strengthens evidence
        # but is not a skin-colour target or proof of specular reflection.
        need = np.clip(relative-.08, 0, .8)*upper*(.5+.5*colour_cue)
        region_distance = cv2.distanceTransform(region.astype(np.uint8), cv2.DIST_L2, 5)
        need *= _smooth(region_distance/max(1, width*.025))
        need[~region | near_clip] = 0
        shine = np.maximum(shine, need)
        candidates = region & (need > .02)
        rows.append(dict(region=row['key'], status='measured', pixels=int(region.sum()),
            relative_highlight_pixels=int(candidates.sum()),
            relative_highlight_percent=round(float(candidates.sum()/region.sum()*100), 3),
            relative_luminance_ev_p95=round(float(np.percentile(relative[region], 95)), 4),
            regional_chroma_reference=round(own_chroma, 4),
            highlight_chroma_loss=round(float(np.median(chroma_loss[candidates])), 4) if candidates.any() else 0.))
    shine = cv2.GaussianBlur(shine, (0, 0), max(1, width*.012))
    shine[~oval] = 0
    features = oval & ~before['_skin_mask']
    for index in (468, 473, 1):
        feature = np.zeros(shape, np.uint8)
        x, y = points[index]
        axes = (max(2, round(width*.15)), max(2, round(width*.09))) if index != 1 else (max(1, round(width*.065)), max(1, round(width*.04)))
        cv2.ellipse(feature, (round(x), round(y-width*.025 if index != 1 else y)), axes, 0, 0, 360, 1, -1)
        features |= feature.astype(bool)
    broad_l = _weighted(lightness, weight, max(2, width*.02))
    marks = valid & ((broad_l-lightness) > 7)
    marks = cv2.dilate(marks.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    for x, y, radius in keep or []:
        if not all(math.isfinite(float(v)) for v in (x, y, radius)):
            raise ValueError('Invalid preserved skin area')
        cv2.circle(marks.view(np.uint8), (round(x*shape[1]), round(y*shape[0])), max(1, round(radius*min(shape))), 1, -1)
    cleanup = cleanup_region.astype(np.float32)*face_alpha
    cleanup = cv2.GaussianBlur(cleanup, (0, 0), max(.6, width*.008))
    cleanup[~cleanup_region | features | marks | near_clip] = 0
    texture_mask = cleanup > .2
    residual = lightness-cv2.GaussianBlur(lightness, (0, 0), 1.2)
    texture_rms = float(np.sqrt(np.mean(residual[texture_mask]**2))) if texture_mask.sum() >= 100 else None
    texture_need = float(np.clip((texture_rms-.35)/2, 0, 1)) if texture_rms is not None else 0.
    report = dict(version=VERSION, status='measured', source_rgb_sha256=_digest(rgb),
        analysis_size=[shape[1], shape[0]], regions=rows,
        relative_highlight_pixels=int((shine*face_alpha > .02).sum()),
        maximum_relative_highlight_ev=round(float(shine.max()), 4),
        near_clip_any_pixels=int((near_clip & oval).sum()),
        saturated_source_channel_pixels=int((saturated & oval).sum()),
        texture_residual_rms_L=round(texture_rms, 4) if texture_rms is not None else None,
        texture_need=round(texture_need, 4), feature_pixels=int(features.sum()), mark_pixels=int(marks.sum()),
        method='Own-region luminance upper tail, masked log-luminance contrast and relative chroma dilution',
        limitation='Trial appearance cues; highlights are not a material classification. Texture includes noise and pores; saturated channels contain no recoverable source detail.')
    return dict(report=report, _face_alpha=face_alpha, _cleanup_alpha=cleanup,
        _feature_mask=features, _mark_mask=marks, _clipped_mask=near_clip,
        _highlight_ev=shine, _shape=shape)


def highlight_gain(analysis, shape, budget):
    """Return the reusable, same-channel scalar tone field on a requested grid."""
    maximum = float(budget.get('max_highlight_ev', 0)) if isinstance(budget, dict) else float(budget)
    if not math.isfinite(maximum) or not 0 <= maximum <= 1:
        raise ValueError('Invalid highlight correction budget')
    height, width = map(int, shape[:2])
    if min(height, width) < 1:
        raise ValueError('Invalid highlight output grid')
    field = np.minimum(analysis['_highlight_ev'], maximum)*analysis['_face_alpha']
    field = cv2.resize(field, (width, height), interpolation=cv2.INTER_LINEAR)
    # Interpolation remains inside the original oval; no spill into the backdrop.
    support = cv2.resize((analysis['_face_alpha'] > 0).astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST)
    field[support == 0] = 0
    return np.exp2(-field).astype(np.float32)


def apply_highlights(rgb, analysis, budget):
    gain = highlight_gain(analysis, rgb.shape[:2], budget)
    linear = np.clip(_linear(rgb)*gain[..., None], 0, 1)
    rendered = np.rint(np.clip(np.where(linear <= .0031308, linear*12.92, 1.055*linear**(1/2.4)-.055), 0, 1)*255).astype(np.uint8)
    near_clip = rgb.max(axis=2) >= 250
    rendered[near_clip | (gain == 1)] = rgb[near_clip | (gain == 1)]
    changed = int(np.any(rendered != rgb, axis=2).sum())
    maximum = float(budget.get('max_highlight_ev', 0)) if isinstance(budget, dict) else float(budget)
    stage = dict(version=VERSION, phase='adaptive_highlights', models=[],
        status='applied' if changed else 'unchanged', edited_pixels=changed,
        maximum_highlight_ev=round(float(-np.log2(gain.min())), 4), budget_ev=maximum,
        source_rgb_sha256=_digest(rgb), diagnosis_source_rgb_sha256=analysis['report']['source_rgb_sha256'],
        output_rgb_sha256=_digest(rendered), source_size=[rgb.shape[1], rgb.shape[0]],
        output_size=[rgb.shape[1], rgb.shape[0]],
        analysis_near_clip_any_pixels=analysis['report']['near_clip_any_pixels'],
        current_near_clip_any_pixels=int(near_clip.sum()),
        current_near_clip_pixels_retained_exact=bool(np.array_equal(rendered[near_clip], rgb[near_clip])),
        saturated_channel_pixels_remaining=int((rendered == 255).any(axis=2).sum()),
        detail_method='Smooth negative EV multiplies existing linear RGB equally; no replacement detail or geometric transform',
        message='Relative facial highlights softened; existing clipped samples retained without claiming recovered detail' if changed else 'No relative highlight correction selected')
    return rendered, stage
