"""Offline ModelScope local blemish detection/repair. No global whitening or tone model."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import enhancement_models as models
from scripts.enhancement_worker import verify


def repair_mask(probability,allowed,sensitivity,spot_size):
    import cv2
    import numpy as np
    threshold={'gentle':.5,'standard':.35,'strong':.25}[sensitivity]
    mask=np.where(probability>=threshold,np.where(probability>=.5,1.,probability),0).astype(np.float32)*allowed
    count,labels,stats,_=cv2.connectedComponentsWithStats((mask>.01).astype(np.uint8),8)
    maximum={'small':.0025,'medium':.01,'large':.03,'all':1.}[spot_size]*max(1,int((allowed>0).sum()))
    spots=0
    for label in range(1,count):
        area=stats[label,cv2.CC_STAT_AREA]
        if area<2 or area>maximum:mask[labels==label]=0
        else:spots+=1
    return mask,spots,threshold


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('input','allowed','output','models'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--roi',required=True);parser.add_argument('--settings',required=True)
    args=parser.parse_args()
    from app.enhancement import validate
    import cv2
    import numpy as np
    from PIL import Image
    import torch
    import torch.nn.functional as F
    spec=models.MODELS['blemish'];checkpoint=args.models/'blemish/joint_20210926.pth'
    verify(checkpoint,spec['files']['joint_20210926.pth'])
    for name,digest in models.BLEMISH_ARCH.items():verify(Path(__file__).parent/'vendor/modelscope_skin'/name,digest)
    from vendor.modelscope_skin.detection_unet_in import DetectionUNet
    from vendor.modelscope_skin.inpainting_unet import RetouchingNet
    torch.set_num_threads(6)
    v=validate(json.loads(args.settings))
    with Image.open(args.input) as image:rgb=np.array(image.convert('RGB'))
    allowed=np.load(args.allowed,allow_pickle=False)
    if allowed.shape!=rgb.shape[:2] or not np.isfinite(allowed).all() or not 0<=allowed.min()<=allowed.max()<=1:
        raise ValueError('Invalid permitted skin mask')
    x0,y0,x1,y1=map(int,json.loads(args.roi));h,w=rgb.shape[:2]
    if not 0<=x0<x1<=w or not 0<=y0<y1<=h:raise ValueError('Invalid face crop')
    started=time.perf_counter()
    weights=torch.load(checkpoint,map_location='cpu',weights_only=True)
    detector=DetectionUNet(n_channels=3,n_classes=1,init_weights=False).eval()
    detector.load_state_dict(weights['detection_net'],strict=True)
    roi=rgb[y0:y1,x0:x1];rh,rw=roi.shape[:2]
    tensor=torch.from_numpy(roi.transpose(2,0,1)[None].copy()).float()/127.5-1
    with torch.inference_mode():
        logits=detector(F.interpolate(tensor,(768,768),mode='bilinear',align_corners=True))
        probability=F.interpolate(torch.sigmoid(logits),(rh,rw),mode='nearest')[0,0].numpy()
    del detector,logits
    if not np.isfinite(probability).all():raise ValueError('Invalid detector output')
    mask,spots,threshold=repair_mask(probability,allowed[y0:y1,x0:x1],v['blemish_sensitivity'],v['blemish_size'])
    prediction=roi.astype(np.float32)/255
    if mask.any():
        network=RetouchingNet(in_channels=4,out_channels=3,init_weights=False)
        # Upstream overrides train() without returning self; don't chain eval().
        network.eval()
        network.load_state_dict(weights['inpainting_net'],strict=True)
        # Match upstream's 512-pixel cores with 32-pixel context on each side.
        ph,pw=((rh+511)//512)*512,((rw+511)//512)*512
        source=F.pad(tensor,(32,pw-rw+32,32,ph-rh+32),value=0)
        keep=F.pad(torch.from_numpy(1-mask)[None,None],(32,pw-rw+32,32,ph-rh+32),value=0)
        predicted=np.empty((ph,pw,3),np.float32)
        with torch.inference_mode():
            for y in range(0,ph,512):
                for x in range(0,pw,512):
                    sub=source[:,:,y:y+576,x:x+576];known=keep[:,:,y:y+576,x:x+576]
                    reconstructed=network(sub*known,known)
                    if not torch.isfinite(reconstructed).all():raise ValueError('Invalid repair prediction')
                    predicted[y:y+512,x:x+512]=(reconstructed[0,:,32:544,32:544].permute(1,2,0).numpy()+1)/2
        prediction=np.clip(predicted[:rh,:rw],0,1)
        del network
    # Only detected, permitted pixels can change; blend never touches known areas.
    alpha=mask*v['blemish']/100
    output=rgb.copy()
    output[y0:y1,x0:x1]=np.rint(np.clip(roi.astype(np.float32)*(1-alpha[...,None])+prediction*255*alpha[...,None],0,255)).astype(np.uint8)
    full_mask=np.zeros((h,w),np.float32);full_mask[y0:y1,x0:x1]=alpha
    np.save(args.output.with_suffix('.npy'),full_mask,allow_pickle=False)
    Image.fromarray(output).save(args.output)
    args.output.with_suffix('.json').write_text(json.dumps(dict(engine='blemish',model_sha256=spec['files']['joint_20210926.pth'],
        code_revision=models.BLEMISH_CODE_REVISION,source_size=[w,h],settings=v,roi=[x0,y0,x1,y1],
        candidate_spots=spots,threshold=threshold,inference_seconds=round(time.perf_counter()-started,3),
        mask_sha256=hashlib.sha256(full_mask.astype('<f4').tobytes()).hexdigest(),runtime='CPU FP32 · 6 threads')))


if __name__=='__main__':main()
