"""Read reference backup jobs, printer data and installer archives safely.

Exports metadata and allowlisted job instructions, never photo bytes, codes,
customer/order names, installer credentials or printer maintenance commands.
Requires Pillow; installer archives are listed/read with macOS bsdtar.
"""
import argparse
import configparser
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageCms


JOB_KEYS = {"OutDevice": ("DeviceName",), "ImageList": ("ImageCnt", "1"),
            "IDStation.jpg": ("SizeName", "PrintCnt", "BackPrint", "Resize", "DSC_Chk")}


def tree(raw):
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return ET.fromstring(raw.decode(enc))
        except (UnicodeError, ET.ParseError):
            pass
    raise ValueError("Unreadable archive XML")


def audit(backup, printer, installer):
    jobs = []
    for image in sorted(backup.rglob("IDStation.jpg")):
        with Image.open(image) as im:
            jpeg = {"pixels": list(im.size), "dpi_tag": list(im.info.get("dpi", ())),
                    "embedded_icc": bool(im.info.get("icc_profile")), "bytes": image.stat().st_size,
                    "quantization_tables": im.quantization}
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read(image.parent / "condition.txt", encoding="utf-8-sig")
        instructions = {section: {key: parser.get(section, key) for key in keys if parser.has_option(section, key)}
                        for section, keys in JOB_KEYS.items()}
        jobs.append({"sample_index": len(jobs) + 1, "jpeg": jpeg, "instructions": instructions,
                     "ready_marker": (image.parent / "end.txt").exists(),
                     "done_marker": (image.parent / "Done.txt").exists()})
    profiles = []
    for p in sorted(printer.rglob("*.icc")):
        raw = p.read_bytes()
        record = {"file": p.relative_to(printer).as_posix(), "bytes": len(raw),
                  "sha256": hashlib.sha256(raw).hexdigest()}
        try:
            ic = ImageCms.getOpenProfile(str(p))
            record.update(readable=True, device_class=ic.profile.device_class.strip(),
                          input_space=ic.profile.xcolor_space.strip(),
                          output_space=ic.profile.connection_space.strip(),
                          description=ImageCms.getProfileDescription(ic).strip())
        except Exception:
            record["readable"] = False
        profiles.append(record)
    archives = []
    for name in ("Photomatic7_Frontier.7z", "Photomatic7_ASK.7z"):
        p = installer / "Installers" / name
        members = subprocess.check_output(["bsdtar", "-tf", str(p)], text=True).splitlines()
        settings = tree(subprocess.check_output(["bsdtar", "-xOf", str(p), "Config/Photomatic7.xml"]))
        archives.append({"file": name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                         "entries": len(members),
                         "country_templates": sum(x.startswith("Templates/Countries/") and x.lower().endswith(".xml") for x in members),
                         "print_templates": sum(x.startswith("Templates/Printer/") and x.lower().endswith(".xml") for x in members),
                         "settings": {k: settings.findtext(k) for k in ("DefaultCountry", "DefaultPrinter", "SelectedPrinter", "DefaultICAOfile", "bCloudPrinting")}})
    all_files = [p for p in printer.rglob("*") if p.is_file()]
    return {"scope": "Reference metadata; no print job sent and no installer or maintenance command executed",
            "backup": {"job_count": len(jobs), "jobs": jobs},
            "printer_data": {"file_count": len(all_files), "extensions": dict(Counter(p.suffix.lower() for p in all_files)),
                             "icc_profiles": profiles}, "installer_archives": archives}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--printer", type=Path, required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "docs/standards/print-reference.json")
    args = parser.parse_args()
    result = audit(args.backup, args.printer, args.installer)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Audited", result["backup"]["job_count"], "print jobs and", len(result["printer_data"]["icc_profiles"]), "colour-profile files")
