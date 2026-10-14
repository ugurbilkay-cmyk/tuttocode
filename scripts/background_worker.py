"""One-shot local inference. Heavy dependencies live outside the web runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import background_models as models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=models.MODELS)
    parser.add_argument("--models", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    specification = models.MODELS[args.engine]
    snapshot = args.models / args.engine
    for name, expected in specification["files"].items():
        digest = hashlib.sha256()
        with (snapshot/name).open("rb") as handle:
            while block := handle.read(4*1024*1024):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError("Background model bundle differs from pinned revision")

    import numpy as np
    from PIL import Image
    with Image.open(args.input) as source:
        image = source.convert("RGB")
    width, height = image.size
    if args.engine == "modnet":
        import cv2
        import onnxruntime as ort
        options = ort.SessionOptions(); options.intra_op_num_threads = 6
        model = ort.InferenceSession(str(snapshot/"model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        scale = 512 / min(width, height) if max(width,height) < 512 or min(width,height) > 512 else 1
        # Bound unusual panoramic uploads; normal portrait preprocessing matches
        # the evaluated upstream pipeline. Keep native output geometry.
        scale = min(scale, 2048/max(width,height))
        size = [max(32, int(width*scale)//32*32), max(32, int(height*scale)//32*32)]
        normalized = (np.asarray(image).astype(np.float64)-127.5)/127.5
        normalized = cv2.resize(normalized, tuple(size), interpolation=cv2.INTER_AREA)
        tensor = normalized.transpose(2,0,1)[None].astype(np.float32)
        started = time.perf_counter()
        prediction = model.run(None,{model.get_inputs()[0].name:tensor})[0].squeeze()
        model_file = "model.onnx"
    else:
        import torch
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
        torch.set_num_threads(6)
        model = AutoModelForImageSegmentation.from_pretrained(str(snapshot.resolve()), trust_remote_code=True,
                                                            local_files_only=True).eval().to("cpu")
        size = [specification["resolution"]]*2
        transform = transforms.Compose([transforms.Resize(tuple(size)), transforms.ToTensor(),
                                        transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
        tensor = transform(image).unsqueeze(0)
        started = time.perf_counter()
        with torch.inference_mode():
            prediction = model(tensor)[-1].sigmoid()[0,0].cpu().numpy()
        model_file = "model.safetensors"
    inference_seconds = time.perf_counter()-started
    alpha_image = Image.fromarray(prediction.astype(np.float32),mode="F").resize(image.size,Image.Resampling.BILINEAR)
    alpha = np.clip(np.asarray(alpha_image),0,1).astype(np.float32)
    np.save(args.output,alpha,allow_pickle=False)
    args.output.with_suffix(".json").write_text(json.dumps(dict(
        engine=args.engine, model_sha256=specification["files"][model_file], licence=specification["licence"],
        repository=specification.get("repository"), revision=specification.get("revision"),
        runtime="CPU FP32 · 6 threads", input_size=size, source_size=[width,height],
        inference_seconds=round(inference_seconds,3))))


if __name__ == "__main__":
    main()
