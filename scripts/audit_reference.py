"""Inventory the supplied reference installation without exporting credentials.

This is a read-only audit, not a runtime dependency or another template import.
Only allowlisted settings, template metadata, filenames and hashes are emitted.
Usage: python scripts/audit_reference.py /path/to/Photomatic7 --output audit.json
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from import_photomatic import flag, value, xml


SAFE_SETTINGS = (
    "DefaultCountry", "SelectedCountry", "DefaultPrinter", "SelectedPrinter",
    "DefaultICAOfile", "SelectedICAOfile", "bAutoCrop", "bMakeEyesHorizontal",
    "bDoBackgroundTest", "bDoGeoTest", "bAutoBackground", "p_bAutoedit",
    "o_bAutoedit", "s_bAutoedit", "bPPblockatSave", "bPPBlockatPrint",
    "bBlockonICAO", "bBlockonGEO", "bBlockonBACK", "bAutoArchive",
    "bSaveafterPrint", "bAlwaysPrintICAO", "bDefaultOversizedPrinting",
)


def xml_files(folder):
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() == ".xml")


def audit(source):
    countries = [(p, xml(p)) for p in xml_files(source / "Packages/Countries")]
    prints = [(p, xml(p)) for p in xml_files(source / "Packages/Printer")]
    saves = xml_files(source / "Packages/Save")
    emails = xml_files(source / "Packages/Email")
    quality = xml_files(source / "Packages/ICAO")
    settings_path = source / "Config/Photomatic7.xml"
    settings = xml(settings_path)
    language_path = source / "Images/en/languagedata.XML"
    manuals = sorted((source / "Images/en").glob("*.pdf"))
    manuals += [source / "Images/nl/Handleiding 7.3.pdf"]
    screenshots = sorted(source.glob("Screenshot 2026-10-12 at 18.*.png"))
    sources = [settings_path, language_path] + [p for p, _ in countries + prints]
    sources += saves + emails + quality + manuals + screenshots

    exceptions = {}
    for field in ("bUseISOtemplate", "bBlockBGtool", "bUseZoomFactor", "bForceCutmarks", "bSpecialMode"):
        exceptions[field] = [p.stem for p, t in countries if flag(t, field)]
    print_families = Counter(
        p.parent.name if p.parent.parent.name == "printers" else "Installed templates"
        for p, _ in prints
    )
    required_exports = [
        {"profile": p.stem, "width": int(value(t, "RequiredDigitalWidth")),
         "height": int(value(t, "RequiredDigitalHeight")),
         "minimum_kb": value(t, "RequiredDigitalFileSizeMin"),
         "maximum_kb": value(t, "RequiredDigitalFileSizeMax")}
        for p, t in countries if int(value(t, "RequiredDigitalWidth", -1)) > 0
    ]
    return {
        "scope": "Reference inventory; presence is not proof of installed device support or functional parity",
        "confirmed_user_workflow": {"input": "File upload", "printer": "FUJIFILM DE100-XD",
                                    "code_countries": ["United Kingdom", "Ireland"]},
        "counts": {"country_document_profiles": len(countries), "print_layouts": len(prints),
                   "save_templates": len(saves), "email_templates": len(emails),
                   "quality_profiles": len(quality), "supplied_screenshots": len(screenshots)},
        "saved_settings": {k: value(settings, k) for k in SAFE_SETTINGS},
        "print_layout_families": dict(sorted(print_families.items())),
        "country_exceptions": exceptions,
        "print_compliance_modes": dict(sorted(Counter(value(t, "ComplianceMode", "absent") for _, t in prints).items())),
        "required_digital_exports": required_exports,
        "quality_profiles": {p.name: {e.tag: (e.text or "").strip() for e in xml(p)} for p in quality},
        "ui_forms": [e.tag for e in xml(language_path)],
        "sources": [{"file": p.relative_to(source).as_posix(),
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result["counts"]))
