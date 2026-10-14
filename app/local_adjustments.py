"""Included, deterministic pixel adjustments. No network or generative edits."""
import math

import cv2
import numpy as np

VERSION = "local-tones-v1"
CONTROLS = [
    dict(key="exposure", label="Exposure", minimum=-1.5, maximum=1.5, step=.1, unit="EV"),
    dict(key="brightness", label="Brightness", minimum=-20, maximum=20, step=1, unit=""),
    dict(key="temperature", label="White balance · cooler / warmer", minimum=-25, maximum=25, step=1, unit=""),
    dict(key="tint", label="White balance · green / magenta", minimum=-20, maximum=20, step=1, unit=""),
    dict(key="highlights", label="Reduce highlights / hotspots", minimum=0, maximum=100, step=1, unit="%"),
    dict(key="shadows", label="Lift dark tones", minimum=0, maximum=100, step=1, unit="%"),
    dict(key="contrast", label="Contrast", minimum=-20, maximum=20, step=1, unit=""),
    dict(key="saturation", label="Colour strength", minimum=-15, maximum=15, step=1, unit=""),
    dict(key="local_contrast", label="Local contrast", minimum=0, maximum=25, step=1, unit="%"),
]


def validate(values=None):
    if values is not None and not isinstance(values, dict):
        raise ValueError("Local adjustments must be a set of named values")
    values = values or {}
    if set(values) - {c["key"] for c in CONTROLS}:
        raise ValueError("Unknown local adjustment")
    result = {}
    for c in CONTROLS:
        try:
            v = float(values.get(c["key"], 0))
        except (ValueError, TypeError):
            raise ValueError("Invalid " + c["label"]) from None
        if not math.isfinite(v) or not c["minimum"] <= v <= c["maximum"]:
            raise ValueError("Out-of-range " + c["label"])
        result[c["key"]] = v
    return result


def apply(rgb, values=None):
    """Keep raster geometry unchanged; every setting starts from the source."""
    from .processing import _to_lin, _to_srgb
    v = validate(values)
    if not any(v.values()):
        return rgb, []
    lin = _to_lin(rgb.astype(np.float32) / 255)
    if v["temperature"] or v["tint"]:
        # Relative channel gains, normalized to retain luminance of neutral grey.
        gains = np.array([2**(v["temperature"]/100), 2**(-v["tint"]/100),
                          2**(-v["temperature"]/100)], np.float32)
        gains /= float(gains @ np.array([.2126,.7152,.0722]))
        lin *= gains
    lin *= 2**v["exposure"]
    y = lin @ np.array([.2126,.7152,.0722], np.float32)
    if v["shadows"]:
        weight = np.maximum(1 - y / .35, 0)**2
        lin *= np.exp2(.8 * v["shadows"]/100 * weight)[...,None]
    if v["highlights"]:
        # A monotone shoulder compresses bright tones. It does not recover detail
        # that was already absent in the camera file.
        y = lin @ np.array([.2126,.7152,.0722], np.float32)
        knee = .5
        over = np.maximum(y-knee, 0)
        strength = 1 + 3*v["highlights"]/100
        compressed = np.where(y > knee, knee + over/(1+strength*over), y)
        lin *= (compressed/np.maximum(y,1e-8))[...,None]
    out = _to_srgb(lin)
    if v["brightness"] or v["contrast"]:
        # Work in perceptual lightness, leaving Lab chroma intact.
        lab = cv2.cvtColor(out.astype(np.float32), cv2.COLOR_RGB2LAB)
        light = lab[...,0]
        light = (light-50) * 2**(v["contrast"]/50) + 50 + v["brightness"]*.5
        lab[...,0] = np.clip(light,0,100)
        out = np.clip(cv2.cvtColor(lab,cv2.COLOR_LAB2RGB),0,1)
    if v["saturation"]:
        luminance = out @ np.array([.2126,.7152,.0722], np.float32)
        out = np.clip(luminance[...,None] + (out-luminance[...,None])*(1+v["saturation"]/100),0,1)
    if v["local_contrast"]:
        byte = np.rint(out*255).astype(np.uint8)
        lab = cv2.cvtColor(byte,cv2.COLOR_RGB2LAB)
        enhanced = cv2.createCLAHE(clipLimit=1.5,tileGridSize=(8,8)).apply(lab[...,0])
        amount = v["local_contrast"]/100
        lab[...,0] = np.rint(lab[...,0]*(1-amount)+enhanced*amount).astype(np.uint8)
        candidate = cv2.cvtColor(lab,cv2.COLOR_LAB2RGB).astype(np.float32)/255
        out = candidate
    result = np.rint(np.clip(out,0,1)*255).astype(np.uint8)
    notes = [f"{c['label']}: {v[c['key']]:g}{(' '+c['unit']) if c['unit'] else ''}"
             for c in CONTROLS if v[c["key"]]]
    return result, notes
