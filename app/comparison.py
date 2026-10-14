"""Source-only comparison rendering. No analysis, enhancement or remote calls."""
import io
import math

import cv2
import numpy as np
from PIL import Image,ImageOps

VERSION='matched-source-comparison-v1'


def render(source,measurements,options,size,country_id):
    """Unedited processing input on the saved result's exact geometry/grid.

    This is a resampled source, not the original camera file. Camera and accepted
    AI inputs are distinguished by the caller. Missing geometry fails closed;
    a small thumbnail is never enlarged as a substitute for the source.
    """
    from . import processing as P,photomatic
    size=tuple(map(int,size))
    if len(size)!=2 or min(size)<1 or size[0]*size[1]>40_000_000:
        raise ValueError('Comparison output size is invalid')
    rgb=P.load_image(source)
    profile=photomatic.country(country_id)
    if measurements.get('print_only'):
        colour=tuple(measurements.get('comparison_padding_colour',profile['background']))
        return P._encode_jpeg(np.asarray(ImageOps.pad(Image.fromarray(rgb),size,
            method=Image.Resampling.LANCZOS,color=colour)))
    crop=options.get('crop',{})
    rotation=int(crop.get('rotation',0))%360
    if rotation:rgb=np.ascontiguousarray(np.rot90(rgb,-(rotation//90)))
    angle=float(crop.get('angle',0))
    if angle:
        h,w=rgb.shape[:2]
        matrix=cv2.getRotationMatrix2D((w/2,h/2),-angle,1)
        nw=int(np.ceil(h*abs(matrix[0,1])+w*abs(matrix[0,0])))
        nh=int(np.ceil(h*abs(matrix[0,0])+w*abs(matrix[0,1])))
        matrix[:,2]+=[(nw-w)/2,(nh-h)/2]
        rgb=cv2.warpAffine(rgb,matrix,(nw,nh),borderValue=(0,0,0))
    expected=measurements.get('analysis_size')
    if expected and list(expected)!=[rgb.shape[1],rgb.shape[0]]:
        raise ValueError('Comparison source dimensions changed')
    working=tuple(map(int,measurements.get('quality_sampling_size',size)))
    if len(working)!=2 or min(working)<1 or working[0]*working[1]>40_000_000:
        raise ValueError('Comparison sampling size is invalid')
    if not profile['use_head'] and not profile['use_width']:
        out=np.asarray(ImageOps.fit(Image.fromarray(rgb),working,method=Image.Resampling.LANCZOS))
    else:
        rect=measurements.get('crop_geometry',{}).get('source_rect')
        if not isinstance(rect,list) or len(rect)!=4 or not all(math.isfinite(float(x)) for x in rect):
            raise ValueError('Comparison source geometry is missing')
        x,y,w,h=map(float,rect)
        if w<=0 or h<=0:raise ValueError('Comparison crop is invalid')
        matrix=np.array([[working[0]/w,0,-x*working[0]/w],
                         [0,working[1]/h,-y*working[1]/h]],np.float32)
        out=cv2.warpAffine(rgb,matrix,working,flags=cv2.INTER_AREA,borderMode=cv2.BORDER_REPLICATE)
    if working!=size:out=cv2.resize(out,size,interpolation=cv2.INTER_LANCZOS4)
    return P._encode_jpeg(out)


def size(data):
    with Image.open(io.BytesIO(data)) as im:return im.size
