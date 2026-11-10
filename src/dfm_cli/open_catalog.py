"""Reference catalog of the open run route: IniFieldFile and sediment/morphology files.

This module only reads text. It never writes, stages or launches anything, and
it widens no other profile: `model.inspect_mdu(catalog=True)` is the single
caller. Engine source is DIMRset_2026.02 (Deltares/Delft3D
5a4649830b1e5072caf019fb4850bbdefd9ad431), the same checkout the other readers
cite. A file or key is cataloged only when the line below consumes it;
everything else that names a file stays an `unsupported_reference` issue.

Observed in source (static analysis, not a native run):
* MDU [geometry] IniFieldFile: unstruc_model.f90:848. [sediment] SedFile and
  MorFile: unstruc_model.f90:1513-1514; the sediment module is initialized only
  when both are set and Sedimentmodelnr = 4 (unstruc_model.f90:1516).
* IniFieldFile blocks: unstruc_inifields.f90:248 reads the file, :250-:262 loop
  over blocks. A General block is skipped, any block other than [Initial] and
  [Parameter] is ignored with a warning (readIniFieldProvider). Keys quantity
  (:502), dataFile (:511), dataFileType (:521), dataVariableName (:537). A block
  missing one of the first three is silently ignored by the engine; a silent
  skip of user data is not closure, so the catalog refuses it instead.
  dataFile is resolved by resolvePath(filename, basedir) at :273, where basedir
  is the folder of the INI file and the join applies only if PathsRelativeToParent
  is set (unstruc_files.f90:500). That is exactly the rule model.inspect_mdu
  already uses for every other reference, so the same resolver is reused.
* A format below major version 2 is refused by the engine (:86), which then
  ignores the whole file (:87-:91).
* Accepted dataFileType strings: time_space_parameters.f90:105-127.
* Sediment and morphology, Contract R8: keys that accept either a number or a file name are
  read through prop_get(..., is_float, value, filename) (properties.f90:3189-3235). A value that
  is neither a real number nor a logical word is a file name, joined to the path of the .sed or
  .mor file as MDU wrote it, filename = combinepaths(filsed|filmor, value) (properties.f90:3229;
  combinepaths.f90:51-88: absolute names stay, relative names take the folder of that file).
  The base is therefore the folder of the .sed/.mor file, not the working directory and not
  PathsRelativeToParent; it equals the MDU folder when the file sits there. The key sites and
  the lines that open the file are in FILE_NAME_SOURCES below. IniFluffMass sits in the .sed
  file but rdmor.f90:2197 resolves it against filmor (its own TODO says so): the .mor folder.
  A name is enumerated, staged and refused like any other reference (missing, outside folder).
  Library keys load executable code and stay refused: rdsed.f90:789 SettleLib, :921 DLL,
  :922 TranspLib; rdtrafrm.f90:589 and :678 InputFile (user-defined transport routine input).
* Initialization of both files: flow_sedmorinit.f90:117-148,189-220
  (morph_inputs.py header cites the same lines).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .common import DfmError

SOURCES = {
    "ini_field_file": "unstruc_model.f90:848",
    "ini_read": "unstruc_inifields.f90:248",
    "ini_version": "unstruc_inifields.f90:86",
    "ini_quantity": "unstruc_inifields.f90:502",
    "ini_data_file": "unstruc_inifields.f90:511",
    "ini_data_file_type": "unstruc_inifields.f90:521",
    "ini_resolution": "unstruc_inifields.f90:273 with unstruc_files.f90:500",
    "ini_file_types": "time_space_parameters.f90:105-127",
    "sed_file": "unstruc_model.f90:1513",
    "mor_file": "unstruc_model.f90:1514",
    "sediment_enabled": "unstruc_model.f90:1516",
    "sediment_number_or_file": "rdsed.f90:507,544,680,685,866,869",
    "morphology_number_or_file": "rdmor.f90:178,498,2197,2221,2270",
    "morphology_bc_file": "rdmor.f90:725",
    "sediment_libraries": "rdsed.f90:789,921,922; rdtrafrm.f90:589,678",
    "commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
}
TEXT_LIMIT = 8 * 1024 * 1024
INI_TYPES = {"polygon": {".pol", ".pli", ".pliz"}, "sample": {".xyz"}, "arcinfo": {".asc"},
             "geotiff": {".tif", ".tiff"}, "netcdf": {".nc"}}
# Engine-recognised types the catalog cannot enumerate (companion grid, nested INI, spiderweb).
INI_UNENUMERATED = {"1dfield", "bcascii", "curvigrid", "spiderweb", "uniform", "unimagdir"}
# Number-or-file keys: (block the engine reads it from, engine line of the read, engine line that opens the file).
# Library and user-routine keys load code and are never opened as data by dfm.
NUMBER_OR_FILE = {
    "sed": {"mudcnt": ("sedimentoverall", "rdsed.f90:507", "rdsed.f90:521"),
            "pmcrit": ("sedimentoverall", "rdsed.f90:544", "rdsed.f90:556"),
            "sedd50": ("sediment", "rdsed.f90:680", "rdsed.f90:694"),
            "seddia": ("sediment", "rdsed.f90:685", "rdsed.f90:694"),
            "inisedthick": ("sediment", "rdsed.f90:866", "rdmorlyr.f90:1342"),
            "sdbuni": ("sediment", "rdsed.f90:869", "rdmorlyr.f90:1342"),
            "inifluffmass": ("sediment", "rdmor.f90:2197", "rdmorlyr.f90:1290")},
    "mor": {"morfac": ("morphology", "rdmor.f90:178", "rdmor.f90:187"),
            "thetsd": ("morphology", "rdmor.f90:498", "rdmor.f90:506"),
            "burfluff0": ("flufflayer", "rdmor.f90:2221", "rdmor.f90:2235"),
            "burfluff1": ("flufflayer", "rdmor.f90:2221", "rdmor.f90:2235"),
            "depfac": ("flufflayer", "rdmor.f90:2270", "rdmor.f90:2286")}}
BC_FILE = ("morphology", "rdmor.f90:725", "rdmor.f90:729")  # combinepaths(filmor, BcFil) at rdmor.f90:727
FILE_NAME_SOURCES = {"resolution": "properties.f90:3229 and rdmor.f90:727: combinepaths(path of the .sed/.mor file, value)",
                     "combinepaths": "combinepaths.f90:51-88", "commit": SOURCES["commit"]}
LIBRARY_KEYS = {"settlelib", "dll", "transplib", "inputfile"}
LOGICAL_WORDS = {"true", "t", "y", "yes", ".true.", "j", "ja", "w", "waar", "on",
                 "false", "f", "n", "no", ".false.", "nee", "o", "off", "onwaar"}  # string_module.f90:1102-1146
METADATA = {"filecreatedby", "filecreationdate", "fileversion"}
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")


def _decode(raw: bytes, path: Path) -> str:
    if len(raw) > TEXT_LIMIT:
        raise DfmError("input_too_large", "Text input exceeds the catalog reader limit", 4, str(path))
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DfmError("unsupported_encoding", "Catalog files must be UTF-8 or ASCII", 4, str(path)) from exc


def ini_blocks(text: str) -> list[dict]:
    """Blocks as the engine's INI reader sees them: `#` comments, `;` and `*` lines skipped."""
    blocks: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";") or line.lstrip(" ").startswith("*"):
            continue
        if code.startswith("[") and code.endswith("]"):
            blocks.append({"name": code[1:-1].strip(), "line": number, "entries": []})
        elif "=" in code and blocks:
            key, value = code.split("=", 1)
            blocks[-1]["entries"].append((key.strip().casefold(), value.strip(), number))
        else:
            raise DfmError("syntax_error", "Expected [block] or key = value", 4, {"line": number})
    return blocks


