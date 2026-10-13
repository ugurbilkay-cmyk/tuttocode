"""Honest operator measurements: native values and explicitly untested fields."""
def report(values, checks, profile):
    values = dict(values)
    final_highlights = values.get('final_highlights',{})
    if final_highlights.get('status')=='diagnostic':
        values.setdefault('regional_near_clip',final_highlights['near_clip_all_percent'])
        values.setdefault('regional_bright_patches',final_highlights['patch_count'])
    by_key = {c["key"]: c["status"] for c in checks}

    def row(label, key=None, unit="", check=None, limits="", status=None):
        value = values.get(key) if key else None
        if isinstance(value, list):
            value = " × ".join(f"{v:g}" for v in value)
        elif isinstance(value, (int, float)):
            value = f"{value:g}"
        return {"label": label, "value": value if value is not None else "Not tested",
                "unit": unit if value is not None else "", "limits": limits,
                "status": "unknown" if value is None else status or by_key.get(check, "unknown")}

    geometry = [
        row("Position Eye 1", "eye1", "px", status="measured"),
        row("Position Eye 2", "eye2", "px", status="measured"),
        row("Horizontal eye angle", "eye_angle", "°", "tilt", f"±{values.get('max_eye_angle', 6):g}°"),
        row("Inter-eye distance · source", "source_eye_distance", "px", "eyedistance", f"≥{values.get('min_source_eye_distance', 90):g} px"),
        row("Inter-eye distance · output", "output_eye_distance", "px", status="measured"),
        row("Pose · nose offset / face width", "yaw_ratio", "ratio", "facing", "≤0.12; warning above 0.07"),
        row("Face biometrics detectable"), row("Eye details detectable"), row("Biometrical details in image"),
        row("Eyes open · blink model output", "blink", "0–1", "eyes", "Not a Photomatic score"),
        row("Sunglasses / darkness around eyes"),
        row("Glare from glasses · candidate bright area", "glare_area", "%", "glare", "≤4%; warning above 1.5%"),
        row("Neutral expression score"),
        row("Mouth closed · jaw model output", "jaw_open", "0–1", "expression", "Not a Photomatic score"),
        row("Smiling · smile model output", "smile", "0–1", "expression", "Not a Photomatic score"),
    ]
    # Anatomical measurements have defined profile ranges, separate from quality scores.
    for label, key, bounds, enabled, check in (
        ("Head height", "head_percent", profile["head"], profile["use_head"], "headsize"),
        ("Eye level from top", "eye_height_percent", profile["eyes"], True, "eyeposition"),
        ("Face width", "face_width_percent", profile["face_width"], profile["use_width"], "facewidth"),
    ):
        measured = values.get(key)
        status = "measured" if not enabled else (
            "pass" if measured is not None and bounds[1] <= measured <= bounds[2] else "fail")
        geometry.append(row(label, key, "%", check,
                            f"{bounds[1]:g}–{bounds[2]:g}%" if enabled else "Not enforced by this template", status))
    return [
        {"name": "Image measurements", "rows": [
            row("Input image size · after EXIF orientation", "input_size", "px", status="measured"),
            row("ID photo source crop", "source_crop_size", "px", "resolution"),
            row("ID photo output", "output_size", "px", status="measured"),
            row("Quality sampling grid · before enlargement", "quality_sampling_size", "px", status="measured"),
            row("Digital export dimensions", "digital_size", "px", status="measured"),
            row("Checked JPEG file size", "digital_kib", "KiB", status="measured"),
            row("Measurement confidence"), row("General image quality"),
        ]},
        {"name": "Biometric measurements", "rows": geometry},
        {"name": "Image quality measurements", "rows": [
            row("Sharpness · Laplacian variance", "sharpness", "variance", "sharp", "≥25; warning below 50"),
            row("Unadjusted crop sharpness", "unadjusted_sharpness", "variance", limits="Before local enhancement · 300 px face reference", status="measured"),
            row("Motion blur"), row("Contrast · face lightness deviation", "contrast", "L*", status="measured"),
            row("Artefacts"), row("Noise"), row("Compression"),
        ]},
        {"name": "Lighting measurements", "rows": [
            row("Exposure · mean face lightness", "face_lightness", "L*", "exposure", "30–88 L*"),
            row("Under exposed score"), row("Over exposed score"), row("Natural skin colour"), row("Hotspots"),
            row("Final JPEG · regional near-clipping in all channels", "regional_near_clip", "%", status="measured", limits="Native-pixel diagnostic; not a Photomatic score"),
            row("Final JPEG · regional bright candidate patches", "regional_bright_patches", "patches", status="measured"),
            row("Uniform lighting / face shadow", "lighting_imbalance", "%", "shadow", "≤30%; warning above 18%"),
            row("Shadow in eyes"),
            row("Background median colour", "background_rgb", "RGB", "background"),
            row("Background lightness deviation", "background_variation", "L*", "background", "≤12; warning above 7"),
        ]},
        {"name": "Staff visual checks", "rows": [row(label) for label in (
            "Red eye", "Glasses", "Head covering", "Face likeness after AI edits", "Age estimate", "Gender") ]},
    ]
