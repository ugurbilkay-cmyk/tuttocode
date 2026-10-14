"""Install explicitly selected, digest-verified model bundles. No photo upload."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.background_models import MODELS

LICENCES = {
    "MIT": ("https://raw.githubusercontent.com/ZhengPeng7/BiRefNet/c4d649666cc171486329413dc2b61f0137158b6a/LICENSE",
            "92a7089e0915fc32bc40067560b398f1e6a7a5958abd7d04eda393629a5acefb"),
    "Apache-2.0": ("https://raw.githubusercontent.com/ZHKKKe/MODNet/28165a451e4610c9d77cfdf925a94610bb2810fb/LICENSE",
                   "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
}


def download(url, path):
    with urllib.request.urlopen(url,timeout=90) as response,path.open("wb") as target:
        while block:=response.read(4*1024*1024):
            target.write(block)


def digest(path):
    value=hashlib.sha256()
    with path.open("rb") as source:
        while block:=source.read(4*1024*1024): value.update(block)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engines",nargs="+",choices=MODELS)
    parser.add_argument("--destination",type=Path,default=Path(__file__).resolve().parents[1]/"models/background")
    parser.add_argument("--from-evaluation",type=Path,help="Reuse private evaluated local files rather than download weights again")
    args=parser.parse_args();args.destination.mkdir(parents=True,exist_ok=True)
    for engine in args.engines:
        specification=MODELS[engine]
        with tempfile.TemporaryDirectory(prefix="install-",dir=args.destination) as folder:
            stage=Path(folder)
            for name,expected in specification["files"].items():
                target=stage/name
                if args.from_evaluation:
                    shutil.copyfile(args.from_evaluation/engine/name,target)
                else:
                    url=specification.get("source") or f'https://huggingface.co/{specification["repository"]}/resolve/{specification["revision"]}/{name}'
                    download(url,target)
                if digest(target)!=expected:
                    raise ValueError(f"Digest mismatch for {engine}/{name}; installation stopped")
            licence_url,licence_hash=LICENCES[specification["licence"]]
            download(licence_url,stage/"LICENSE")
            if digest(stage/"LICENSE")!=licence_hash: raise ValueError("Licence digest mismatch")
            (stage/"bundle.json").write_text(json.dumps(specification,indent=2))
            destination=args.destination/engine;destination.mkdir(exist_ok=True)
            for path in stage.iterdir(): os.replace(path,destination/path.name)
        print(f"Installed verified {engine} bundle",flush=True)


if __name__=="__main__":main()
