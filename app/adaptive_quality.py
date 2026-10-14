"""Trial, source-referenced correction controller; no passport approval scores.

Landmarks come from the real face model. Tone/noise/texture decisions below are
explicit engineering heuristics, not learned skin-tone or demographic classes.
Profiles are maximum edit budgets, not targets for a particular complexion.
"""
import copy
import hashlib
import time
import threading

import cv2
import numpy as np

from . import enhancement, hotspots, skin, skin_guided, portrait_finish, blemishes

VERSION = 'adaptive-quality-v2'
_lighting_lock=threading.Lock()
_lighting_cache=None
FACE_FEATHER_WIDTH = .20
PROFILES = {
    'natural': dict(label='Natural', exposure_ev=.25, shadow_ev=.20, lighting_fraction=.35, max_highlight_ev=.10, denoise=10., skin=10., blemish=10., texture_floor=.95),
    'balanced': dict(label='Balanced', exposure_ev=.50, shadow_ev=.35, lighting_fraction=.65, max_highlight_ev=.20, denoise=18., skin=25., blemish=20., texture_floor=.90),
    'recovery': dict(label='Recovery', exposure_ev=.75, shadow_ev=.50, lighting_fraction=1., max_highlight_ev=.30, denoise=25., skin=40., blemish=30., texture_floor=.85),
}


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
    """Return same-size image and auditable decisions; never infer missing regions."""
    if profile not in PROFILES:raise ValueError('Unknown adaptive profile')
    started=time.monotonic();budget=PROFILES[profile]
    evidence=dict(version=VERSION,phase='adaptive',profile=profile,label=budget['label'],
                  status='unavailable',models=[],source_rgb_sha256=_digest(rgb),
                  source_size=[rgb.shape[1],rgb.shape[0]],budget=budget,
                  calibration='Trial heuristics; not Photomatic/ICAO decision thresholds')
    try:
        points=np.asarray(points,dtype=np.float64)
        if points.shape!=(478,2) or not np.isfinite(points).all():raise ValueError('Facial landmarks unavailable')
        # Bound analysis/restoration memory; render only on this actual input
        # grid, never upscale in the quality controller. Full-frame jobs retain
        # their native geometry with a bounded-resolution gain field below.
        iod=float(np.linalg.norm(points[468]-points[473]))
        if iod<15:raise ValueError('Face too small for adaptive preparation')
        scale=min(1.,180/iod,1600/max(rgb.shape[:2]))
        size=(max(1,round(rgb.shape[1]*scale)),max(1,round(rgb.shape[0]*scale)))
        small=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA) if scale<1 else rgb.copy()
        sp=points*np.array([size[0]/rgb.shape[1],size[1]/rgb.shape[0]])
        report,alpha,protected,lab=_regions(small,sp,keep)
        if person_mask is not None:
            if person_mask.shape!=rgb.shape[:2] or not np.isfinite(person_mask).all():raise ValueError('Foreground mask unavailable')
            pm=cv2.resize(person_mask,size,interpolation=cv2.INTER_LINEAR)
            alpha[pm<.8]=0
            if (alpha>.2).sum()<100:raise ValueError('Foreground skin is uncertain')
        diagnosis=portrait_finish.analyse(small,sp,pm if person_mask is not None else None,keep)
        evidence['source_diagnosis']=diagnosis['report']
        cleanup_alpha=np.minimum(alpha,diagnosis['_cleanup_alpha'])
        valid=alpha>.2;noise=_noise(lab[...,0],valid)
        lum=_linear(small)@np.array([.2126,.7152,.0722],np.float32)
        # Whole-image upper tail, never a desired skin median. A dark face
        # against a bright backdrop alone does not trigger global exposure.
        scene_p99=float(np.percentile(lum,99))
        exposure=min(budget['exposure_ev'],max(0.,float(np.log2(.22/max(scene_p99,1e-5)))))
        fw=float(np.linalg.norm(sp[454]-sp[234]))
        weight=alpha.copy()
        num=cv2.GaussianBlur(lum*weight,(0,0),max(2,fw*.08))
        den=cv2.GaussianBlur(weight,(0,0),max(2,fw*.08))
        broad=num/np.maximum(den,1e-5)
        q25,q75=np.percentile(broad[valid],[25,75])
        spread=float(np.log2(max(q75,1e-5)/max(q25,1e-5)))
        # Correct relative illumination only when regional variation exceeds
        # the trial deadband. No fixed light/dark complexion target is used.
        shadow=min(budget['shadow_ev'],max(0.,spread-.35)*.6)
        lift=np.clip(np.log2(max(q75,1e-5)/np.maximum(broad,1e-5)),0,shadow)
        # Tone can cross eyes/lips/marks smoothly; cleanup cannot. Use one
        # inward-feathered oval so small editable skin patches do not become
        # visible bright islands. The field is still estimated only from skin.
        oval=hotspots._polygon_mask(small.shape[:2],sp[hotspots.FACE_OVAL]).astype(np.uint8)
        distance=cv2.distanceTransform(oval,cv2.DIST_L2,5)
        tone_alpha=_face_feather(distance,fw)
        if person_mask is not None:tone_alpha*=np.clip((pm-.5)*2,0,1)
        lift[den<.02]=0
        lift=cv2.GaussianBlur(lift,(0,0),max(2,fw*.04))
        lift=np.minimum(lift,shadow)*tone_alpha
        gain=(2**(exposure+lift)).astype(np.float32)
        lighting_record=None
        skin_p90=float(np.percentile(lum[valid],90))
        skin_range=float(np.percentile(lab[...,0][valid],90)-np.percentile(lab[...,0][valid],10))
        # Scene/face brightness cannot decide whether a face needs correction:
        # bright backgrounds and natural reflectance make that ratio ambiguous.
        # Evaluate a proposal on measurable, non-flat faces first; profile
        # strength and headroom limit the actual edit afterwards. Flat fields
        # stay exact no-ops without asking a low-light model to invent variation.
        lighting_needed=skin_range>4
        learned_max=0.
        proposal_percentiles=None
        if lighting_needed:
            predicted,lighting_record=lighting_prediction(small)
            lighting_record['phase']='adaptive_lighting'
            if lighting_record['status']=='applied':
                proposed=_linear(predicted)@np.array([.2126,.7152,.0722],np.float32)
                ev=np.log2(np.maximum(proposed,1e-5)/np.maximum(lum,1e-5))
                # Transfer low frequencies only, in linear luminance, using
                # the same gain in all channels. NN pixels never become pores.
                ev=_lighting_field(ev,weight,valid,max(2,fw*.06))
                proposal_percentiles=[round(float(x),4) for x in np.percentile(ev[valid],[10,50,90])]
                ev=np.clip(ev*budget['lighting_fraction'],0,budget['exposure_ev'])*tone_alpha
                learned_max=float(ev.max())
                combined=np.minimum(np.log2(gain)+ev,budget['exposure_ev']+budget['shadow_ev'])
                gain=(2**combined).astype(np.float32)
        full_gain=cv2.resize(gain,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_LINEAR)
        reference=_tone(rgb,full_gain)
        reference,highlight_record=portrait_finish.apply_highlights(reference,diagnosis,budget)
        # Restore/denoise from source pixels, then reapply the same lighting and
        # highlight field before comparing texture. No earlier edit is stacked.
        highlight_gain=portrait_finish.highlight_gain(diagnosis,rgb.shape[:2],budget)
        # Noise and fine skin texture cannot be perfectly separated here.
        # Conservative budgets and a source-detail floor bound their removal.
        need=0. if noise is None else float(np.clip((noise-.8)/2.5,0,1))
        texture_need=diagnosis['report']['texture_need']
        denoise=round(budget['denoise']*need,2)
        smoothing=round(budget['skin']*max(need,texture_need),2)
        cleaning=round(budget['blemish']*texture_need,2)
        cleanup_available=int((cleanup_alpha>.2).sum())>=100
        cleanup_needed=bool(denoise or smoothing or cleaning)
        if not cleanup_available:denoise=smoothing=cleaning=0.
        evidence['analysis']=dict(analysis_size=list(size),interocular_pixels=round(float(np.linalg.norm(sp[468]-sp[473])),2),
            skin_pixels=int(valid.sum()),skin_median_lightness=round(float(np.median(lab[...,0][valid])),3),
            scene_p99_linear_luminance=round(scene_p99,5),regional_illumination_spread_ev=round(spread,4),
            face_p90_linear_luminance=round(skin_p90,5),skin_lightness_range=round(skin_range,4),
            noise_estimate_L=round(noise,4) if noise is not None else None,
            noise_method='Smooth-region diagonal MAD; texture/noise separation remains uncertain')
        evidence['decisions']=dict(exposure_ev=round(exposure,4),maximum_local_shadow_ev=round(shadow,4),
            lighting_adviser_requested=lighting_needed,maximum_learned_lighting_ev=round(learned_max,4),
            lighting_proposal_ev_p10_p50_p90=proposal_percentiles,lighting_fraction=budget['lighting_fraction'],
            lighting_field_method='Regularized normalized convolution with measured-skin median prior',
            face_feather_width_fraction=FACE_FEATHER_WIDTH,face_feather_curve='smoothstep',
            maximum_highlight_reduction_ev=highlight_record['maximum_highlight_ev'],
            denoise_percent=denoise,skin_percent=smoothing,skin_cleaning_percent=cleaning,sharpening=0,colour_adjustment='unchanged',
            reasons=['Global exposure uses the whole-image bright tail, not skin brightness',
                     'Shadow lift uses relative illumination inside this face',
                     'Non-flat faces receive a lighting proposal before correction strength is selected',
                     'Profile-scaled lighting proposals are bounded linear-luminance fields; model skin pixels are discarded',
                     'Relative highlights use a source-derived negative scalar field with original clipping retained',
                     'Skin polish follows measured texture separately from sensor-noise cleanup',
                     'Local spot detection uses gentle small-candidate repair; source marks and feature detail are guarded',
                     'No neutral colour reference: automatic white balance skipped',
                     'Focus recovery and facial reconstruction are not selected'])
        # Learned cleanup is performed at the native input grid inside a
        # bounded face ROI; inference is never used to redraw eyes/lips/hair.
        candidate=reference.copy();stages=([lighting_record] if lighting_record else [])+[highlight_record]
        evidence['models']=copy.deepcopy(lighting_record.get('models',[])) if lighting_record else []
        if cleanup_needed and not cleanup_available:
            stages.append(dict(phase='adaptive_skin_cleanup',status='unavailable',models=[],
                message='Too little reliable skin support for texture cleanup; tonal corrections retained'))
        if denoise or smoothing or cleaning:
            ys,xs=np.where(cleanup_alpha>.001)
            sx=rgb.shape[1]/size[0];sy=rgb.shape[0]/size[1]
            x0=max(0,int(xs.min()*sx)-32);x1=min(rgb.shape[1],int((xs.max()+1)*sx)+32)
            y0=max(0,int(ys.min()*sy)-32);y1=min(rgb.shape[0],int((ys.max()+1)*sy)+32)
            crop=rgb[y0:y1,x0:x1]
            # Large full-frame ROI stays local without a multi-GB worker.
            if max(crop.shape[:2])>1800:
                denoise=0.;evidence['decisions']['denoise_percent']=0.
                evidence['decisions']['reasons'].append('Native face ROI exceeds cleanup memory budget; learned denoise skipped')
            if denoise:
                restored,record=enhancement.apply(crop,dict(denoise=denoise))
                restored=_tone(restored,full_gain[y0:y1,x0:x1])
                restored=_tone(restored,highlight_gain[y0:y1,x0:x1])
            else:
                restored=reference[y0:y1,x0:x1].copy()
                record=dict(status='unchanged',models=[],message='No noise correction selected')
            record['phase']='adaptive_denoise';stages.append(record);evidence['models']+=record.get('models',[])
            ap=points-[x0,y0]
            source_protected=cv2.resize((diagnosis['_mark_mask']|diagnosis['_feature_mask']).astype(np.uint8),
                (rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_NEAREST).astype(bool)[y0:y1,x0:x1]
            if smoothing:
                restored,srecord=skin_guided.apply(restored,ap,smoothing)
                srecord['phase']='adaptive_skin';stages.append(srecord)
            if cleaning:
                restored,crecord,_=blemishes.apply(restored,ap,dict(blemish=cleaning,
                    blemish_sensitivity='gentle',blemish_size='small'),protected_mask=source_protected)
                crecord['phase']='adaptive_skin_cleaning';stages.append(crecord);evidence['models']+=crecord.get('models',[])
            restored[source_protected]=reference[y0:y1,x0:x1][source_protected]
            full_alpha=cv2.resize(cleanup_alpha,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_LINEAR)
            full_protected=cv2.resize(protected.astype(np.uint8),(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_NEAREST).astype(bool)
            full_alpha[full_protected]=0
            a=full_alpha[y0:y1,x0:x1,None]
            candidate[y0:y1,x0:x1]=np.rint(reference[y0:y1,x0:x1]*(1-a)+restored*a).astype(np.uint8)
        # Verify the normalized, common analysis grid; any rollback is also
        # applied to the full-resolution output. Exact facial source geometry
        # stays unchanged; tone edits are different from pixel-exact identity.
        r=cv2.resize(reference,size,interpolation=cv2.INTER_AREA)
        c=cv2.resize(candidate,size,interpolation=cv2.INTER_AREA)
        _,guard=texture_guard(r,c,valid,budget['texture_floor'])
        blend=guard['blend'] if guard['status']!='unchanged' else 1.
        guarded=np.rint(r.astype(np.float32)*(1-blend)+c.astype(np.float32)*blend).astype(np.uint8)
        feature_mask=diagnosis['_feature_mask']|diagnosis['_mark_mask']
        _,feature_guard=texture_guard(r,guarded,feature_mask,.98)
        if feature_guard['status']!='unchanged':blend*=feature_guard['blend']
        out=np.rint(reference.astype(np.float32)*(1-blend)+candidate.astype(np.float32)*blend).astype(np.uint8)
        changed_pixels=int(np.any(out!=rgb,axis=2).sum())
        failed_stages=[s['phase'].removeprefix('adaptive_') for s in stages if s.get('status')=='unavailable']
        incomplete=noise is None or bool(failed_stages)
        summary=[]
        if exposure or shadow or learned_max:summary.append('lighting adjusted')
        if highlight_record['edited_pixels']:summary.append('shine softened')
        if smoothing:summary.append('skin polish checked')
        if cleaning:summary.append('local spots checked')
        message=(f"{budget['label']} · "+' · '.join(summary) if changed_pixels else f"{budget['label']} evaluated · no facial correction selected")
        if incomplete:
            missing=', '.join(failed_stages+(['noise analysis'] if noise is None else []))
            message=f"{budget['label']} preparation incomplete · {missing} unavailable; "+('completed corrections retained' if changed_pixels else 'input pixels retained')
        evidence.update(status='partial' if incomplete else 'applied' if changed_pixels else 'unchanged',
            changed_pixels=changed_pixels,mean_absolute_rgb_change=round(float(np.mean(np.abs(out.astype(np.float32)-rgb))),5),
            stages=stages,texture_guard=guard,feature_detail_guard=feature_guard,cleanup_blend=round(float(blend),5),
            before_hotspots=skin._diagnostic(report),
            after_hotspots=skin._diagnostic(hotspots.measure(cv2.resize(out,size,interpolation=cv2.INTER_AREA),sp)),
            message=message,
            output_rgb_sha256=_digest(out),output_size=[out.shape[1],out.shape[0]],
            seconds=round(time.monotonic()-started,3))
        return out,evidence
    except (ValueError,cv2.error,TypeError):
        evidence.update(message='Adaptive facial preparation unavailable; input pixels retained. Review the original.',
                        output_rgb_sha256=_digest(rgb),output_size=evidence['source_size'],seconds=round(time.monotonic()-started,3))
        return rgb,evidence
