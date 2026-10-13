"""Explicitly install digest-verified local enhancer weights. Never uploads photos."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.enhancement_models import MODELS,EXPORT_RELEASE


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as source:
        while block:=source.read(4*1024*1024): value.update(block)
    return value.hexdigest()


def download(url,target):
    with urllib.request.urlopen(url,timeout=120) as response,target.open('wb') as out:
        while block:=response.read(4*1024*1024):out.write(block)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engines',nargs='+',choices=MODELS)
    parser.add_argument('--destination',type=Path,default=Path(__file__).resolve().parents[1]/'models/enhancement')
    parser.add_argument('--from-evaluation',type=Path)
    args=parser.parse_args();args.destination.mkdir(parents=True,exist_ok=True)
    for name in args.engines:
        spec=MODELS[name]
        with tempfile.TemporaryDirectory(prefix='enhancer-install-',dir=args.destination) as temporary:
            stage=Path(temporary)
            if args.from_evaluation:
                for file in spec['files']:shutil.copyfile(args.from_evaluation/name/file,stage/file)
            elif spec.get('bundle'):
                bundle=stage/spec['bundle'];download(EXPORT_RELEASE+'/'+spec['bundle'],bundle)
                if digest(bundle)!=spec['bundle_sha256']:raise ValueError('Enhancer export bundle digest mismatch')
                with zipfile.ZipFile(bundle) as archive:
                    for file in spec['files']:
                        with archive.open(spec['prefix']+'/'+file) as source,(stage/file).open('wb') as target:
                            shutil.copyfileobj(source,target)
                bundle.unlink()
            elif spec.get('urls'):
                for file,url in spec['urls'].items():download(url,stage/file)
            else:download(spec['url'],stage/'model.pth')
            for file,expected in spec['files'].items():
                if digest(stage/file)!=expected:raise ValueError('Digest mismatch: '+name+'/'+file)
            licence=Path(__file__).parent/'vendor'/({'retinex':'RETINEXFORMER','nafnet':'NAFNET','plksr':'PLKSR','realesrgan':'REALESRGAN'}[name]+'_LICENSE.txt')
            shutil.copyfile(licence,stage/'LICENSE.txt')
            (stage/'bundle.json').write_text(json.dumps(spec,indent=2))
            destination=args.destination/name;destination.mkdir(exist_ok=True)
            for file in stage.iterdir():os.replace(file,destination/file.name)
        print('Installed verified local enhancer: '+name,flush=True)


if __name__=='__main__':main()
