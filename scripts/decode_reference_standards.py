"""Decode allowlisted reference rules into a field guide and per-profile records.

No executables are run. No email, device, customer or credential configuration is
exported. Missing XML flags remain distinguishable from explicit false values.
"""
import argparse
import hashlib
import json
from pathlib import Path

from import_photomatic import flag, key, number, value, xml


# Meanings follow the supplied country manual and UI labels. Names alone do not
# establish undocumented enum semantics or native engine scoring algorithms.
FIELDS = {
    "LandCode": ("Legacy identifier; do not assume this is an ISO country code", "identifier"),
    "LandName": ("Country/document display label", "text"),
    "URLforSpecs": ("Stored specification link; may be stale or refer to another country", "URL"),
    "strFormat": ("Named aspect-ratio format", "enum name"),
    "Format": ("Serialized format selection", "enum name"),
    "iCanvasWidth": ("Physical photo width", "mm"),
    "iCanvasHeight": ("Physical photo height", "mm"),
    "bUseOverlay": ("Display the reference guide overlay", "boolean"),
    "OverlayFileName": ("Overlay artwork reference", "filename"),
    "FlagFileName": ("Country flag artwork reference", "filename"),
    "DefaultPrintTemplateName": ("Default sheet layout reference", "filename"),
    "SaveTemplateName": ("Default digital Save profile reference", "filename"),
    "EmailTemplateName": ("Default digital Email profile reference", "filename"),
    "bUseISOtemplate": ("Use the country's named quality profile instead of the global selection", "boolean"),
    "ISOtemplatename": ("Country quality-profile override reference", "filename"),
    "BackgroundColor": ("Optional serialized colour value; not a quality score", "serialized colour"),
    "BackgroundColorMin": ("Optional serialized lower colour bound", "serialized colour"),
    "BackgroundColorMax": ("Optional serialized upper colour bound", "serialized colour"),
    "bSpecialMode": ("Additional document workflow enabled", "boolean"),
    "iRadioButton2Use": ("Legacy special-mode button selection; enum mapping not established", "selector"),
    "RadioBtnlabel": ("Label for the special workflow action", "text"),
    "App2Start": ("Legacy external application reference; basename only", "filename"),
    "RequiredDigitalWidth": ("Required digital export width; -1 means no explicit requirement", "pixels"),
    "RequiredDigitalHeight": ("Required digital export height; -1 means no explicit requirement", "pixels"),
    "RequiredDigitalFileSizeMin": ("Minimum digital JPEG size; exact byte conversion requires tracing", "legacy KB"),
    "RequiredDigitalFileSizeMax": ("Maximum digital JPEG size; exact byte conversion requires tracing", "legacy KB"),
    "bDoICAOcheck": ("Run automatic quality checking for this document", "boolean"),
    "bDoAutoCrop": ("Run automatic crop for this document", "boolean"),
    "bGlassesForbidden": ("Document policy forbids glasses; independent of detecting glare", "boolean"),
    "bForceCutmarks": ("Document requests cut marks on its print sheet", "boolean"),
    "bBlockBGtool": ("Disable background editing for this document", "boolean"),
    "iEyesHeight": ("Target eye-line position measured from the photo top", "% of photo height"),
    "iEyesHeightMin": ("Minimum eye-line position from the photo top", "% of photo height"),
    "iEyesHeightMax": ("Maximum eye-line position from the photo top", "% of photo height"),
    "iFaceHeight": ("Target head/face height; landmark/crown definition needs engine tracing", "% of photo height"),
    "iFaceHeightMin": ("Minimum head/face height", "% of photo height"),
    "iFaceHeightMax": ("Maximum head/face height", "% of photo height"),
    "iFaceWidth": ("Target face width", "% of photo width"),
    "iFaceWidthMin": ("Minimum face width", "% of photo width"),
    "iFaceWidthMax": ("Maximum face width", "% of photo width"),
    "bUseFaceWidth": ("Enable width-based geometry; do not discard when height is also enabled", "boolean"),
    "bUseFaceHeight": ("Enable height-based geometry", "boolean"),
    "bUseZoomFactor": ("Use the legacy zoom-factor framing mode", "boolean"),
    "iZoomFactor": ("Legacy zoom factor; not a universal physical measurement", "legacy factor"),
    "iFreeFrameWidth": ("Free-frame parameter; physical interpretation not yet traced", "legacy parameter"),
    "iFreeFrameHeight": ("Free-frame parameter; physical interpretation not yet traced", "legacy parameter"),
}
for channel in "RGB":
    FIELDS["Back" + channel] = ("Preferred background " + channel + " channel", "0–255 channel value")
    FIELDS["Back" + channel + "min"] = ("Minimum background " + channel + " channel", "0–255 channel value")
    FIELDS["Back" + channel + "max"] = ("Maximum background " + channel + " channel", "0–255 channel value")

