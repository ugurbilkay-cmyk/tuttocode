"""Per-photo execution evidence, separate from passport quality verdicts."""
from . import background_models, enhancement


def report(options, values, checks, has_photo, ai_state=None):
    rows=[]
    def add(name,state,detail):rows.append(dict(name=name,state=state,detail=detail))
    face=values.get('face_analysis',{})
    if face.get('status')=='completed':
        counts=face.get('landmark_counts',[])
        detail=f"{face.get('method',face.get('engine','Face analyzer'))} · {face['face_count']} face(s) · {sum(counts)} landmarks"
        if 'inference_seconds' in face:detail+=f" · {face['inference_seconds']:g} s"
        if face.get('model_sha256'):detail+=f" · model {face['model_sha256'][:12]}"
        add('Face detection','Completed',detail)
    elif values.get('source_eye_distance') is not None:
        add('Face detection','Saved measurements','Face geometry exists from an earlier run; model execution provenance was not recorded then.')
    else:add('Face detection','Unavailable','No completed facial-analysis evidence for this job.')
    geometry=values.get('crop_geometry',{})
    if not has_photo:
        add('Document crop','Failed','No prepared photo. Background removal and enhancement below were not reached.')
    elif values.get('print_only'):
        add('Document crop','Full frame','Print layout only; no passport crop was assessed.')
    else:
        detail='Face-based crop prepared; quality findings remain separate.'
        if geometry.get('automatic_fit'):detail='Automatic crop fitted to real source pixels; selected template limits remain enforced.'
        if values.get('head_percent') is not None:detail+=f" Head {values['head_percent']:g}% · eyes {values['eye_height_percent']:g}%."
        add('Document crop','Completed',detail)
    skipped='Not reached because the face/crop stage did not produce a photo.'
    bg=values.get('background_removal',{})
    if not options.get('replace_bg'):add('Background removal','Off','Not selected for this run.')
    elif bg.get('status')=='applied':
        detail=bg.get('label',background_models.LABELS.get(bg.get('engine'),'Background model'))
        detail+=' · reused verified source mask' if bg.get('cache_hit') else f" · {bg.get('inference_seconds',0):g} s inference"
        if bg.get('model_sha256'):detail+=f" · model {bg['model_sha256'][:12]}"
        add('Background removal','Applied',detail)
    else:add('Background removal','Unavailable' if has_photo else 'Skipped',bg.get('message',skipped if not has_photo else 'Selected but no successful model output was recorded.'))
    settings=enhancement.validate(options.get('enhancement_options'))
    stages=values.get('local_enhancement',{}).get('stages',[])
    adaptive=values.get('adaptive_quality',{})
    if settings['adaptive_profile']!='off':
        add('Automatic quality profile',adaptive.get('status','Skipped').capitalize(),
            adaptive.get('message',skipped if not has_photo else 'No completed adaptive preparation was recorded.'))
        settings=dict(settings,**{k:adaptive.get('decisions',{}).get(name,0) for k,name in
                                 [('denoise','denoise_percent'),('skin','skin_percent')]})
        stages=stages+adaptive.get('stages',[])
    models={m['engine']:m for stage in stages for m in stage.get('models',[])}
    for key,engine,label in [('lighting','retinex','Retinexformer lighting'),('denoise','nafnet','NAFNet noise cleanup')]:
        model=models.get(engine)
        if model:add(label,'Applied',f"Local model · {model.get('inference_seconds',0):g} s · SHA {model.get('model_sha256','')[:12]}")
        elif not settings[key] and not (key=='lighting' and adaptive.get('decisions',{}).get('lighting_adviser_requested')):add(label,'Off','No correction selected by the controller.' if adaptive else 'Strength is zero.')
        else:add(label,'Unavailable' if has_photo else 'Skipped',skipped if not has_photo else 'Selected model did not complete; this stage was left unchanged.')
    for key,label in [('portrait_tone','Skin lighting and contrast'),('skin','Skin smoothing'),('blemish','Advanced skin cleaning')]:
        stage=next((s for s in stages if s.get('phase') in (key,'adaptive_'+key) or (key=='blemish' and s.get('version','').startswith('skin-cleaner'))),{})
        if key=='blemish':stage=values.get('skin_cleaning',stage)
        if not settings[key]:add(label,'Off','Not selected.')
        elif stage:add(label,'Unavailable' if stage.get('status')=='unavailable' else 'Applied' if stage.get('status')=='applied' else 'Completed',stage.get('message','See detailed processing evidence.'))
        else:add(label,'Unavailable' if has_photo else 'Skipped',skipped if not has_photo else 'No completed local stage was recorded.')
    upscale=next((s for s in stages if s.get('phase')=='upscale'),{})
    if settings['scale']==1:add('Enlargement','Off','Standard master size; AI upscaling not selected.')
    elif upscale.get('status')=='applied':
        names=', '.join(m.get('label',m['engine']) for m in upscale.get('models',[])) or upscale.get('method','Standard interpolation')
        add('Enlargement','Applied',f"{settings['scale']}× · {names}")
    else:add('Enlargement','Unavailable' if has_photo else 'Skipped',skipped if not has_photo else 'Selected enlargement did not complete.')
    detail=next((s.get('detail_method') for s in stages if s.get('detail_method')),None)
    detail_state='Off' if not settings['detail'] else 'Applied' if detail else 'Unavailable' if has_photo else 'Skipped'
    detail_message='Not selected.' if not settings['detail'] else detail or ('No completed detail stage recorded.' if has_photo else skipped)
    add('Detail sharpening',detail_state,detail_message)
    tone_selected=options.get('auto_adjust') or options.get('fix_shadows') or options.get('even_bg') or any(values.get('local_adjustments',{}).get('values',{}).values())
    tone=next((c.get('detail') for c in checks if c['key']=='adjust'),None)
    add('Colour and lighting','Evaluated' if has_photo and tone_selected else 'Skipped' if tone_selected else 'Off',
        (tone or 'Selected local pixel adjustments were evaluated.') if has_photo and tone_selected else skipped if tone_selected else 'Not selected.')
    if adaptive:
        rows[-1]=dict(name='Colour and lighting',state=adaptive.get('status','unavailable').capitalize(),
                      detail=adaptive.get('message','No completed adaptive lighting stage.'))
    highlights=values.get('final_highlights',{})
    native=values.get('ofiq',{})
    state=native.get('status','not_recorded')
    stages=native.get('stages',[])
    add('OFIQ standardized quality','Measured' if state=='completed' else 'Partial' if state=='partial' else 'Off' if state=='off' else 'Unavailable',
        f"Official OFIQ {native.get('version','')} · {len(stages)} image stage(s) · raw and mapped quality values; document thresholds are not calibrated."
        if stages else native.get('message','No native OFIQ assessment was recorded for this revision.'))
    add('Regional hotspots','Measured' if highlights.get('status')=='diagnostic' else 'Not measured',
        f"{len(highlights.get('regions',[]))} facial regions · native JPEG pixels · diagnostic thresholds, not calibrated approval scores."
        if highlights.get('status')=='diagnostic' else 'Use Inspect hotspots to measure facial regions; no hotspot score is invented.')
    ai=ai_state or {};accepted=options.get('ai',{})
    if ai.get('status')=='ready':add('OpenAI','Preview ready',f"{ai.get('model','OpenAI')} returned an image; it is awaiting staff review.")
    elif accepted:add('OpenAI','Accepted',f"{accepted.get('model','OpenAI')} image accepted after staff comparison.")
    else:add('OpenAI',ai.get('status','Not requested').capitalize(),'Optional paid processing is separate from these local tools.')
    return rows