def _first(entries, key):
    values = [v for k, v, _ in entries if k == key]
    return values[0] if values else None


def enumerate_ini_field(path: Path, reference, issues: list, parsed: dict) -> dict:
    """Follow every [Initial]/[Parameter] dataFile of one IniFieldFile.

    `reference(parent, address, value)` is the caller's resolver: it applies the
    MDU's path rule, records the link, flags a missing or outside file and
    returns the existing path or None.
    """
    raw = path.read_bytes()
    parsed[path] = (hashlib.sha256(raw).hexdigest(), len(raw))
    summary = {"path": str(path), "version": None, "blocks": []}
    try:
        blocks = ini_blocks(_decode(raw, path))
    except DfmError as exc:
        issues.append({"code": exc.code, "file": str(path), "message": str(exc)})
        return summary
    general = [b for b in blocks if b["name"].casefold() == "general"]
    version = _first(general[0]["entries"], "fileversion") if len(general) == 1 else None
    match = re.match(r"\s*([0-9]+)\.([0-9]+)", version or "")
    summary["version"] = version
    if not match or int(match[1]) < 2:
        issues.append({"code": "unsupported_input_format", "file": str(path), "setting": "General/fileVersion",
                       "value": version, "reason": "IniFieldFile format below major version 2 is ignored by the engine",
                       "source": SOURCES["ini_version"]})
    file_type = _first(general[0]["entries"], "filetype") if len(general) == 1 else None
    if file_type is not None and file_type.casefold() != "inifield":
        issues.append({"code": "unsupported_input_format", "file": str(path), "setting": "General/fileType", "value": file_type})
    ordinal = 0
    for block in blocks:
        name = block["name"]
        if name.casefold() == "general":
            continue
        ordinal += 1
        label = f"{path.name}[{name}#{ordinal}]"
        entries = block["entries"]
        keys = {k for k, _, _ in entries}
        if name.casefold() not in {"initial", "parameter"}:
            for key in sorted(keys):
                if "file" in key:
                    issues.append({"code": "unsupported_reference", "setting": f"{label}/{key}", "line": block["line"]})
            issues.append({"code": "invalid_ini_field_block", "setting": label,
                           "reason": "Block other than [Initial]/[Parameter] is ignored by the engine and would hide user data"})
            continue
        for key in sorted(keys):
            if "file" in key and key not in {"datafile", "datafiletype"}:
                issues.append({"code": "unsupported_reference", "setting": f"{label}/{key}",
                               "value": _first(entries, key)})
        quantity, data_file, data_type = (_first(entries, k) for k in ("quantity", "datafile", "datafiletype"))
        if not quantity or not data_file or not data_type:
            issues.append({"code": "invalid_ini_field_block", "setting": label,
                           "reason": "quantity, dataFile and dataFileType are all required; the engine would ignore the block",
                           "missing": [k for k, v in (("quantity", quantity), ("dataFile", data_file), ("dataFileType", data_type)) if not v]})
            continue
        item = {"block": name, "ordinal": ordinal, "quantity": quantity, "data_file": data_file,
                "data_file_type": data_type, "line": block["line"]}
        summary["blocks"].append(item)
        kind = data_type.casefold()
        if kind not in INI_TYPES:
            issues.append({"code": "unsupported_input_format", "setting": f"{label}/dataFileType", "value": data_type,
                           "reason": "unknown to the engine" if kind not in INI_UNENUMERATED else "references of this type are not enumerated"})
            continue
        target = reference(path, f"{label}/datafile", data_file)
        if target is not None and target.suffix.casefold() not in INI_TYPES[kind]:
            issues.append({"code": "unsupported_input_format", "path": str(target), "setting": f"{label}/dataFile"})
    return summary


