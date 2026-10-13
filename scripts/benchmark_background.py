"""Evaluate a reviewed local matting snapshot without changing the studio engine.

No downloads, OpenAI requests, auto-approval, or generative edits. See
docs/BACKGROUND_REMOVAL.md for snapshot provenance and evaluation limitations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageOps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--engine", choices=("birefnet", "modnet"), default="birefnet")
    parser.add_argument("--resolution", type=int, choices=(1024, 2048))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    if args.engine == "birefnet" and args.resolution is None:
        parser.error("BiRefNet requires its published --resolution")
    verified = json.loads((args.snapshot / "verified-model.json").read_text())
    weight_hash = hashlib.sha256()
    weight_path = args.snapshot / ("model.safetensors" if args.engine == "birefnet" else "model.onnx")
    with weight_path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            weight_hash.update(block)
    if weight_hash.hexdigest() != verified["sha256"]:
        raise ValueError("Local weight digest differs from the recorded snapshot")

    started = time.perf_counter()
    if args.engine == "birefnet":
        # The official snapshot includes custom architecture code. It is
        # reviewed/pinned, never fetched during staff processing.
        import torch
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
        torch.set_num_threads(6)
        model = AutoModelForImageSegmentation.from_pretrained(
            str(args.snapshot.resolve()), trust_remote_code=True, local_files_only=True
        ).eval().to("cpu")
        transform = transforms.Compose([
            transforms.Resize((args.resolution, args.resolution)),
            transforms.ToTensor(),
            transforms.Normalize([.485, .456, .406], [.229, .224, .225]),
        ])
    else:
        import cv2
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 6
        model = ort.InferenceSession(str(weight_path), sess_options=options, providers=["CPUExecutionProvider"])
    load_seconds = time.perf_counter() - started
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for index, path in enumerate(args.images):
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        rgb = np.asarray(image)
        if args.engine == "birefnet":
            tensor = transform(image).unsqueeze(0)
            input_size = [args.resolution, args.resolution]
        else:
            # Match official MODNet ONNX normalization and aspect-preserving
            # resize: reference short side 512, multiples of 32.
            width, height = image.size
            scale = 512 / min(width, height) if max(width, height) < 512 or min(width, height) > 512 else 1
            input_size = [int(width * scale) // 32 * 32, int(height * scale) // 32 * 32]
            normalized = (rgb.astype(np.float64) - 127.5) / 127.5
            normalized = cv2.resize(normalized, tuple(input_size), interpolation=cv2.INTER_AREA)
            tensor = normalized.transpose(2, 0, 1)[None].astype(np.float32)
        started = time.perf_counter()
        if args.engine == "birefnet":
            with torch.inference_mode():
                prediction = model(tensor)[-1].sigmoid()[0, 0].cpu().numpy()
        else:
            prediction = model.run(None, {model.get_inputs()[0].name: tensor})[0].squeeze()
        inference_seconds = time.perf_counter() - started
        # Keep continuous alpha and the original raster geometry. No binary
        # erosion, hole-filling or edge blur that could delete fine hair.
        alpha_image = Image.fromarray(prediction.astype(np.float32), mode="F").resize(
            image.size, Image.Resampling.BILINEAR
        )
        alpha = np.clip(np.asarray(alpha_image), 0, 1)
        label = f"{index + 1:02d}-{path.stem}"
        np.save(args.output / f"{label}-alpha.npy", alpha)
        Image.fromarray(np.rint(alpha * 255).astype(np.uint8)).save(args.output / f"{label}-alpha.png")
        rgba = image.copy()
        rgba.putalpha(Image.fromarray(np.rint(alpha * 255).astype(np.uint8)))
        rgba.save(args.output / f"{label}-cutout.png")
        for colour_name, colour in (("grey", (228, 228, 228)), ("black", (0, 0, 0)), ("white", (255, 255, 255))):
            composited = np.rint(rgb * alpha[..., None] + np.asarray(colour) * (1 - alpha[..., None]))
            Image.fromarray(np.clip(composited, 0, 255).astype(np.uint8)).save(args.output / f"{label}-{colour_name}.png")
        record = dict(source_label=path.name, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      source_size=list(image.size), input_size=input_size, inference_seconds=round(inference_seconds, 3),
                      intermediate_alpha_fraction=float(((alpha > .01) & (alpha < .99)).mean()))
        records.append(record)
        print(json.dumps(record), flush=True)
    try:
        import resource
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        maxrss = None
    report = dict(model=verified, engine=args.engine, runtime="CPU FP32, 6 threads", input_resolution=args.resolution,
                  load_seconds=round(load_seconds, 3), maxrss_raw=maxrss,
                  maxrss_note="process peak; OS-specific units; not isolated model allocation",
                  results=records, accuracy="not measured: these photos have no reference alpha matte")
    (args.output / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
