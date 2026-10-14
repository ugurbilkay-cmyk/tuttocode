"""Import only photo templates and artwork from a Photomatic installation.

Usage: python3 scripts/import_photomatic.py /path/to/Photomatic7
No credentials, issued codes, executables or device paths are exported.
"""
import argparse
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def xml(path):
    raw = path.read_bytes()
    # Several shipped files declare UTF-16 but contain UTF-8/Windows text.
    encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp1252")
    for encoding in encodings:
        try:
            return ET.fromstring(raw.decode(encoding))
        except (UnicodeError, ET.ParseError):
            pass
    raise ValueError(f"Unreadable template: {path.name}")


def value(tree, key, default=None):
    text = tree.findtext(".//" + key)
    return default if text is None or not text.strip() else text.strip()


def number(tree, key, default=0):
    return float(value(tree, key, default))


def flag(tree, key, default=False):
    return str(value(tree, key, default)).lower() == "true"


def key(name):
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def import_catalog(source, destination):
    assets = destination / "static" / "photomatic"
    warnings = []
    files = []

    def artwork(folder, name, category):
        basename = name.replace("\\", "/").split("/")[-1]
        candidates = {p.name.casefold(): p for p in folder.iterdir() if p.is_file()}
        p = candidates.get(basename.casefold())
        if not p:
            # A few old templates still name .bmp after the artwork was
            # replaced with a .png of the same name in this installation.
            stem = Path(basename).stem.casefold()
            p = next((f for f in candidates.values() if f.stem.casefold() == stem), None)
        if not p:
            return None
        out = assets / category / p.name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, out)
        return "/static/photomatic/" + category + "/" + p.name

    def provenance(p):
        files.append({"file": p.relative_to(source).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})

    settings = xml(source / "Config/Photomatic7.xml")
    countries = []
    for p in sorted((source / "Packages/Countries").iterdir(), key=lambda p: p.name.casefold()):
        if p.suffix.lower() != ".xml":
            continue
        t = xml(p)
        c = {
            "id": key(p.stem), "name": p.stem, "country": value(t, "LandName", p.stem),
            "format": value(t, "strFormat"),
            "width_mm": number(t, "iCanvasWidth"), "height_mm": number(t, "iCanvasHeight"),
            "eyes": [number(t, "iEyesHeight"), number(t, "iEyesHeightMin"), number(t, "iEyesHeightMax")],
            "head": [number(t, "iFaceHeight"), number(t, "iFaceHeightMin"), number(t, "iFaceHeightMax")],
            "face_width": [number(t, "iFaceWidth"), number(t, "iFaceWidthMin"), number(t, "iFaceWidthMax")],
            "use_head": flag(t, "bUseFaceHeight"), "use_width": flag(t, "bUseFaceWidth"),
            "auto_crop": flag(t, "bDoAutoCrop", True), "check_icao": flag(t, "bDoICAOcheck", True),
            "glasses_forbidden": flag(t, "bGlassesForbidden"),
            "background": [int(number(t, "Back" + ch)) for ch in "RGB"],
            "background_min": [int(number(t, "Back" + ch + "min")) for ch in "RGB"],
            "background_max": [int(number(t, "Back" + ch + "max", 255)) for ch in "RGB"],
            "digital_size": [int(number(t, "RequiredDigitalWidth", -1)), int(number(t, "RequiredDigitalHeight", -1))],
            "digital_kb": [number(t, "RequiredDigitalFileSizeMin", -1), number(t, "RequiredDigitalFileSizeMax", -1)],
            "default_print_name": value(t, "DefaultPrintTemplateName", ""),
            "default_save_name": value(t, "SaveTemplateName", "DefaultSaveTemplate.xml"),
            "default_email_name": value(t, "EmailTemplateName", "DefaultEmailTemplate.XML"),
            "special_mode": flag(t, "bSpecialMode"), "special_label": value(t, "RadioBtnlabel", "Next"),
            "use_overlay": flag(t, "bUseOverlay"),
            "flag": artwork(source / "Packages/Countries/Flags", value(t, "FlagFileName", ""), "flags"),
            "overlay": artwork(source / "Packages/Countries/Overlays", value(t, "OverlayFileName", ""), "overlays") if flag(t, "bUseOverlay") else None,
        }
        if not c["width_mm"] or not c["height_mm"]:
            raise ValueError(f"Invalid dimensions: {p.name}")
        countries.append(c)
        provenance(p)

    prints = []
    folders = [(p.name, p) for p in sorted((source / "Packages/Printer/printers").iterdir()) if p.is_dir()]
    folders.append(("Installed templates", source / "Packages/Printer"))
    for printer, folder in folders:
        for p in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            if p.suffix.lower() != ".xml":
                continue
            t = xml(p)
            boxes = [{"x_mm": number(b, "TopLeftX"), "y_mm": number(b, "TopLeftY"),
                      "width_mm": number(b, "Width"), "height_mm": number(b, "Height"),
                      "landscape": flag(b, "bLandscape"), "format": value(b, "format")}
                     for b in t.findall("Boxes") if not flag(b, "bDeleted")]
            # Saved templates can retain undeleted slots after their configured
            # count (e.g. a 4-up with six records). Do not render stale extras.
            configured_count = int(number(t, "nrBoxes", len(boxes)))
            if configured_count > 0:
                boxes = boxes[:configured_count]
            prints.append({
                "id": key(printer) + "/" + key(p.stem), "name": p.stem, "filename": p.name,
                "printer": printer, "width_px": int(number(t, "PrinterWidthPixels")),
                "height_px": int(number(t, "PrinterHeightPixels")), "dpi": int(number(t, "PrinterResolution")),
                "format": value(t, "ComplianceFormat"), "boxes": boxes,
                "cut_marks": flag(t, "bCutMarks"), "cut_mark_size": number(t, "CutMarkSize", 60),
                "photo_number": flag(t, "bPrintPhotoNumber"),
                "number_position_mm": [number(t, "PhotoNumberTopLeftX"), number(t, "PhotoNumberTopLeftY")],
                "background": artwork(source / "Packages/Printer/Images", value(t, "Templatename", ""), "print") if flag(t, "bPrintBackgroundImage") else None,
                "force_country": value(t, "ForceTemplateName", ""), "generated": False,
            })
            provenance(p)

    # Some countries refer to files missing from the supplied installation.
    # Preserve their real dimensions with an explicitly labelled generated layout.
    for c in countries:
        if any(p["filename"].casefold() == c["default_print_name"].casefold() for p in prints):
            continue
        w, h, dpi = c["width_mm"], c["height_mm"], 301
        sheet_w, sheet_h = 1844 * 25.4 / dpi, 1240 * 25.4 / dpi
        cols, rows = max(1, int((sheet_w - 8) // (w + 3))), max(1, int((sheet_h - 8) // (h + 3)))
        # Oversized freestyle frames are printed in the intended print format.
        dims = re.search(r"(\d+)x(\d+)", c["default_print_name"], re.I)
        if dims:
            w, h = map(float, dims.groups())
            cols, rows = max(1, int((sheet_w - 8) // (w + 3))), max(1, int((sheet_h - 8) // (h + 3)))
        count = re.search(r"(\d+)-?up", c["default_print_name"], re.I)
        count = min(cols * rows, int(count.group(1))) if count else cols * rows
        boxes = [{"x_mm": 4 + (i % cols) * (w + 3), "y_mm": 4 + (i // cols) * (h + 3),
                  "width_mm": w, "height_mm": h, "landscape": False, "format": c["format"]} for i in range(count)]
        prints.append({"id": "generated/" + c["id"], "name": c["default_print_name"].removesuffix(".XML") + " (generated)",
                       "filename": c["default_print_name"], "printer": "Generated layouts", "width_px": 1844, "height_px": 1240,
                       "dpi": dpi, "format": c["format"], "boxes": boxes, "cut_marks": True,
                       "cut_mark_size": 60, "photo_number": False, "number_position_mm": [0, 0],
                       "background": None, "force_country": "", "generated": True})
        warnings.append(c["name"] + ": default print file is missing; generated a layout from its dimensions")

    saves = {}
    for p in (source / "Packages/Save").iterdir():
        if p.suffix.lower() == ".xml":
            t = xml(p)
            saves[p.name.casefold()] = {"width": int(number(t, "Imagewidth")), "height": int(number(t, "Imageheight")), "format": value(t, "Format")}
    for c in countries:
        c["save"] = saves.get(c["default_save_name"].casefold(), saves["defaultsavetemplate.xml"])
        # Only these templates represent the existing UK passport-code workflow.
        c["hmpo_code"] = c["id"] in {"united-kingdom-passport", "united-kingdom-online-renewal", "uk-online"}
        c["code_service"] = "uk" if c["hmpo_code"] else (
            "ie" if c["id"] in {"ireland-passport", "ireland-passport-online"} else None)
    emails = {}
    for p in (source / "Packages/Email").iterdir():
        if p.suffix.lower() == ".xml":
            t = xml(p)
            emails[p.name.casefold()] = {"width": int(number(t, "Imagewidth")), "height": int(number(t, "Imageheight")), "format": value(t, "Format")}
    for c in countries:
        c["email"] = emails.get(c["default_email_name"].casefold(), emails["defaultemailtemplate.xml"])
    for name in ["backgroundv7.png"]:
        artwork(source / "Images/common", name, "ui")
    catalog = {"version": 1, "default_country": key(value(settings, "DefaultCountry", "United Kingdom Passport")),
               "default_printer": value(settings, "DefaultPrinter", "Print2Hotfolder"),
               "countries": countries, "prints": prints, "warnings": warnings,
               "quality": {e.tag: (e.text or "").strip() for e in xml(source / "Packages/ICAO/DefaultISOlevels.XML")},
               "sources": files}
    out = destination / "app/photomatic_catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(f"Imported {len(countries)} country/document templates, {len(prints)} print layouts")
    print(f"{len(warnings)} missing print references have labelled generated layouts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    import_catalog(args.source, args.destination)
