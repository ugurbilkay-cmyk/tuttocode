"""Local spot repair with protected facial features and auditable edit masks."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np
from PIL import Image

from . import background,config,enhancement,enhancement_models as models,skin

VERSION='local-blemish-v1'


def png(image):
    stream=io.BytesIO();Image.fromarray(image).save(stream,'PNG');return stream.getvalue()


def apply(rgb,points,values):
    v=enhancement.validate(values)
    record=dict(phase='blemish',status='unchanged',models=[],version=VERSION,settings=v)
    if not v['blemish']:return rgb,record,{}
    spec=models.MODELS['blemish'];checkpoint=config.ENHANCER_MODEL_DIR/'blemish/joint_20210926.pth'
    if not checkpoint.is_file():
        record.update(status='unavailable',message='Advanced skin model needs local setup; no spot repair applied')
        return rgb,record,{}
    try:
        if points is None:raise ValueError('No face landmarks')
        before,allowed,protected,_=skin.protection(rgb,points,v['blemish_keep'])
    except (ValueError,cv2.error):
        record.update(status='unavailable',message='Advanced skin cleaning skipped: facial regions could not be located reliably')
        return rgb,record,{}
    h,w=rgb.shape[:2]
    from . import hotspots
    outline=np.asarray(points)[hotspots.FACE_OVAL]
    left,top=outline.min(axis=0);right,bottom=outline.max(axis=0)
    side=max(right-left,bottom-top)*1.5;cx,cy=(left+right)/2,(top+bottom)/2
    roi=[max(0,int(cx-side/2)),max(0,int(cy-side/2)),min(w,int(np.ceil(cx+side/2))),min(h,int(np.ceil(cy+side/2)))]
    source_hash=hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='tuttocode-skin-cleaning-') as directory:
        directory=Path(directory);source=directory/'source.png';permit=directory/'allowed.npy';target=directory/'result.png'
        Image.fromarray(rgb).save(source);np.save(permit,allowed.astype(np.float32),allow_pickle=False)
        args=[config.ENHANCER_PYTHON,str(config.BASE_DIR/'scripts/blemish_worker.py'),
              '--models',str(config.ENHANCER_MODEL_DIR.resolve()),'--input',str(source),'--allowed',str(permit),
              '--output',str(target),'--roi',json.dumps(roi),'--settings',json.dumps(v)]
        try:
            with background._worker_slot():
                reply=subprocess.run(args,capture_output=True,timeout=config.ENHANCER_TIMEOUT_SECONDS,
                    env=background._worker_environment(),check=False)
            if reply.returncode or not target.is_file():raise ValueError('Repair worker failed')
            with Image.open(target) as image:
                if image.mode!='RGB' or image.size!=(w,h):raise ValueError('Invalid repaired image')
                out=np.array(image)
            mask=np.load(target.with_suffix('.npy'),allow_pickle=False)
            evidence=json.loads(target.with_suffix('.json').read_text())
            if (mask.shape!=(h,w) or not np.isfinite(mask).all() or mask.min()<0 or
                (mask>allowed*v['blemish']/100+1e-5).any()):raise ValueError('Invalid repair mask')
            if (evidence['engine']!='blemish' or evidence['model_sha256']!=spec['files']['joint_20210926.pth'] or
                evidence['code_revision']!=models.BLEMISH_CODE_REVISION or evidence['settings']!=v or
                evidence['source_size']!=[w,h] or evidence['roi']!=roi or evidence['mask_sha256']!=
                hashlib.sha256(mask.astype('<f4').tobytes()).hexdigest()):raise ValueError('Incorrect repair provenance')
        except (subprocess.TimeoutExpired,OSError,ValueError,KeyError,TypeError,EOFError,background.Unavailable):
            record.update(status='unavailable',message='Local skin cleaning could not finish; photo left unchanged. Retry or reduce selected tools.')
            return rgb,record,{}
    # Enforce the permitted support independently of the learned worker.
    out[mask<=0]=rgb[mask<=0]
    out,after,reverted=skin.guard(rgb,out,points,before,protected)
    changed=np.any(out!=rgb,axis=2)
    actual_mask=np.rint(np.where(changed,mask,0)*255).astype(np.uint8)
    model=dict(engine='blemish',label=spec['label'],licence=spec['licence'],repository=spec['repository'],
               model_sha256=evidence['model_sha256'],code_revision=evidence['code_revision'])
    record.update(status='applied',models=[model],inference_seconds=evidence['inference_seconds'],
        source_size=[w,h],output_size=[w,h],candidate_spots=evidence['candidate_spots'],
        edited_pixels=int(changed.sum()),kept_areas=len(v['blemish_keep']),reverted_regions=reverted,
        before_hotspots=skin._diagnostic(before),after_hotspots=skin._diagnostic(after),
        preserved_hotspot_pixels=bool(np.array_equal(out[before['_candidate_mask']],rgb[before['_candidate_mask']])),
        source_rgb_sha256=source_hash,output_rgb_sha256=hashlib.sha256(out.tobytes()).hexdigest(),
        mask_sha256=hashlib.sha256(actual_mask.tobytes()).hexdigest(),
        message=f"{evidence['candidate_spots']} permitted spot candidates · {int(changed.sum())} pixels repaired · review the repair mask")
    return out,record,dict(before=png(rgb),after=png(out),mask=png(actual_mask))
