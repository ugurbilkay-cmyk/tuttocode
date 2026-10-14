"""OpenAI image edits, separate from local measurements and code issuance."""
import base64
import binascii
import io
import json
import math
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from PIL import Image, ImageOps

from . import config

ENDPOINT = "https://api.openai.com/v1/images/edits"
MAX_RESPONSE_BYTES = 40 * 1024 * 1024
PROMPT_VERSION = "portrait-cleanup-v2"


class PreparationError(Exception):
    """A staff-readable error; never includes the API key or provider payload."""


@dataclass
class PreparedImage:
    image: bytes
    model: str
    request_id: str
    prompt_version: str = PROMPT_VERSION


def prepare(data, *, lighting=True, colour=True, print_only=False):
    if not config.OPENAI_API_KEY:
        raise PreparationError("OpenAI is not connected. Configure OPENAI_API_KEY on the server.")
    if not lighting and not colour:
        raise PreparationError("Choose lighting correction or colour correction.")
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    # Strip camera metadata and keep the original safely in local job storage.
    image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    w, h = image.size
    if not 1 / 3 <= w / h <= 3:
        raise PreparationError("Use a portrait or ordinary landscape camera photo.")
    # Keep enough real source resolution for passport cropping; cap the requested
    # output at the model's documented non-experimental 2K pixel area.
    scale = min(1, math.sqrt(3_686_400 / (w * h)))
    if print_only:
        # A print/edit preview can request a larger canvas, without claiming
        # additional source detail or a passport-quality verdict.
        scale = min(max(1, 512/min(w,h), math.sqrt(1_048_576/(w*h))),
                    math.sqrt(3_686_400/(w*h)))
    width, height = max(16, round(w * scale / 16) * 16), max(16, round(h * scale / 16) * 16)
    while width * height > 3_686_400:
        if width >= height:
            width -= 16
        else:
            height -= 16
    while width > 3 * height:
        width -= 16
    while height > 3 * width:
        height -= 16
    blob = io.BytesIO()
    image.save(blob, "PNG")
    instructions = []
    if lighting:
        instructions.append("Correct overall exposure and gently balance uneven facial illumination. Soften harsh lighting shadows only where existing image detail is visible. Reduce excessive specular shine and hotspots while preserving visible skin texture and natural shading; do not darken clipped patches to pretend lost detail has been recovered. Do not create new clipped highlights or sharpen glare.")
    if colour:
        instructions.append("Correct an obvious camera white-balance colour cast while preserving the person's natural skin tone; do not lighten or recolour their complexion.")
    prompt = (
        "TASK: Make one gentle, natural photographic enhancement of this existing camera portrait. " + " ".join(instructions) +
        " SKIN AND DETAIL: Lightly clean skin surface noise and soften distracting fine texture without an airbrushed or plastic finish. Preserve natural pores, skin texture, wrinkles and age cues. Clean only clearly temporary tiny surface spots; retain any uncertain mark. Preserve every mole, freckle, scar, birthmark and other distinguishing mark."
        " Apply gentle, natural sharpening only to existing visible detail, keeping eyes, eyelashes, hair and facial edges clear. Do not invent pores, eyelashes or texture, reconstruct the face, create sharpening halos, or intensify bright skin patches. Leave genuinely missing, blurred or clipped detail unresolved."
        " IDENTITY HAS PRIORITY: Preserve the exact person's likeness and facial biometrics: face and head geometry, proportions and distances between features, eye and iris colour, eyelids, nose, mouth, ears, jaw, hairline, hair, beard, expression, pose and age. Do not reshape, slim, enlarge, beautify facial features, open eyes, change an expression, remove identifying marks, add makeup or change clothing. If cleanup conflicts with preserving a feature or mark, leave that area unchanged."
        " FRAMING AND OUTPUT: Keep the original composition, perspective, field of view and background. Do not crop, rotate, replace the background, remove objects or add objects or text; our application handles framing and background separately. Return only the enhanced photograph."
    )
    payload = {
        "model": config.OPENAI_IMAGE_MODEL,
        "images": [{"image_url": "data:image/png;base64," + base64.b64encode(blob.getvalue()).decode("ascii")}],
        "prompt": prompt, "n": 1, "size": f"{width}x{height}",
        "quality": "high", "output_format": "png",
    }
    # Legacy models have fixed sizes and an explicit facial preservation option.
    if config.OPENAI_IMAGE_MODEL in ("gpt-image-1", "gpt-image-1.5"):
        payload.update(input_fidelity="high", size="auto")
    request = urllib.request.Request(ENDPOINT, json.dumps(payload).encode(), headers={
        "Authorization": "Bearer " + config.OPENAI_API_KEY, "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=config.OPENAI_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            request_id = response.headers.get("x-request-id", "")[:200]
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PreparationError("OpenAI returned an oversized image response.")
        body = json.loads(raw)
        output = base64.b64decode(body["data"][0]["b64_json"], validate=True)
        with Image.open(io.BytesIO(output)) as edited:
            ew, eh = edited.size
            if ew * eh > 16_000_000 or min(ew, eh) < 500 or abs((ew / eh) / (w / h) - 1) > .02:
                raise PreparationError("The AI result changed the image format. Keep the original or prepare again.")
            edited.verify()
        return PreparedImage(output, config.OPENAI_IMAGE_MODEL, request_id)
    except urllib.error.HTTPError as exc:
        message = {
            401: "OpenAI rejected the API key. Check the server connection.",
            403: "The OpenAI account cannot use this image model. Check account access.",
            429: "OpenAI is busy or the account limit was reached. Try again later.",
        }.get(exc.code, "OpenAI could not prepare this photo. The original is unchanged.")
        raise PreparationError(message) from None
    except (TimeoutError, socket.timeout, urllib.error.URLError):
        raise PreparationError("OpenAI did not finish in time. No edit was applied; try again later.") from None
    except (KeyError, IndexError, TypeError, ValueError, binascii.Error, OSError):
        raise PreparationError("OpenAI did not return a readable edited image. The original is unchanged.") from None
