"""Pinned, previously evaluated background models. No downloads on import."""

VERSION = "portrait-matting-v1"
_CODE = {
    "birefnet.py": "2a45b4e0ece72d7c4212bca1a988e7d7e52bfe9f98ec59c58b8809c8a8b7a831",
    "BiRefNet_config.py": "e7b8c2a74f6cea6a59553d517f71d47f2c1d90e670a13416af17c25fe2f3dc52",
}
MODELS = {
    "hr": dict(label="Maximum detail · BiRefNet HR-matting", resolution=2048,
               repository="ZhengPeng7/BiRefNet_HR-matting", revision="5d6b6f8adcb5b417c871b1d84ceaae9871355b7f", licence="MIT",
               files={**_CODE, "config.json": "d0b779ee9a76bf079673c5852c346f439591f016ca0d778a87bbd1dcbe24398a",
                      "model.safetensors": "a5a4de698739ea5e0e8bbab28e1b293dde95092b87a442d566cbc585c53cef55"}),
    "portrait": dict(label="Faster detail · BiRefNet-portrait", resolution=1024,
                     repository="ZhengPeng7/BiRefNet-portrait", revision="b6561965a70070d9143fd9e558f6ca3c481510db", licence="MIT",
                     files={**_CODE, "config.json": "68a27b9f0058e0d81f8b32655c3b5b8d82838c523243a2851b8269dd3f080a0e",
                            "model.safetensors": "4a4eb3a5469b75f0cccaec6772c22fc30e6c12ed429c2c0ba71b43e3d8d97182"}),
    "modnet": dict(label="Fast · MODNet", resolution=512, licence="Apache-2.0",
                   source="https://drive.google.com/uc?export=download&id=1cgycTQlYXpTh26gB9FTnthE7AvruV8hd",
                   files={"model.onnx": "07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9"}),
}
LABELS = {key: value["label"] for key, value in MODELS.items()}
LABELS["mediapipe"] = "Basic · existing MediaPipe mask"


def validate(engine):
    if engine not in LABELS:
        raise ValueError("Unknown background tool")
    return engine
