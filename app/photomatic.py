"""Photomatic's imported country and printer catalog (no Windows dependency)."""
import json
from pathlib import Path


CATALOG = json.loads((Path(__file__).parent / "photomatic_catalog.json").read_text())
COUNTRIES = {c["id"]: c for c in CATALOG["countries"]}
PRINTS = {p["id"]: p for p in CATALOG["prints"]}
DEFAULT_COUNTRY = CATALOG["default_country"]
DEFAULT_PRINTER = CATALOG["default_printer"]
PRINTERS = sorted({p["printer"] for p in PRINTS.values()})


def country(country_id=None):
    return COUNTRIES[country_id or DEFAULT_COUNTRY]


def print_choices(c, printer=None):
    """Use the selected printer, falling back to the installation's loose templates."""
    printer = printer or DEFAULT_PRINTER
    matches = [p for p in PRINTS.values() if
               p["filename"].casefold() == c["default_print_name"].casefold() or
               (p["printer"] in (printer, "Installed templates", "Generated layouts") and
                (p["format"] == c["format"] or any(b["format"] == c["format"] for b in p["boxes"])))]
    return sorted(matches, key=lambda p: (p["filename"].casefold() != c["default_print_name"].casefold(),
                                         p["printer"] != printer, p["printer"] != "Installed templates", p["name"].casefold()))


def default_print(c, printer=None):
    choices = print_choices(c, printer)
    if not choices:
        raise ValueError(f"No print layout for {c['name']}")
    return choices[0]


def output_size(c):
    # A small visa upload (e.g. 250px wide) must not reduce the print master.
    # The crop/print aspect ratio follows the physical country template.
    return round(c["width_mm"] * 30), round(c["height_mm"] * 30)


def save_size(c, email=False):
    if all(v > 0 for v in c["digital_size"]):
        return tuple(c["digital_size"])
    export = c["email"] if email else c["save"]
    width = export["width"]
    if export["format"] == c["format"]:
        return width, export["height"]
    return width, round(width * c["height_mm"] / c["width_mm"])


def summary(checks):
    groups = {"Image quality": [], "Face size and position": [], "Background": []}
    for c in checks:
        group = "Background" if c["key"] in ("background", "bgshadow", "background_tool") else (
            "Face size and position" if c["key"] in ("face", "tilt", "facing", "framing", "resolution", "headsize", "eyeposition", "facewidth", "eyedistance")
            else "Image quality")
        groups[group].append(c)
    return [{"name": name, "status": "fail" if any(c["status"] == "fail" for c in rows) else
             "warn" if not rows or any(c["status"] == "warn" for c in rows) else "pass"}
            for name, rows in groups.items()]
