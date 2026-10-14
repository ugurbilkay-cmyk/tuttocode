"""Three scene-exposure choices with source-referenced local lighting.

Landmarks come from the real face model. Local illumination decisions use
engineering heuristics, not learned skin-tone or demographic classes.
Scene exposure is an explicit staff choice, not an inferred complexion target.
Skin retouching, shine removal and reconstruction are not part of these options.
"""
import copy
import hashlib
import time
import threading

import cv2
import numpy as np

from . import enhancement, hotspots, skin, skin_guided, portrait_finish, blemishes

VERSION = 'adaptive-quality-v3'
_lighting_lock=threading.Lock()
_lighting_cache=None
FACE_FEATHER_WIDTH = .20
_LIGHTING_ONLY = dict(mode='lighting_only', shadow_ev=.35, lighting_fraction=.65,
    max_relative_lighting_ev=.50, max_highlight_ev=0., denoise=0., skin=0., blemish=0.)
PROFILES = {key: dict(_LIGHTING_ONLY, label=label, exposure_ev=ev) for key,label,ev in (
    ('natural','Natural',.25), ('balanced','Balanced',.50), ('recovery','Recovery',.75))}


def _digest(rgb):
    return hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()


def lighting_prediction(rgb):
    """One verified source prediction reused across profile strengths in-process.

    No customer rasters on disk beyond the existing temporary worker files.
    A different source evicts the sole cached image. Failed predictions are
    never cached. Worker provenance/hashes are retained on cache hits.
    """
    global _lighting_cache
    from . import config,enhancement_models
    weight=config.ENHANCER_MODEL_DIR/'retinex/model.pth'
    try:stamp=(str(weight.resolve()),weight.stat().st_mtime_ns,weight.stat().st_size)
    except OSError:stamp=None
    key=(_digest(rgb),VERSION,enhancement_models.VERSION,stamp,config.ENHANCER_PYTHON)
    with _lighting_lock:
        if _lighting_cache is not None and _lighting_cache[0]==key:
            return _lighting_cache[1].copy(),dict(copy.deepcopy(_lighting_cache[2]),cache_hit=True)
        out,e=enhancement.apply(rgb,dict(lighting=100))
        if e['status']=='applied':_lighting_cache=(key,out.copy(),copy.deepcopy(e))
        else:_lighting_cache=None
        return out,dict(copy.deepcopy(e),cache_hit=False)


def _linear(rgb):
    x=rgb.astype(np.float32)/255
    return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)


def _render(linear):
    x=np.clip(linear,0,1)
    return np.rint(np.clip(np.where(x<=.0031308,x*12.92,1.055*x**(1/2.4)-.055),0,1)*255).astype(np.uint8)


