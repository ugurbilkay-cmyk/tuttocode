"""Isolated native OFIQ 1.2 C API adapter. Original C API is MIT licensed by BSI.

Struct layouts and signatures follow the pinned official ofiq_structs_c.h and
ofiq_libc.h. See docs/OFIQ.md. No model downloads and no cloud calls.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from PIL import Image as PILImage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ofiq import COMMIT, MEASURES, NATIVE_NAMES, VERSION, digest, runtime_manifest


class Image(C.Structure):
    _fields_ = [('width', C.c_uint16), ('height', C.c_uint16), ('depth', C.c_uint8),
                ('data', C.POINTER(C.c_uint8))]
class Box(C.Structure):
    _fields_ = [('x', C.c_int16), ('y', C.c_int16), ('width', C.c_int16), ('height', C.c_int16), ('detector', C.c_int)]
class Measure(C.Structure):
    _fields_ = [('id', C.c_int), ('raw', C.c_double), ('quality', C.c_double), ('code', C.c_int)]
class Assessment(C.Structure):
    _fields_ = [('items', C.POINTER(Measure)), ('count', C.c_size_t), ('box', Box)]


class Native:
    def __init__(self, root, manifest):
        self.lib = C.CDLL(str(root / manifest['library'])); self.handle = C.c_void_p()
        for name, args, result in [
            ('OFIQGetVersion', [C.POINTER(C.c_int)] * 3, None),
            ('OFIQGetQualityMeasureName', [C.c_int], C.c_char_p),
            ('OFIQInitialize', [C.POINTER(C.c_void_p), C.c_char_p, C.c_char_p], C.c_int),
            ('OFIQCleanup', [C.POINTER(C.c_void_p)], C.c_int),
            ('OFIQReadImage', [C.c_char_p, C.POINTER(Image)], C.c_int),
            ('OFIQFreeImage', [C.POINTER(Image)], C.c_int),
            ('OFIQVectorQuality', [C.c_void_p, C.POINTER(Image), C.POINTER(Assessment)], C.c_int),
            ('OFIQFreeFaceImageQualityAssessment', [C.POINTER(Assessment)], C.c_int)]:
            fn = getattr(self.lib, name); fn.argtypes = args; fn.restype = result
        numbers = [C.c_int() for _ in range(3)]
        self.lib.OFIQGetVersion(*(C.byref(n) for n in numbers))
        if '.'.join(str(n.value) for n in numbers) != VERSION: raise ValueError('Native OFIQ version mismatch')
        for ident, name in MEASURES.items():
            native = self.lib.OFIQGetQualityMeasureName(ident)
            if not native or native.decode() != NATIVE_NAMES[ident]: raise ValueError('Native enum mismatch')
        actual = {n: C.sizeof(t) for n, t in [('Image', Image), ('BoundingBox', Box),
                 ('QualityMeasureResult', Measure), ('FaceImageQualityAssessment', Assessment)]}
        if actual != manifest['abi_sizes']: raise ValueError('Native C API layout mismatch')
        cfg = root / manifest['config']
        started = time.perf_counter()
        code = self.lib.OFIQInitialize(C.byref(self.handle), str(cfg.parent).encode(), cfg.name.encode())
        self.initialization_seconds = round(time.perf_counter() - started, 4)
        if code != 0 or not self.handle: raise ValueError('Native OFIQ initialization failed')

    def close(self):
        if self.handle: self.lib.OFIQCleanup(C.byref(self.handle))

    def assess(self, record):
        image, result = Image(), Assessment()
        started = time.perf_counter()
        output = dict(stage=record['stage'], image_sha256=digest(record['path']),
                      return_code=None, measurements=[])
        if output['image_sha256'] != record['sha256']: raise ValueError('Input bytes changed')
        try:
            with PILImage.open(record['path']) as decoded:
                if min(decoded.size) < 32 or max(decoded.size) > 32767: raise ValueError('Unsafe source dimensions')
            code = self.lib.OFIQReadImage(str(record['path']).encode(), C.byref(image))
            if code != 0 or not image.data: raise ValueError('Native image decode failed')
            if not 32 <= image.width <= 32767 or not 32 <= image.height <= 32767 or image.depth != 24:
                raise ValueError('Unsafe native image dimensions or channel depth')
            output['input_size'] = [image.width, image.height]
            output['channel_order'] = 'Native OFIQReadImage BGR'
            code = self.lib.OFIQVectorQuality(self.handle, C.byref(image), C.byref(result))
            output['return_code'] = code
            if result.count > len(MEASURES): raise ValueError('Unexpected native vector size')
            if result.count and not result.items: raise ValueError('Missing native assessment buffer')
            for i in range(result.count):
                m = result.items[i]
                # Copy numbers out before freeing every native allocation.
                output['measurements'].append(dict(id=m.id, name=MEASURES.get(m.id, 'unknown'), native_name=NATIVE_NAMES.get(m.id,'unknown'),
                    raw=float(m.raw) if math.isfinite(m.raw) else None,
                    quality=float(m.quality) if math.isfinite(m.quality) else None, return_code=int(m.code)))
            output['bounding_box'] = [result.box.x, result.box.y, result.box.width, result.box.height]
        finally:
            self.lib.OFIQFreeFaceImageQualityAssessment(C.byref(result))
            self.lib.OFIQFreeImage(C.byref(image))
        output['assessment_seconds'] = round(time.perf_counter() - started, 4)
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('runtime', 'inputs', 'output'): parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args(); root = args.runtime.resolve()
    manifest = runtime_manifest(root, verify=True)
    records = json.loads(args.inputs.read_text())
    if not isinstance(records, list) or not 1 <= len(records) <= 4: raise ValueError('Invalid assessment batch')
    engine = Native(root, manifest)
    try:
        stages = [engine.assess(record) for record in records]
    finally: engine.close()
    args.output.write_text(json.dumps(dict(engine='OFIQ', version=VERSION, source_commit=COMMIT,
        initialization_seconds=engine.initialization_seconds, stages=stages,
        config_sha256=manifest['files'][manifest['config']],
        runtime_manifest_sha256=digest(root / 'manifest.json'),
        library_sha256=manifest['files'][manifest['library']],
        model_bundle_sha256=manifest['model_bundle_sha256'],
        adapter_sha256=digest(__file__)), allow_nan=False))


if __name__ == '__main__': main()
