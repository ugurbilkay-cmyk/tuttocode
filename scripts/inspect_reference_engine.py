"""Read selected .NET method metadata and IL without running the reference app.

Optional inspection dependencies: dnfile and dncil. They are not app dependencies.
String literals are always redacted. This does not inspect licensing/credentials.
"""
import argparse
import hashlib
import json
from pathlib import Path

import dnfile
from dncil.cil.body.reader import read_method_body_from_bytes
from dncil.clr.token import StringToken, Token


SELECTION = {
    "Bin/Photomatic.DLL": {
        "Photomatic.ControlFrame": {".ctor"},
        "Photomatic.ISOlevels": {".ctor"},
        "Photomatic.Photo": {"CheckICAOlevelsNoGeometry", "CheckICAOlevelsGeometry",
                             "GeometryCheck7", "GeometryCheckExtra7", "BackgroundCheck7",
                             "ImageQualityCheck7", "CalculateViewAuto", "AutoCrop7",
                             "AutoCrop7N", "CheckBackground"},
    },
    "Bin/PhotoMatic7.exe": {
        "PhotoMatic7.Form1": {"StartIsoCheck", "StartGeoCheck", "StartBackgroundCheck",
                             "CheckICAOlevelsGeometry", "RunICAOtask", "RunGEOtask",
                             "GetjustICAO", "ServerICAOtestAsync"},
    },
}


def inspect(source, full_il=False):
    result = {"scope": "Static inspection of selected methods only; no reference executable was run; all string literals omitted",
              "assemblies": []}
    for relative, selection in SELECTION.items():
        path = source / relative
        pe = dnfile.dnPE(str(path))
        owners = {m.row_index: str(t.TypeName) for t in pe.net.mdtables.TypeDef.rows for m in t.MethodList}
        fields = {f.row_index: str(t.TypeName) for t in pe.net.mdtables.TypeDef.rows for f in t.FieldList}

        def resolve(operand):
            if isinstance(operand, StringToken):
                return "[string literal omitted]"
            if isinstance(operand, Token):
                row = pe.net.mdtables.tables[operand.table].rows[operand.rid - 1]
                if operand.table == 6:
                    return owners[operand.rid] + "." + str(row.Name)
                if operand.table == 4:
                    return fields[operand.rid] + "." + str(row.Name)
                parent = getattr(row, "Class", None)
                type_name = str(getattr(parent.row if parent else row, "TypeName", ""))
                return type_name + "." + str(getattr(row, "Name", ""))
            if operand is None or isinstance(operand, (int, float, list)):
                return operand
            return str(operand)

        record = {"file": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "references": [str(r.Name) for r in pe.net.mdtables.AssemblyRef.rows], "methods": []}
        for t in pe.net.mdtables.TypeDef.rows:
            type_name = str(t.TypeNamespace) + "." + str(t.TypeName)
            if type_name not in selection:
                continue
            for m in t.MethodList:
                name = str(m.row.Name)
                if name not in selection[type_name] or not m.row.Rva:
                    continue
                body = read_method_body_from_bytes(pe.get_data(m.row.Rva))
                instructions = [{"offset": hex(i.offset), "opcode": i.opcode.name,
                                 "operand": resolve(i.operand)} for i in body.instructions]
                # No string values, licensing internals or credentials are exposed.
                instructions = [i for i in instructions if not isinstance(i["operand"], str) or "license" not in i["operand"].lower()]
                method = {"type": type_name, "name": name,
                    "token": hex(0x06000000 | m.row_index), "instruction_count": len(body.instructions),
                    "calls": sorted({i["operand"] for i in instructions if i["opcode"] in ("call", "callvirt", "newobj")}),
                    "fields_referenced": sorted({i["operand"] for i in instructions if i["opcode"] in ("ldfld", "stfld", "ldsfld", "stsfld")})}
                if full_il or name in (".ctor", "CheckICAOlevelsNoGeometry", "CheckICAOlevelsGeometry", "CheckBackground"):
                    method["instructions"] = instructions
                if type_name == "Photomatic.ISOlevels" and name == ".ctor":
                    defaults = {str(f.row.Name): False for f in t.FieldList if str(f.row.Name).startswith("Check")}
                    for index, instruction in enumerate(instructions):
                        if instruction["opcode"] != "stfld" or not index:
                            continue
                        previous = instructions[index - 1]
                        opcode = previous["opcode"]
                        if opcode.startswith("ldc.i4.") and opcode != "ldc.i4.s":
                            suffix = opcode.rsplit(".", 1)[-1]
                            constant = -1 if suffix == "m1" else int(suffix)
                        elif opcode in ("ldc.i4", "ldc.i4.s", "ldc.r4", "ldc.r8"):
                            constant = previous["operand"]
                        else:
                            continue
                        field = instruction["operand"].split(".", 1)[-1]
                        defaults[field] = bool(constant) if field.startswith("Check") else constant
                    method["numeric_constructor_defaults"] = defaults
                record["methods"].append(method)
        result["assemblies"].append(record)
        pe.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "docs/standards/engine-inspection.json")
    parser.add_argument("--full-il", action="store_true", help="Include all selected method instructions, still redacting string literals")
    args = parser.parse_args()
    data = inspect(args.source, full_il=args.full_il)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print("Inspected", sum(len(a["methods"]) for a in data["assemblies"]), "methods in", len(data["assemblies"]), "assemblies")