def _regions(rgb, points, keep):
    report=hotspots.measure(rgb,points,include_masks=True)
    lab=cv2.cvtColor(rgb.astype(np.float32)/255,cv2.COLOR_RGB2LAB)
    width=float(np.linalg.norm(points[454]-points[234]))
    radius=max(1,round(width*.025))
    alpha=cv2.erode(report['_skin_mask'].astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,)*2)).astype(np.float32)
    alpha=cv2.GaussianBlur(alpha,(0,0),max(.6,width*.008))
    alpha[~report['_skin_mask']]=0
    # Relative candidates and clipping, not an absolute light-skin cutoff.
    protected=report['_candidate_mask'] | (rgb.max(axis=2)>=250)
    for index in (468,473,1):
        feature=np.zeros(rgb.shape[:2],np.uint8)
        x,y=points[index]
        axes=(max(2,round(width*.15)),max(2,round(width*.09))) if index!=1 else (max(1,round(width*.065)),max(1,round(width*.04)))
        cv2.ellipse(feature,(round(x),round(y-width*.025 if index!=1 else y)),axes,0,0,360,1,-1)
        protected |= feature.astype(bool)
    for x,y,r in keep or []:
        feature=np.zeros(rgb.shape[:2],np.uint8)
        cv2.circle(feature,(round(x*rgb.shape[1]),round(y*rgb.shape[0])),max(1,round(r*min(rgb.shape[:2]))),1,-1)
        protected |= feature.astype(bool)
    region=np.zeros(rgb.shape[:2],bool)
    # Forehead and upper cheeks only. Geometric regions are further narrowed by
    # this image's chroma and dark-mark evidence; no ethnic skin-colour ranges.
    for idx in (0,2,3):
        coords=np.asarray(report['outlines'][idx]['points'])*[rgb.shape[1],rgb.shape[0]]
        part=hotspots._polygon_mask(rgb.shape[:2],coords)
        if idx in (2,3):
            part &= np.indices(part.shape)[0]<float((points[1,1]+points[61,1])/2)
        region |= part
    region &= report['_skin_mask']
    if region.sum()<100:raise ValueError('Too little measurable facial skin')
    ab=np.median(lab[...,1:][region],axis=0)
    region &= np.linalg.norm(lab[...,1:]-ab,axis=2)<18
    broad=cv2.GaussianBlur(lab[...,0],(0,0),max(2,width*.02))
    marks=(broad-lab[...,0])>8
    protected |= cv2.dilate(marks.astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
    alpha *= region
    alpha[protected]=0
    if (alpha>.2).sum()<100:raise ValueError('Facial skin protection is uncertain')
    return report,alpha,protected,lab


def _noise(light, mask):
    # Diagonal 2x2 high-pass MAD on the smoother half of the eligible skin.
    # A diagnostic estimate, not proof that residuals are sensor noise.
    broad=cv2.GaussianBlur(light,(0,0),1.2)
    gradient=cv2.magnitude(cv2.Sobel(broad,cv2.CV_32F,1,0),cv2.Sobel(broad,cv2.CV_32F,0,1))
    valid=mask[:-1,:-1]&mask[1:,:-1]&mask[:-1,1:]&mask[1:,1:]
    if valid.sum()<100:return None
    valid &= gradient[:-1,:-1]<=np.percentile(gradient[:-1,:-1][valid],50)
    if valid.sum()<50:return None
    residual=(light[:-1,:-1]-light[1:,:-1]-light[:-1,1:]+light[1:,1:])/2
    values=residual[valid]
    return float(np.median(np.abs(values-np.median(values)))/.67449)


def _tone(rgb, gain):
    # No additive detail synthesizer. The bounded smooth field multiplies
    # linear RGB equally, retaining channel ratios until quantization.
    lin=_linear(rgb)
    maximum=lin.max(axis=2)
    # Reserve headroom instead of clipping previously unclipped source pixels.
    gain=np.minimum(gain,np.maximum(1.,.945/np.maximum(maximum,1e-6)))
    out=_render(lin*gain[...,None])
    out[rgb.max(axis=2)>=250]=rgb[rgb.max(axis=2)>=250]
    return out


def _lighting_field(ev, weight, valid, sigma):
    """Extend measured skin lighting smoothly across protected facial features.

    Sparse editable skin is evidence for a field, not the field's boundary.
    A robust constant prior prevents holes at eyes/nose and hard support cutoffs.
    Only a scalar illumination estimate is extended, never model RGB/detail.
    """
    prior=float(np.median(ev[valid]))
    num=cv2.GaussianBlur(ev*weight,(0,0),sigma)
    den=cv2.GaussianBlur(weight,(0,0),sigma)
    return (num+.02*prior)/(den+.02)


def _face_feather(distance,face_width):
    value=np.clip(distance/max(2,face_width*FACE_FEATHER_WIDTH),0,1)
    return value*value*(3-2*value)


def texture_guard(reference,candidate,mask,floor):
    """Blend back against source-derived tone when normalized residuals collapse.

    This is a trial edit guard, not a validated pore/identity/focus metric. Check
    forehead and cheeks separately so one textured region cannot hide another.
    """
    if np.array_equal(reference,candidate):return candidate,dict(blend=0.,regions=[],status='unchanged')
    a=cv2.cvtColor(reference.astype(np.float32)/255,cv2.COLOR_RGB2LAB)[...,0]
    b=cv2.cvtColor(candidate.astype(np.float32)/255,cv2.COLOR_RGB2LAB)[...,0]
    ah=a-cv2.GaussianBlur(a,(0,0),1.2);bh=b-cv2.GaussianBlur(b,(0,0),1.2)
    factor=1.;rows=[]
    # Spatial tiles keep the guard local and independent of demographic labels.
    ys,xs=np.where(mask)
    if len(ys)<100:return reference,dict(blend=0.,regions=[],status='unavailable')
    ycuts=np.linspace(ys.min(),ys.max()+1,4,dtype=int)
    xcuts=np.linspace(xs.min(),xs.max()+1,4,dtype=int)
    for y0,y1 in zip(ycuts[:-1],ycuts[1:]):
        for x0,x1 in zip(xcuts[:-1],xcuts[1:]):
            m=mask[y0:y1,x0:x1]
            if m.sum()<50:continue
            x=ah[y0:y1,x0:x1][m];y=bh[y0:y1,x0:x1][m]
            energy=float(np.mean(x*x))
            if energy<.05:continue
            projection=float(np.mean(x*y)/energy)
            ratio=float(np.sqrt(np.mean(y*y)/energy))
            # For linear mixing of residuals, projection is 1+t*(p-1).
            allowed=min(1.,max(0.,(1-floor)/(1-projection))) if projection<floor else 1.
            factor=min(factor,allowed)
            rows.append(dict(source_energy=round(energy,5),candidate_energy_ratio=round(ratio,5),
                             source_detail_projection=round(projection,5),allowed_blend=round(allowed,5)))
    # Quantized final verification; decrease blending if the declared floor is
    # missed. This metric deliberately has no green/passport verdict.
    for _ in range(10):
        out=np.rint(reference.astype(np.float32)*(1-factor)+candidate.astype(np.float32)*factor).astype(np.uint8)
        c=cv2.cvtColor(out.astype(np.float32)/255,cv2.COLOR_RGB2LAB)[...,0]
        ch=c-cv2.GaussianBlur(c,(0,0),1.2)
        projections=[]
        for y0,y1 in zip(ycuts[:-1],ycuts[1:]):
            for x0,x1 in zip(xcuts[:-1],xcuts[1:]):
                m=mask[y0:y1,x0:x1];x=ah[y0:y1,x0:x1][m]
                if len(x)<50 or np.mean(x*x)<.05:continue
                projections.append(float(np.mean(x*ch[y0:y1,x0:x1][m])/np.mean(x*x)))
        if not projections or min(projections)>=floor-.005:break
        factor*=.7
    else:
        factor=0.;out=reference.copy();projections=[1.]
    return out,dict(status='measured',blend=round(factor,5),floor=floor,
                    minimum_final_projection=round(min(projections),5) if projections else None,regions=rows,
                    reference='Original pixels after the same bounded lighting field; before cleanup',
                    limitation='Residuals include noise; this is not identity, focus or pore certification')


def apply(rgb,points,profile,person_mask=None,keep=None):
    """Apply the chosen scene exposure plus a common source-relative local field.

    A missing local analysis never cancels the explicit scene-exposure choice.
    The model's common brightness proposal is discarded; no model RGB, cleanup
    or shine-removal pixels are used by these three lighting options.
    """
    if profile not in PROFILES:raise ValueError('Unknown adaptive profile')
    started=time.monotonic();budget=copy.deepcopy(PROFILES[profile])
    exposure=float(budget['exposure_ev'])
    decisions=dict(exposure_ev=exposure,exposure_selection='Explicit lighting option',
        exposure_support='Whole source crop, including face, neck, clothing and background',
        maximum_local_shadow_ev=0.,lighting_adviser_requested=False,
        maximum_learned_lighting_ev=0.,lighting_proposal_ev_p10_p50_p90=None,
        removed_model_common_ev=None,lighting_fraction=budget['lighting_fraction'],
        maximum_relative_lighting_ev=budget['max_relative_lighting_ev'],
        lighting_field_method='Median-centered source-relative scalar linear-luminance field',
        face_feather_width_fraction=FACE_FEATHER_WIDTH,face_feather_curve='smoothstep',
        maximum_highlight_reduction_ev=0.,denoise_percent=0.,skin_percent=0.,
        skin_cleaning_percent=0.,sharpening=0,colour_adjustment='unchanged',
        reasons=['The selected scene exposure covers the whole photo rather than a face oval',
                 'All three choices use the same restrained local facial-lighting correction',
                 'The common median model brightening is removed before local correction',
                 'No target skin brightness or backdrop-based face exposure is inferred',
                 'Original colour channel ratios and geometry are retained apart from rounding',
                 'Polishing, denoising, spot cleaning and shine reduction are off'])
    evidence=dict(version=VERSION,mode='lighting_only',phase='adaptive',profile=profile,
        label=budget['label'],status='unavailable',models=[],source_rgb_sha256=_digest(rgb),
        source_size=[rgb.shape[1],rgb.shape[0]],budget=budget,decisions=decisions,
        calibration='Staff-selected exposure levels; local-lighting heuristics are not calibrated exposure or passport decisions')
    local_full=np.zeros(rgb.shape[:2],np.float32)
    stages=[];incomplete=None
    try:
        points=np.asarray(points,dtype=np.float64)
        if points.shape!=(478,2) or not np.isfinite(points).all():
            raise ValueError('Facial landmarks unavailable')
        iod=float(np.linalg.norm(points[468]-points[473]))
        if iod<15:raise ValueError('Face too small for local lighting')
        scale=min(1.,180/iod,1600/max(rgb.shape[:2]))
        size=(max(1,round(rgb.shape[1]*scale)),max(1,round(rgb.shape[0]*scale)))
        small=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA) if scale<1 else rgb.copy()
        sp=points*np.array([size[0]/rgb.shape[1],size[1]/rgb.shape[0]])
        report,alpha,_,lab=_regions(small,sp,keep)
        pm=None
        if person_mask is not None:
            if person_mask.shape!=rgb.shape[:2] or not np.isfinite(person_mask).all():
                raise ValueError('Foreground mask unavailable')
            pm=cv2.resize(person_mask,size,interpolation=cv2.INTER_LINEAR)
            alpha[pm<.8]=0
            if (alpha>.2).sum()<100:raise ValueError('Foreground lighting support is uncertain')
        valid=alpha>.2;weight=alpha.copy()
        lum=_linear(small)@np.array([.2126,.7152,.0722],np.float32)
        fw=float(np.linalg.norm(sp[454]-sp[234]))
        num=cv2.GaussianBlur(lum*weight,(0,0),max(2,fw*.08))
        den=cv2.GaussianBlur(weight,(0,0),max(2,fw*.08))
        broad=num/np.maximum(den,1e-5)
        q25,q75=np.percentile(broad[valid],[25,75])
        spread=float(np.log2(max(q75,1e-5)/max(q25,1e-5)))
        shadow=min(budget['shadow_ev'],max(0.,spread-.35)*.6)
        lift=np.clip(np.log2(max(q75,1e-5)/np.maximum(broad,1e-5)),0,shadow)
        oval=hotspots._polygon_mask(small.shape[:2],sp[hotspots.FACE_OVAL]).astype(np.uint8)
        distance=cv2.distanceTransform(oval,cv2.DIST_L2,5)
        tone_alpha=_face_feather(distance,fw)
        if pm is not None:tone_alpha*=np.clip((pm-.5)*2,0,1)
        lift[den<.02]=0
        lift=cv2.GaussianBlur(lift,(0,0),max(2,fw*.04))
        lift=np.minimum(lift,shadow)*tone_alpha
        skin_range=float(np.percentile(lab[...,0][valid],90)-np.percentile(lab[...,0][valid],10))
        analysis=dict(analysis_size=list(size),
            interocular_pixels=round(float(np.linalg.norm(sp[468]-sp[473])),2),
            skin_pixels=int(valid.sum()),skin_median_lightness=round(float(np.median(lab[...,0][valid])),3),
            scene_p99_linear_luminance=round(float(np.percentile(lum,99)),5),
            regional_illumination_spread_ev=round(spread,4),
            face_p90_linear_luminance=round(float(np.percentile(lum[valid],90)),5),
            skin_lightness_range=round(skin_range,4))
        evidence['analysis']=analysis
        evidence['source_diagnosis']=dict(version='source-lighting-v1',status='measured',
            source_rgb_sha256=_digest(small),**analysis,
            near_clip_any_pixels=int((small.max(axis=2)>=250).sum()),
            limitation='Source-relative lighting cues do not identify skin reflectance, establish correct exposure, or calibrate colour.')
        decisions['maximum_local_shadow_ev']=round(shadow,4)
        lighting_needed=skin_range>4
        decisions['lighting_adviser_requested']=lighting_needed
        relative=np.zeros(lum.shape,np.float32)
        if lighting_needed:
            predicted,record=lighting_prediction(small)
            record=copy.deepcopy(record);record['phase']='adaptive_lighting';stages.append(record)
            evidence['models']=copy.deepcopy(record.get('models',[]))
            if record['status']=='applied':
                if predicted.shape!=small.shape:raise ValueError('Lighting prediction grid differs')
                proposed=_linear(predicted)@np.array([.2126,.7152,.0722],np.float32)
                ev=np.log2(np.maximum(proposed,1e-5)/np.maximum(lum,1e-5))
                ev=_lighting_field(ev,weight,valid,max(2,fw*.06))
                common=float(np.median(ev[valid]))
                relative=np.clip((ev-common)*budget['lighting_fraction'],0,
                    budget['max_relative_lighting_ev'])*tone_alpha
                decisions.update(removed_model_common_ev=round(common,4),
                    lighting_proposal_ev_p10_p50_p90=[round(float(v),4) for v in np.percentile(ev[valid],[10,50,90])],
                    maximum_learned_lighting_ev=round(float(relative.max()),4))
            else:incomplete='Local lighting model unavailable'
        # Match the reviewed scene trials: interpolate the sum of local EV,
        # then add the selected common scene exposure before exponentiation.
        local_full=cv2.resize(lift+relative,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_LINEAR)
    except (ValueError,cv2.error,TypeError):
        incomplete='Local facial-lighting analysis unavailable'
    full_gain=np.exp2(exposure+local_full).astype(np.float32)
    out=_tone(rgb,full_gain)
    changed=int(np.any(out!=rgb,axis=2).sum())
    clipped=rgb.max(axis=2)>=250
    maximum=_linear(rgb).max(axis=2)
    limited=np.minimum(full_gain,np.maximum(1.,.945/np.maximum(maximum,1e-6)))
    limited[clipped]=1.
    actual=np.log2(limited)
    message=f"{budget['label']} lighting · scene +{exposure:.2f} EV selected · retouching off"
    if incomplete:message+=f" · {incomplete}; scene exposure retained"
    evidence.update(status='partial' if incomplete else 'applied' if changed else 'unchanged',
        stages=stages,changed_pixels=changed,
        mean_absolute_rgb_change=round(float(np.mean(np.abs(out.astype(np.float32)-rgb))),5),
        requested_scene_exposure_ev=exposure,
        applied_gain_ev_p10_p50_p90=[round(float(v),4) for v in np.percentile(actual,[10,50,90])],
        headroom_limited_pixels=int(((limited<full_gain-1e-6)&~clipped).sum()),
        source_clipping_exact=bool(np.array_equal(out[clipped],rgb[clipped])),
        new_near_clip_pixels=int(((out.max(axis=2)>=250)&~clipped).sum()),
        detail_method='One source-only common-channel scalar linear-light pass; no spatial filtering or facial reconstruction',
        message=message,output_rgb_sha256=_digest(out),output_size=evidence['source_size'],
        seconds=round(time.monotonic()-started,3))
    return out,evidence
