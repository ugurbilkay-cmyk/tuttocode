"""Opt-in source-guided regional texture finish. No target image/model/reconstructed face.

Guided filter: He/Sun/Tang, ECCV2010 https://people.csail.mit.edu/kaiming/eccv10/index.html
The fallback is the directly implemented local-linear/box-filter algorithm,
not a hidden Gaussian substitution. Intended for opt-in image finishing;
regional diagnostics are recomputed, not held to artificial prior scores.
"""
import hashlib
import math
import cv2
import numpy as np
from . import skin,hotspots

def _guided(lightness,radius,epsilon):
    if hasattr(cv2,'ximgproc') and hasattr(cv2.ximgproc,'guidedFilter'):
        return cv2.ximgproc.guidedFilter(lightness,lightness,radius,epsilon), 'opencv-ximgproc-guided-filter'
    box=lambda x:cv2.boxFilter(x,cv2.CV_32F,(2*radius+1,2*radius+1),borderType=cv2.BORDER_REFLECT)
    mean=box(lightness);variance=np.maximum(box(lightness*lightness)-mean*mean,0)
    a=variance/(variance+epsilon);b=mean-a*mean
    return box(a)*lightness+box(b), 'opencv-box-guided-filter'

def apply(rgb,points,strength,keep_areas=None):
    if not math.isfinite(float(strength)) or not 0<=strength<=100:
        raise ValueError('Invalid guided skin strength')
    if not strength:
        return rgb,dict(status='unchanged',phase='skin',models=[],method='guided',strength=0)
    from .processing import FACE_L,FACE_R,FOREHEAD,CHIN,L_IRIS,R_IRIS,NOSE
    points=np.asarray(points)
    if points.shape!=(478,2) or not np.isfinite(points).all():
        raise ValueError('Facial landmarks are incomplete')
    before,base_alpha,protected,lab=skin.protection(rgb,points,keep_areas)
    L=lab[...,0];fw=float(np.linalg.norm(points[FACE_R]-points[FACE_L]))
    left,right=sorted((points[L_IRIS],points[R_IRIS]),key=lambda p:p[0]);u=(right-left)/np.linalg.norm(right-left);v=np.array([-u[1],u[0]])
    y=np.indices(rgb.shape[:2],dtype=np.float32)
    ylocal=(y[1]-points[NOSE,0])*v[0]+(y[0]-points[NOSE,1])*v[1]
    fh=float((points[CHIN]-points[FOREHEAD])@v)
    # Persistent contrast and texture edges remain. Keep inferred dark marks;
    # users can supply explicit keep circles for distinguishing marks as well.
    broad=cv2.GaussianBlur(L,(0,0),max(2,fw*.02))
    marks=(broad-L)>9
    radius=max(1,round(fw*.004))
    marks=cv2.dilate(marks.astype('uint8'),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,)*2)).astype(bool)
    protected=protected|marks
    # Preserve each regional absolute maximum exactly as source pixels.
    for outline in before['outlines']:
        coords=np.asarray(outline['points'])*[rgb.shape[1],rgb.shape[0]]
        region=hotspots._polygon_mask(rgb.shape[:2],coords)&before['_skin_mask']
        if region.any():protected|=region&(L>=float(L[region].max())-.8)
    base_alpha=base_alpha.copy();base_alpha[protected]=0
    structural=cv2.GaussianBlur(L,(0,0),max(1,fw*.003))
    gradient=cv2.magnitude(cv2.Sobel(structural,cv2.CV_32F,1,0),cv2.Sobel(structural,cv2.CV_32F,0,1))
    base_alpha*=1/(1+(gradient/24)**4)
    delta=np.zeros(L.shape,np.float32); recipes=[]; algorithms=set()
    for idx,radius_ratio,epsilon,blend in [(0,.013,25,.85),(2,.008,12,.55),(3,.008,12,.55)]:
        row=before['regions'][idx]
        if row['status']!='measured':continue
        coords=np.asarray(before['outlines'][idx]['points'])*[rgb.shape[1],rgb.shape[0]]
        region=hotspots._polygon_mask(rgb.shape[:2],coords)&before['_skin_mask']
        if idx in (2,3):
            region &= ylocal < fh*.07 # Restrict cheeks above mouth/beard boundary.
            region &= L>float(row['median_lightness'])-16 # Conservative dark-beard exclusion.
        # Feather inward from every region boundary; exactly zero beyond it.
        distance=cv2.distanceTransform(region.astype('uint8'),cv2.DIST_L2,5)
        feather=np.clip(distance/max(2,fw*.015),0,1)
        radius=max(1,min(24,round(fw*radius_ratio)))
        filtered,algorithm=_guided(L,radius,epsilon);algorithms.add(algorithm)
        region_delta=(filtered-L)*base_alpha*feather*blend*strength/100
        delta+=region_delta
        recipes.append(dict(region=row['key'],radius=radius,epsilon_L2=epsilon,blend=blend))
    delta=np.clip(delta,-5,5);edited_lab=lab.copy();edited_lab[...,0]+=delta
    rendered=np.rint(np.clip(cv2.cvtColor(edited_lab,cv2.COLOR_LAB2RGB),0,1)*255).astype('uint8')
    out=rgb.copy();editable=np.abs(delta)>.001;out[editable]=rendered[editable]
    out[protected|~before['_skin_mask']]=rgb[protected|~before['_skin_mask']]
    after=hotspots.measure(out,points,include_masks=True)
    # Do not revert whole regions to keep derived median-relative counts fixed.
    report=dict(status='applied',phase='skin',method='guided',models=[],strength=float(strength),
        version='landmark-guided-texture-v1',algorithms=sorted(algorithms),recipes=recipes,
        edited_pixels=int(np.any(out!=rgb,axis=2).sum()),protected_pixels=int(protected.sum()),
        protected_exact=bool(np.array_equal(out[protected],rgb[protected])),max_lightness_delta=5,
        before_hotspots=skin._diagnostic(before),after_hotspots=skin._diagnostic(after),
        message=f'Regional guided texture finish {strength:g}% · stronger forehead, gentler cheeks',
        preserved_hotspot_pixels=bool(np.array_equal(out[before['_candidate_mask']],rgb[before['_candidate_mask']])),
        source_size=[rgb.shape[1],rgb.shape[0]],output_size=[out.shape[1],out.shape[0]],
        source_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),output_rgb_sha256=hashlib.sha256(out.tobytes()).hexdigest())
    return out,report
