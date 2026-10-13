"""Optional local enhancement, isolated from API credentials and web dependencies."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np
from PIL import Image

from . import config, background, enhancement_models as models

CONTROLS = [
    dict(key="lighting", label="Low-light recovery", unit="%", minimum=0, maximum=100, step=5),
    dict(key="denoise", label="Noise cleanup", unit="%", minimum=0, maximum=100, step=5),
    dict(key="detail", label="Detail sharpening", unit="%", minimum=0, maximum=100, step=5),
    dict(key="skin", label="Skin smoothing · protect hotspots", unit="%", minimum=0, maximum=100, step=5),
    dict(key="upscale_strength", label="AI upscale strength", unit="%", minimum=0, maximum=100, step=5),
]
DEFAULTS = dict(lighting=0., denoise=0., detail=0., skin=0., scale=1, upscale_strength=70., upscale_engine='plksr')
PRESETS = {
    "natural": dict(label="Natural portrait", enhancement=dict(lighting=0,denoise=15,detail=10,skin=20,scale=1),
                    adjustments={}, auto_adjust=True, fix_shadows=False),
    "lowlight": dict(label="Difficult lighting", enhancement=dict(lighting=50,denoise=25,detail=5,skin=25,scale=1),
                     adjustments={"highlights":20}, auto_adjust=False, fix_shadows=False),
    "clean": dict(label="Clean detail", enhancement=dict(lighting=0,denoise=35,detail=20,skin=25,scale=1),
                  adjustments={}, auto_adjust=False, fix_shadows=False),
    "small": dict(label="Small photo / larger print", enhancement=dict(lighting=0,denoise=15,detail=5,skin=20,scale=2,upscale_strength=70),
                  adjustments={}, auto_adjust=False, fix_shadows=False),
}


def validate(values=None):
    if values is not None and not isinstance(values,dict):
        raise ValueError("Enhancer settings must be named values")
    values = values or {}
    if set(values)-set(DEFAULTS): raise ValueError("Unknown enhancer setting")
    result = {}
    for key, default in DEFAULTS.items():
        if key=='upscale_engine':
            value=values.get(key,default)
            if value not in ('plksr','realesrgan','lanczos'): raise ValueError('Unknown enlargement engine')
            result[key]=value
            continue
        try: value=float(values.get(key,default))
        except (ValueError,TypeError): raise ValueError("Invalid enhancer setting: "+key) from None
        if not math.isfinite(value) or (value not in (1,2,4) if key=="scale" else not 0<=value<=100):
            raise ValueError("Out-of-range enhancer setting: "+key)
        result[key]=int(value) if key=="scale" else value
    return result


def active(values=None):
    v=validate(values)
    return bool(v['lighting'] or v['denoise'] or v['detail'] or v['skin'] or v['scale']!=1)


def choices():
    return {key: all((config.ENHANCER_MODEL_DIR/key/name).is_file() for name in spec['files'])
            for key,spec in models.MODELS.items()}


def required(values,phase):
    v=validate(values)
    if phase=='restore': return [name for name,key in [('retinex','lighting'),('nafnet','denoise')] if v[key]]
    if phase=='upscale': return [v['upscale_engine']] if v['scale']!=1 and v['upscale_strength'] and v['upscale_engine']!='lanczos' else []
    raise ValueError("Unknown enhancement phase")


def apply(rgb,values=None,phase='restore'):
    """Return raster + evidence. Failures are warnings and preserve this stage's input."""
    v=validate(values); engines=required(v,phase)
    factor=v['scale'] if phase=='upscale' else 1
    evidence=dict(version=models.VERSION,phase=phase,settings=v,source_size=[rgb.shape[1],rgb.shape[0]],
                  models=[],status='unchanged')
    out=rgb
    if engines:
        if any(not (config.ENHANCER_MODEL_DIR/name/file).is_file() for name in engines for file in models.MODELS[name]['files']):
            evidence.update(status='unavailable',message='Selected enhancer model needs local setup; this stage was left unchanged')
            return rgb,evidence
        with tempfile.TemporaryDirectory(prefix='tuttocode-enhancer-') as folder:
            folder=Path(folder);source=folder/'source.png';target=folder/'result.png'
            Image.fromarray(rgb).save(source)
            args=[config.ENHANCER_PYTHON,str(config.BASE_DIR/'scripts/enhancement_worker.py'),
                  '--models',str(config.ENHANCER_MODEL_DIR.resolve()),'--input',str(source),'--output',str(target),
                  '--phase',phase,'--settings',json.dumps(v)]
            try:
                with background._worker_slot():
                    reply=subprocess.run(args,capture_output=True,timeout=config.ENHANCER_TIMEOUT_SECONDS,
                                         env=background._worker_environment(),check=False)
                if reply.returncode or not target.is_file(): raise ValueError('worker failed')
                with Image.open(target) as image:
                    if image.mode!='RGB' or image.size!=(rgb.shape[1]*factor,rgb.shape[0]*factor):
                        raise ValueError('invalid raster')
                    out=np.array(image)
                reported=json.loads(target.with_suffix('.json').read_text())
                if reported['phase']!=phase or reported['settings']!=v or reported['source_size']!=evidence['source_size']:
                    raise ValueError('invalid provenance')
                actual={item['engine']:item for item in reported['models']}
                if set(actual)!=set(engines): raise ValueError('missing provenance')
                for name in engines:
                    filename=f'model_x{factor}.onnx' if name=='plksr' else 'model.onnx' if name=='nafnet' else 'general.pth' if name=='realesrgan' else 'model.pth'
                    if actual[name]['model_sha256']!=models.MODELS[name]['files'][filename]: raise ValueError('wrong model')
                    if name=='realesrgan' and actual[name]['secondary_model_sha256']!=models.MODELS[name]['files']['general-wdn.pth']:
                        raise ValueError('wrong secondary model')
                evidence.update(reported,status='applied')
            except (subprocess.TimeoutExpired,OSError,ValueError,KeyError,TypeError,background.Unavailable):
                evidence.update(status='unavailable',message='Local enhancement could not finish; this stage was left unchanged. Retry or reduce selected tools.')
                return rgb,evidence
    elif factor!=1:
        out=cv2.resize(rgb,(rgb.shape[1]*factor,rgb.shape[0]*factor),interpolation=cv2.INTER_LANCZOS4)
        evidence.update(status='applied',method='Standard Lanczos enlargement')
    if phase=='restore' and v['detail']:
        # Thresholded lightness-only unsharp mask: no face reconstruction.
        lab=cv2.cvtColor(out.astype(np.float32)/255,cv2.COLOR_RGB2LAB)
        residual=lab[...,0]-cv2.GaussianBlur(lab[...,0],(0,0),.8)
        residual=np.where(np.abs(residual)>1.2,np.clip(residual,-8,8),0)
        lab[...,0]=np.clip(lab[...,0]+residual*v['detail']/100,0,100)
        out=np.rint(np.clip(cv2.cvtColor(lab,cv2.COLOR_LAB2RGB),0,1)*255).astype(np.uint8)
        evidence.update(status='applied',detail_method='thresholded lightness unsharp mask')
    evidence.update(output_size=[out.shape[1],out.shape[0]],
        source_rgb_sha256=hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest(),
        output_rgb_sha256=hashlib.sha256(np.ascontiguousarray(out).tobytes()).hexdigest())
    return out,evidence