def _tokens(text: str):
    """Sediment/morphology lines: `Key = value  [unit]  free text`; `#name#` quotes a value."""
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "*")):
            continue
        yield number, stripped


def sed_or_mor_values(text: str) -> list[dict]:
    blocks: list[dict] = []
    for number, line in _tokens(text):
        if line.startswith("[") and "]" in line:
            blocks.append({"name": line[1:line.index("]")].strip(), "line": number, "entries": []})
        elif "=" in line and blocks:
            key, rest = line.split("=", 1)
            rest = rest.strip()
            if rest.startswith("#") and "#" in rest[1:]:
                token = rest[1:rest.index("#", 1)]
            else:
                token = rest.split(None, 1)[0] if rest else ""
            blocks[-1]["entries"].append((key.strip().casefold(), token, number))
        elif line.startswith("#"):
            continue
        else:
            raise DfmError("syntax_error", "Expected [block] or key = value", 4, {"line": number})
    return blocks


def enumerate_sed_or_mor(kind: str, path: Path, issues: list, parsed: dict, reference=None, mor_path: Path | None = None) -> dict:
    """Catalog one .sed (`sed`) or .mor (`mor`) file; Contract R8.

    `reference(parent, address, value, base)` is the caller's resolver (as for the INI
    catalog) with an explicit base folder. File names are resolved from the folder of the
    .sed/.mor file (`mor_path`'s folder for IniFluffMass); without a resolver every name
    is refused as before. Library keys and every other file-naming key stay refused.
    """
    raw = path.read_bytes()
    parsed[path] = (hashlib.sha256(raw).hexdigest(), len(raw))
    summary = {"path": str(path), "references": []}
    try:
        blocks = sed_or_mor_values(_decode(raw, path))
    except DfmError as exc:
        issues.append({"code": exc.code, "file": str(path), "message": str(exc)})
        return summary
    fractions = []
    for ordinal, block in enumerate(blocks, 1):
        label = f"{path.name}[{block['name']}#{ordinal}]"
        name = block["name"].casefold()
        for key, token, line in block["entries"]:
            if key in METADATA or not token:
                continue
            site = NUMBER_OR_FILE[kind].get(key)
            if kind == "mor" and key == "bcfil":
                site = BC_FILE
            data_key = site is not None and site[0] == name
            names_file = key in LIBRARY_KEYS or key == "bcfil" or bool(re.search(r"^file|file$|fil$", key))
            if data_key and (key == "bcfil" or not (NUMBER.fullmatch(token) or token.casefold() in LOGICAL_WORDS)):
                base = path.parent
                if key == "inifluffmass":
                    base = mor_path.parent if mor_path is not None else None
                if reference is None or base is None:
                    issues.append({"code": "unsupported_reference", "setting": f"{label}/{key}", "value": token, "line": line, "source": site[1]})
                    continue
                target = reference(path, f"{label}/{key}", token, base)
                summary["references"].append({"key": key, "setting": f"{label}/{key}", "value": token, "line": line,
                                              "path": str(target) if target is not None else None, "exists": target is not None,
                                              "base": str(base), "source": site[1], "opened_at": site[2]})
                continue
            numeric_key = key in NUMBER_OR_FILE[kind] or (kind == "mor" and name == "flufflayer")
            if names_file or (numeric_key and not (NUMBER.fullmatch(token) or token.casefold() in LOGICAL_WORDS)):
                issues.append({"code": "unsupported_reference", "setting": f"{label}/{key}", "value": token, "line": line,
                               "source": SOURCES["sediment_libraries" if kind == "sed" and names_file else
                                                 "morphology_bc_file" if names_file else
                                                 f"{'sediment' if kind == 'sed' else 'morphology'}_number_or_file"]})
        if kind == "sed" and name == "sediment":
            fraction = {"name": _first(block["entries"], "name"), "type": (_first(block["entries"], "sedtyp") or "").casefold()}
            fractions.append(fraction)
        if kind == "mor" and name == "morphology":
            summary.update(morfac=_first(block["entries"], "morfac"), morstt=_first(block["entries"], "morstt"))
    if kind == "sed":
        summary["fractions"] = fractions
    return summary
