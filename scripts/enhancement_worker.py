"""One-shot CPU restoration. Pinned assets, no downloads or face-specific model."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import enhancement_models as models


def verify(path,expected):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        while block:=source.read(4*1024*1024): digest.update(block)
    if digest.hexdigest()!=expected: raise ValueError('Enhancer asset differs from pinned digest')


def tiled(rgb,predict,tile,scale,halo=32):
    """Fixed ONNX tiles with reflected context and exact coverage of edge remainders."""
    import numpy as np
    h,w=rgb.shape[:2];core=tile-2*halo
    padded=np.pad(rgb,((halo,tile),(halo,tile),(0,0)),mode='reflect' if min(h,w)>1 else 'edge')
    out=np.empty((h*scale,w*scale,3),np.float32)
    for y in range(0,h,core):
        for x in range(0,w,core):
            patch=padded[y:y+tile,x:x+tile]
            tensor=patch.astype(np.float32).transpose(2,0,1)[None]/255
            result=predict(tensor)[0].transpose(1,2,0)
            if result.shape!=(tile*scale,tile*scale,3) or not np.isfinite(result).all():
                raise ValueError('Invalid model tile')
            ch,cw=min(core,h-y),min(core,w-x);a=halo*scale
            out[y*scale:(y+ch)*scale,x*scale:(x+cw)*scale]=result[a:a+ch*scale,a:a+cw*scale]
    return np.clip(out,0,1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('models','input','output'): p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--phase',choices=['restore','upscale'],required=True);p.add_argument('--settings',required=True)
    args=p.parse_args()
    # Import validation only after argument parsing; all compute remains local.
    from app.enhancement import validate,required
    import cv2
    import numpy as np
    from PIL import Image
    v=validate(json.loads(args.settings));engines=required(v,args.phase)
    evidence=[]
    for name in engines:
        file=f'model_x{v["scale"]}.onnx' if name=='plksr' else 'model.onnx' if name=='nafnet' else 'general.pth' if name=='realesrgan' else 'model.pth'
        verify(args.models/name/file,models.MODELS[name]['files'][file])
        if name=='realesrgan':verify(args.models/name/'general-wdn.pth',models.MODELS[name]['files']['general-wdn.pth'])
    with Image.open(args.input) as im: rgb=np.array(im.convert('RGB'))
    source_size=[rgb.shape[1],rgb.shape[0]]
    started=time.perf_counter()
    for name in engines:
        spec=models.MODELS[name];scale=v['scale'] if name in ('plksr','realesrgan') else 1
        file=f'model_x{scale}.onnx' if name=='plksr' else 'model.onnx' if name=='nafnet' else 'general.pth' if name=='realesrgan' else 'model.pth'
        stage=time.perf_counter()
        if name=='retinex':
            import torch
            torch.set_num_threads(6)
            architecture=Path(__file__).parent/'vendor/retinexformer.py'
            verify(architecture,models.RETINEX_ARCH_SHA256)
            from vendor.retinexformer import RetinexFormer
            net=RetinexFormer(n_feat=40,stage=1,num_blocks=[1,2,2]).eval()
            weights=torch.load(args.models/name/file,map_location='cpu',weights_only=True)
            net.load_state_dict(weights['params'],strict=True)
            h,w=rgb.shape[:2];ratio=min(1.,1024/max(h,w))
            size=(max(8,round(w*ratio)),max(8,round(h*ratio)))
            small=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA).astype(np.float32)/255
            padded=np.pad(small,((0,(-size[1])%8),(0,(-size[0])%8),(0,0)),mode='reflect')
            with torch.inference_mode():
                restored=net(torch.from_numpy(padded.transpose(2,0,1)[None].copy())).numpy()[0].transpose(1,2,0)[:size[1],:size[0]]
            if not np.isfinite(restored).all(): raise ValueError('Invalid illumination prediction')
            # Transfer a smooth, bounded RGB illumination field onto source pixels.
            # The network never supplies replacement facial detail in this mode.
            gain=np.clip(restored/np.maximum(small,.02),.5,4.)
            gain=cv2.GaussianBlur(gain,(0,0),3)
            gain=cv2.resize(gain,(w,h),interpolation=cv2.INTER_LINEAR)
            prediction=np.clip(rgb.astype(np.float32)/255*gain,0,1)
            strength=v['lighting']/100
            del net,weights
            method='Retinexformer LOL-v1 · smooth illumination transfer (gain 0.5–4)'
        elif name=='realesrgan':
            import torch
            torch.set_num_threads(6)
            verify(Path(__file__).parent/'vendor/srvgg.py',models.SRVGG_ARCH_SHA256)
            from vendor.srvgg import SRVGGNetCompact
            net=SRVGGNetCompact(num_conv=32).eval()
            normal=torch.load(args.models/name/'general.pth',map_location='cpu',weights_only=True)['params']
            weak=torch.load(args.models/name/'general-wdn.pth',map_location='cpu',weights_only=True)['params']
            # Official two-checkpoint interpolation; modest built-in denoising.
            net.load_state_dict({k:normal[k]*.25+weak[k]*.75 for k in normal},strict=True)
            def predict(tensor):
                with torch.inference_mode():return net(torch.from_numpy(tensor.copy())).numpy()
            prediction=tiled(rgb,predict,256,4)
            if scale==2:prediction=cv2.resize(prediction,(rgb.shape[1]*2,rgb.shape[0]*2),interpolation=cv2.INTER_AREA)
            strength=v['upscale_strength']/100
            method='Real-ESRGAN general-x4v3 · DNI noise 0.25 · overlapping-context tiles'
            del net,normal,weak
        else:
            import onnxruntime as ort
            options=ort.SessionOptions();options.intra_op_num_threads=6;options.inter_op_num_threads=1
            session=ort.InferenceSession(str(args.models/name/file),sess_options=options,providers=['CPUExecutionProvider'])
            tile=768 if name=='nafnet' else 512 if scale==2 else 256
            prediction=tiled(rgb,lambda t:session.run(None,{session.get_inputs()[0].name:t})[0],tile,scale)
            strength=(v['denoise'] if name=='nafnet' else v['upscale_strength'])/100
            del session
            method='NAFNet SIDD · overlapping-context tiles' if name=='nafnet' else 'RealPLKSR MSSIM pretrain · overlapping-context tiles'
        base=rgb.astype(np.float32)/255
        if scale!=1: base=cv2.resize(base,(rgb.shape[1]*scale,rgb.shape[0]*scale),interpolation=cv2.INTER_LANCZOS4)
        rgb=np.rint(np.clip(base*(1-strength)+prediction*strength,0,1)*255).astype(np.uint8)
        evidence.append(dict(engine=name,label=spec['label'],method=method,licence=spec['licence'],
            repository=spec['repository'],model_sha256=spec['files'][file],strength=strength,
            inference_seconds=round(time.perf_counter()-stage,3)))
        if name=='realesrgan':evidence[-1]['secondary_model_sha256']=spec['files']['general-wdn.pth']
    Image.fromarray(rgb).save(args.output)
    args.output.with_suffix('.json').write_text(json.dumps(dict(phase=args.phase,settings=v,models=evidence,
        source_size=source_size,output_size=[rgb.shape[1],rgb.shape[0]],runtime='CPU FP32 · 6 threads',
        inference_seconds=round(time.perf_counter()-started,3))))


if __name__=='__main__':main()