DEFAULT_FLAGS = {"bDoAutoCrop": True, "bDoICAOcheck": True, "bUseISOtemplate": False,
                 "bSpecialMode": False, "bGlassesForbidden": False,
                 "bForceCutmarks": False, "bBlockBGtool": False}
# Verified in the supplied ControlFrame constructor. Boolean fields not assigned
# there have the CLR's zero/false default. Width/height modes are explicit in XML.

QUALITY_LABELS = {
    "InputSize": "Input pixel dimensions", "Face": "Face detection", "Eyes": "Eye detection",
    "Confidence": "Measurement confidence", "GenQuality": "General image quality",
    "EyeAngle": "Eye-line tilt", "EyeDistance": "Distance between eyes", "Pose": "Face pose",
    "FaceFree": "Face unobstructed", "Suitable": "Biometric suitability",
    "EyesClear": "Eye detail visible", "EyesOpen": "Eyes open", "SunGlases": "Sunglasses/dark eye area",
    "Glare": "Glasses glare", "Expression": "Neutral expression", "Hat": "Headwear",
    "MouthClosed": "Mouth closed", "Smiling": "Smiling", "Glasses": "Glasses detection",
    "RedEyes": "Red eye", "Age": "Age estimate", "Gender": "Gender estimate",
    "Realface": "Real-face check", "MultipleFaces": "Multiple faces",
    "FaceNotFacingCamera": "Face orientation", "EyesNotFacingCamera": "Gaze direction",
    "Overexposed": "Overexposure", "Underexposed": "Underexposure",
    "SkinColor": "Skin colour", "Hotspots": "Bright hotspots", "Uniform": "Uniform lighting",
    "ShadowInEyes": "Eye shadows", "ShadowInFace": "Face shadows",
    "FaceLarge": "Face too large", "FaceSmall": "Face too small",
    "FacePositionLeft": "Face too far left", "FacePositionRight": "Face too far right",
    "FacePositionHigh": "Face too high", "FacePositionLow": "Face too low",
    "Sharpness": "Sharpness", "Motionblur": "Motion blur", "Contrast": "Contrast",
    "Artefacts": "Image artefacts", "Noise": "Image noise", "Interlaced": "Interlacing",
    "Compressed": "Compression quality", "BackUniform": "Background uniformity",
    "BackBright": "Background brightness", "BackShadows": "Background shadows",
    "BackColor": "Background colour",
}


def quality_definition(name):
    if name.startswith("Check"):
        return {"meaning": "Enable " + QUALITY_LABELS.get(name[5:], name[5:]).lower(), "unit": "boolean"}
    if name in ("MinInputWidth", "MinInputHeight", "MineyeDistance"):
        return {"meaning": "Minimum " + {"MinInputWidth": "input width", "MinInputHeight": "input height", "MineyeDistance": "inter-eye distance"}[name], "unit": "pixels"}
    if name == "MaxAngle":
        return {"meaning": "Maximum absolute eye-line tilt", "unit": "degrees"}
    if name.startswith("RefBackColor"):
        return {"meaning": "Global reference background colour channel; country also has its own bounds", "unit": "0–255 channel value"}
    return {"meaning": "Legacy acceptance threshold for " + name,
            "unit": "legacy engine score", "note": "Score calculation is not defined by this XML; not interchangeable with an OpenCV/AI confidence value"}


