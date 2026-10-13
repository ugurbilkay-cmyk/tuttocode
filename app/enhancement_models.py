"""Pinned optional local restoration assets; no model downloads during editing."""
VERSION = "local-enhancer-v1"
MODELS = {
    "retinex": dict(label="Low-light recovery · Retinexformer", licence="MIT",
        repository="https://github.com/caiyuanhao1998/Retinexformer",
        revision="1e9a0efce4b306b6701b824768370ff26066c32a",
        files={"model.pth":"9b4810dc51322fab70be8658ee0ad1df64a54aa814497b7849767baa2ff32cd1"},
        url="https://drive.google.com/uc?export=download&id=1xDwQtTCj3tlAVCTJgYrzonBGVwqeOhKu"),
    "nafnet": dict(label="Noise cleanup · NAFNet", licence="MIT / Apache-2.0",
        repository="https://github.com/megvii-research/NAFNet",
        revision="2b4af71ebe098a92a75910c233a3965a3e93ede4",
        files={"model.onnx":"8b437280db2f9f0ef5c733fa0fec70fc10012a62d19dac24a25b80ec8c529230"},
        bundle="denoise-nafnet.dtmodel", bundle_sha256="4b5c0b9c2650956eaab9a3fc6ffe3e11d4dc4f55b246b7f3a0d2d72161b6980c", prefix="denoise-nafnet"),
    "plksr": dict(label="Natural AI upscale · RealPLKSR", licence="MIT",
        repository="https://github.com/dslisleedh/PLKSR",
        files={"model_x2.onnx":"d7abb65092f3808d3aa255ffdab42b1d672883915d90adbdd321204168b9f293",
               "model_x4.onnx":"8ce692652494e2e5c31e1f7c7ab61eb084e9a450cde727a374f5d6746cfe054b"},
        bundle="upscale-realplksr.dtmodel", bundle_sha256="7f7b4942b2363691628f10c52bce66ff3ac67d07d4d55c3804d3f89fc9cd6ba7", prefix="upscale-realplksr"),
    "realesrgan": dict(label="Fast smooth AI upscale · Real-ESRGAN", licence="BSD-3-Clause",
        repository="https://github.com/xinntao/Real-ESRGAN",revision="a4abfb2979a7bbff3f69f58f58ae324608821e27",
        files={"general.pth":"8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292",
               "general-wdn.pth":"1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca"},
        urls={"general.pth":"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
              "general-wdn.pth":"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth"}),
}
# These two graphs are darktable-ai release-5.6.0 exports, not its GPL application
# or converter code. The learned weights retain their upstream model licences.
EXPORT_RELEASE = "https://github.com/darktable-org/darktable-ai/releases/download/release-5.6.0"
RETINEX_ARCH_SHA256 = "1567c89d55285a3c1a4d4ca33f288b1fd98dc6b6bbdf971eda02d745f9087631"
SRVGG_ARCH_SHA256 = "e00a5886004a563c6ca0b9868513ec004687ba7103941fffabf278465a1bec59"
