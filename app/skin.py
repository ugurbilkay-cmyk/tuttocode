"""Landmark-guided texture softening; protect highlight pixels and detector evidence."""
import hashlib

import cv2
import numpy as np

from . import hotspots

VERSION = 'skin-texture-v1'


def _diagnostic(report):
    return {key:report[key] for key in ('regions','patch_count','near_clip_all_percent','inspected_pixels')}


def protection(rgb,points,keep_areas=None):
    """Shared editable skin alpha and exact protected highlights/features."""
    from .processing import FACE_L,FACE_R,L_IRIS,R_IRIS,NOSE
    before=hotspots.measure(rgb,points,include_masks=True)
    points=np.asarray(points)
    width=float(np.linalg.norm(points[FACE_R]-points[FACE_L]))
    radius=max(1,round(width*.025))
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,)*2)
    valid=before['_skin_mask']
    alpha=cv2.erode(valid.astype(np.uint8),kernel).astype(np.float32)
    alpha=np.clip(cv2.GaussianBlur(alpha,(0,0),max(.6,width*.008)),0,1)
    alpha[~valid]=0
    lab=cv2.cvtColor(rgb.astype(np.float32)/255,cv2.COLOR_RGB2LAB)
    # Keep current hotspot candidates, near-clipped channels and high highlights
    # exact, including a narrow surround. They are not made to look like a pass.
    protected=before['_candidate_mask'] | (rgb.max(axis=2)>=hotspots.SETTINGS['near_clip_channel']) | (lab[...,0]>=78)
    for index in (L_IRIS,R_IRIS):
        feature=np.zeros(rgb.shape[:2],np.uint8)
        x,y=points[index]
        cv2.ellipse(feature,(round(x),round(y-width*.025)),
                    (max(2,round(width*.15)),max(2,round(width*.09))),0,0,360,1,-1)
        protected |= feature.astype(bool)
    # The nose tip/nostril boundary and the eye/lip masks from the inspector
    # remain source pixels; strong edges receive less filtering elsewhere.
    feature=np.zeros(rgb.shape[:2],np.uint8)
    cv2.ellipse(feature,tuple(np.rint(points[NOSE]).astype(int)),
                (max(1,round(width*.065)),max(1,round(width*.04))),0,0,360,1,-1)
    protected |= feature.astype(bool)
    for x,y,r in keep_areas or []:
        feature=np.zeros(rgb.shape[:2],np.uint8)
        cv2.circle(feature,(round(x*rgb.shape[1]),round(y*rgb.shape[0])),
                   max(1,round(r*min(rgb.shape[:2]))),1,-1)
        protected |= feature.astype(bool)
    protected=cv2.dilate(protected.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))).astype(bool)
    alpha[protected]=0
    return before,alpha,protected,lab


def guard(rgb,out,points,before,protected):
    """Preserve regional highlight evidence after either smoothing or spot repair."""
    valid=before['_skin_mask']
    out=out.copy();out[protected | ~valid]=rgb[protected | ~valid]
    reverted=set()
    guards=('peak_lightness','bright_percent','near_clip_any_percent','near_clip_all_percent')
    for _ in range(3):
        after=hotspots.measure(out,points,include_masks=True)
        changed=[i for i,(a,b) in enumerate(zip(before['regions'],after['regions']))
                 if any(a.get(key)!=b.get(key) for key in guards)]
        if not changed:break
        for index in changed:
            reverted.add(before['regions'][index]['key'])
            coords=np.asarray(before['outlines'][index]['points'])*[rgb.shape[1],rgb.shape[0]]
            region=hotspots._polygon_mask(rgb.shape[:2],coords)
            out[region]=rgb[region]
    after=hotspots.measure(out,points,include_masks=True)
    if any(any(a.get(key)!=b.get(key) for key in guards) for a,b in zip(before['regions'],after['regions'])):
        out[before['_inspected_mask']]=rgb[before['_inspected_mask']]
        after=hotspots.measure(out,points,include_masks=True)
        reverted.update(row['key'] for row in before['regions'])
    return out,after,sorted(reverted)


def apply(rgb,points,strength,keep_areas=None):
    """Work on skin texture, not geometric features or a lighting correction."""
    if not 0<=strength<=100:raise ValueError('Invalid skin smoothing strength')
    if not strength:return rgb,dict(status='unchanged',phase='skin',models=[],strength=0)
    points=np.asarray(points)
    before,alpha,protected,lab=protection(rgb,points,keep_areas)
    valid=before['_skin_mask']
    from .processing import FACE_L,FACE_R
    width=float(np.linalg.norm(points[FACE_R]-points[FACE_L]))
    gradient=cv2.magnitude(cv2.Sobel(lab[...,0],cv2.CV_32F,1,0,ksize=3),cv2.Sobel(lab[...,0],cv2.CV_32F,0,1,ksize=3))
    alpha *= 1/(1+(gradient/18)**4)
    # A small, edge-aware base removes fine texture while retaining the broad
    # illumination field. Chroma filtering is weaker than lightness filtering.
    sigma=max(1.,min(4.,width/100))
    filtered=lab.copy()
    for channel in range(3):
        filtered[...,channel]=cv2.bilateralFilter(lab[...,channel],9,8 if channel==0 else 6,sigma)
    weight=alpha[...,None]*strength/100*np.array([1,.35,.35],np.float32)
    mixed=lab*(1-weight)+filtered*weight
    rendered=np.rint(np.clip(cv2.cvtColor(mixed,cv2.COLOR_LAB2RGB),0,1)*255).astype(np.uint8)
    out=rgb.copy();editable=alpha>.001;out[editable]=rendered[editable]
    # Bright candidate classifications also depend on regional medians. Restore
    # a region if smoothing changes its diagnostic highlight/clip counts or peak.
    # This is an edit safeguard, not a code-issuance restriction.
    out,after,reverted=guard(rgb,out,points,before,protected)
    # Pixel values at protected highlights and facial features remain exact.
    out[protected | ~valid]=rgb[protected | ~valid]
    delta=cv2.cvtColor(out.astype(np.float32)/255,cv2.COLOR_RGB2LAB)[...,0]-lab[...,0]
    return out,dict(phase='skin',models=[],status='applied',version=VERSION,strength=strength,
        message=f'Edge-aware skin smoothing {strength:g}% · highlights and facial features protected',
        protected_pixels=int((protected & valid).sum()),edited_pixels=int(np.any(out!=rgb,axis=2).sum()),
        preserved_hotspot_pixels=bool(np.array_equal(out[before['_candidate_mask']],rgb[before['_candidate_mask']])),
        reverted_regions=sorted(reverted),before_hotspots=_diagnostic(before),after_hotspots=_diagnostic(after),
        mean_skin_lightness_change=round(float(delta[valid].mean()),4),source_size=[rgb.shape[1],rgb.shape[0]],
        output_size=[rgb.shape[1],rgb.shape[0]],source_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),
        output_rgb_sha256=hashlib.sha256(out.tobytes()).hexdigest())