def basename(text):
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def decode(source):
    settings = xml(source / "Config/Photomatic7.xml")
    quality_files = {p.name.casefold(): p for p in (source / "Packages/ICAO").iterdir() if p.suffix.lower() == ".xml"}
    selected_quality = value(settings, "SelectedICAOfile") or value(settings, "DefaultICAOfile")
    if not selected_quality.lower().endswith(".xml"):
        selected_quality += ".XML"
    quality = {p.name: {e.tag: (e.text or "").strip() for e in xml(p)} for p in sorted(quality_files.values())}
    inspection_path = Path(__file__).resolve().parent.parent / "docs/standards/engine-inspection.json"
    defaults = {}
    if not inspection_path.exists():
        raise ValueError("Run inspect_reference_engine.py first to verify constructor defaults for this installation")
    inspection = json.loads(inspection_path.read_text())
    assembly = next(a for a in inspection["assemblies"] if a["file"] == "Bin/Photomatic.DLL")
    if hashlib.sha256((source / assembly["file"]).read_bytes()).hexdigest() != assembly["sha256"]:
        raise ValueError("Reference binary changed; regenerate engine inspection before decoding defaults")
    defaults = next(m["numeric_constructor_defaults"] for m in assembly["methods"]
                    if m["type"] == "Photomatic.ISOlevels" and "numeric_constructor_defaults" in m)
    records = []
    unknown = set()
    seen = set()
    for p in sorted((source / "Packages/Countries").iterdir(), key=lambda p: p.name.casefold()):
        if p.suffix.lower() != ".xml":
            continue
        t = xml(p)
        fields = {}
        for e in t.iter():
            if len(e):
                continue
            if e.tag not in FIELDS:
                unknown.add(e.tag)
                continue
            seen.add(e.tag)
            text = (e.text or "").strip()
            fields[("view/" if e.tag in {x.tag for x in t.find("view")} else "") + e.tag] = basename(text) if FIELDS[e.tag][1] == "filename" else text
        qname = basename(value(t, "ISOtemplatename", "")) if flag(t, "bUseISOtemplate") else selected_quality
        qpath = quality_files.get(qname.casefold())
        h, w = number(t, "iCanvasHeight"), number(t, "iCanvasWidth")
        records.append({
            "id": key(p.stem), "name": p.stem,
            "source": {"file": p.relative_to(source).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
            "fields": fields,
            "effective_flags": {k: {"value": flag(t, k, default),
                                    "origin": "XML" if t.find('.//' + k) is not None else "ControlFrame constructor default"}
                                for k, default in DEFAULT_FLAGS.items()},
            "quality_profile": qpath.name if qpath else None,
            "quality_reference_resolves": bool(qpath),
            "derived_mm": {"head_target": h * number(t, "iFaceHeight") / 100,
                           "head_range": [h * number(t, k) / 100 for k in ("iFaceHeightMin", "iFaceHeightMax")],
                           "eye_from_top_target": h * number(t, "iEyesHeight") / 100,
                           "eye_from_top_range": [h * number(t, k) / 100 for k in ("iEyesHeightMin", "iEyesHeightMax")],
                           "face_width_target": w * number(t, "iFaceWidth") / 100,
                           "face_width_range": [w * number(t, k) / 100 for k in ("iFaceWidthMin", "iFaceWidthMax")]},
        })
    if unknown:
        raise ValueError("Undocumented country fields; values not exported: " + ", ".join(sorted(unknown)))
    return {"scope": "Stored reference configuration and documented field meanings, not verified current government standards",
            "country_fields": {k: {"meaning": FIELDS[k][0], "unit": FIELDS[k][1]} for k in sorted(seen)},
            "quality_fields": {k: quality_definition(k) for k in sorted({k for v in quality.values() for k in v})},
            "quality_profiles": quality, "quality_constructor_defaults": defaults,
            "effective_quality_profiles": {name: {k: {"value": raw.get(k, str(default).lower() if isinstance(default, bool) else str(default)),
                                                        "origin": "XML" if k in raw else "ISOlevels constructor default"}
                                                  for k, default in defaults.items()} for name, raw in quality.items()},
            "countries": records}


def guide(data):
    lines = ["# Stored photo standards field guide", "",
             "Generated from the supplied reference installation. Read [the decoding notes](../STANDARDS_DECODING.md) for verified application logic and unresolved engine behaviour.", "",
             "## Country fields", "", "| XML field | Meaning | Unit |", "|---|---|---|"]
    for k, v in data["country_fields"].items():
        lines.append(f"| `{k}` | {v['meaning']} | {v['unit']} |")
    lines += ["", "## Quality settings one by one", "",
              "A switch enables a check. A numeric score threshold does not define the algorithm that produces that score.", "",
              "| XML field | Default | NOlevels | Meaning | Unit |", "|---|---|---|---|---|"]
    for k, v in data["quality_fields"].items():
        lines.append(f"| `{k}` | {data['quality_profiles']['DefaultISOlevels.XML'].get(k, 'absent')} | {data['quality_profiles']['NOlevels.XML'].get(k, 'absent')} | {v['meaning']} | {v['unit']} |")
    lines += ["", "Absence in XML does not necessarily disable a check. Constructor defaults and effective values are recorded in profiles.json. For example, CheckInputFormat is absent from all three XML profiles but defaults true in this library."]
    lines += ["", "## All country and document profiles", "",
              "Complete individual fields and default origins are in [profiles.json](profiles.json). The table shows stored values, including inactive geometry ranges.", "",
              "| Profile | Photo mm | Head range % | Eyes from top % | Geometry enabled | Quality profile |", "|---|---|---|---|---|---|"]
    for c in data["countries"]:
        f = c["fields"]
        enabled = ", ".join(name for field, name in [("view/bUseFaceHeight", "height"), ("view/bUseFaceWidth", "width"), ("view/bUseZoomFactor", "zoom")] if f.get(field) == "true") or "free-style"
        lines.append(f"| {c['name']} | {f['iCanvasWidth']} × {f['iCanvasHeight']} | {f['view/iFaceHeightMin']}–{f['view/iFaceHeightMax']} | {f['view/iEyesHeightMin']}–{f['view/iEyesHeightMax']} | {enabled} | {c['quality_profile'] or 'unresolved'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "docs/standards")
    args = parser.parse_args()
    result = decode(args.source)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "profiles.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    (args.output / "FIELD_GUIDE.md").write_text(guide(result))
    print(f"Decoded {len(result['countries'])} profiles, {len(result['country_fields'])} country fields, {len(result['quality_fields'])} quality fields")
