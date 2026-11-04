"""Independent E007 entry-context metadata audit. No target code is loaded/run.

Uses optional dnfile to label CLR rows, but maps RVAs and verifies every retained
IL/metadata anchor independently against original PE bytes. Static anchors do
not establish actual entry-AppDomain paths or authorize a controller launch.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
from pathlib import Path, PureWindowsPath
import re
import struct
import xml.etree.ElementTree as ET


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def pe_layout(raw):
    require(len(raw) >= 256 and raw[:2] == b"MZ", "Not a bounded PE binary")
    header = struct.unpack_from("<I", raw, 0x3c)[0]
    require(header + 24 <= len(raw) and raw[header:header + 4] == b"PE\0\0", "Invalid PE signature")
    machine, count = struct.unpack_from("<HH", raw, header + 4)
    optional_size = struct.unpack_from("<H", raw, header + 20)[0]
    optional = header + 24
    magic = struct.unpack_from("<H", raw, optional)[0]
    require(magic in (0x10b, 0x20b), "Unsupported PE optional header")
    dirs = optional + (96 if magic == 0x10b else 112)
    require(dirs + 15 * 8 <= optional + optional_size, "Truncated CLR data directory")
    clr_rva, clr_size = struct.unpack_from("<II", raw, dirs + 14 * 8)
    sections = []
    for i in range(count):
        at = optional + optional_size + 40 * i
        require(at + 40 <= len(raw), "Truncated PE section table")
        virtual_size, virtual, size, offset = struct.unpack_from("<IIII", raw, at + 8)
        require(offset + size <= len(raw), "PE section raw range escapes file")
        sections.append((virtual, virtual_size, offset, size))
    def offset(rva, size=1):
        matches = [raw_at + rva - va for va, vs, raw_at, raw_size in sections if va <= rva and rva + size <= va + raw_size]
        require(len(matches) == 1 and matches[0] + size <= len(raw), "Ambiguous/unmapped initialized PE RVA")
        return matches[0]
    require(clr_rva and clr_size >= 24, "No CLR header; wrong unmanaged binary")
    clr = offset(clr_rva, 24)
    flags, entry = struct.unpack_from("<II", raw, clr + 16)
    return {"machine": machine, "optional_magic": magic, "clr_flags": flags, "entry_token": entry,
            "clr_offset": clr, "sections": sections, "offset": offset}


def anchor(raw, offset, length):
    require(type(offset) is int and type(length) is int and 0 <= offset <= len(raw) and 0 < length <= 16384 and offset + length <= len(raw), "Invalid exact byte anchor")
    part = raw[offset:offset + length]
    return {"file_offset": offset, "bytes": length, "sha256": digest(part), "hex": part.hex()}


def check_anchor(raw, record):
    require(anchor(raw, record["file_offset"], record["bytes"]) == record, "Counterfeit/stale byte anchor")


def body(raw, layout, rva):
    at = layout["offset"](rva)
    first = raw[at]
    if first & 3 == 2:
        header, size = 1, first >> 2
    else:
        require(first & 3 == 3 and at + 12 <= len(raw), "Invalid managed method header")
        flags = struct.unpack_from("<H", raw, at)[0]
        header = (flags >> 12) * 4
        size = struct.unpack_from("<I", raw, at + 4)[0]
        require(header >= 12, "Truncated fat method header")
    require(0 < size <= 12000, "Method outside compact anchor bound")
    require(layout["offset"](rva + header, size) == at + header, "Managed method leaves initialized PE section")
    return at, header, raw[at + header:at + header + size]


def instructions(code):
    """Decode operand extents; retain only exact call/string token references."""
    one = set(range(0x0e, 0x14)) | {0x1f, 0xde} | set(range(0x2b, 0x38))
    four = {0x20, 0x22, 0x27, 0x28, 0x29, 0x6f, 0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x79, 0x81, 0x8c, 0x8d, 0x8f, 0xa3, 0xa4, 0xa5, 0xc2, 0xc6, 0xd0, 0xdd} | set(range(0x38, 0x45)) | set(range(0x7b, 0x81))
    cursor = 0
    while cursor < len(code):
        at = cursor; op = code[cursor]; cursor += 1
        if op == 0xfe:
            require(cursor < len(code), "Truncated two-byte IL opcode")
            op = 0xfe00 | code[cursor]; cursor += 1
            width = 2 if 0xfe09 <= op <= 0xfe0e else 4 if op in (0xfe06, 0xfe07, 0xfe15, 0xfe16, 0xfe1c) else 1 if op in (0xfe12, 0xfe19) else 0
        elif op == 0x45:
            require(cursor + 4 <= len(code), "Truncated IL switch")
            width = 4 + 4 * struct.unpack_from("<I", code, cursor)[0]
        else:
            width = 1 if op in one else 4 if op in four else 8 if op in (0x21, 0x23) else 0
        require(cursor + width <= len(code), "Truncated IL operand")
        if op in (0x28, 0x6f, 0x72, 0x73, 0xfe06, 0xfe07):
            yield {"il_offset": at, "opcode": hex(op), "token": struct.unpack_from("<I", code, cursor)[0]}
        cursor += width


TARGETS = {
    "DeltaShell.Gui.exe": {"DeltaShell.Gui.App": {".ctor", "App_Startup", "HandleCommandLineOptions"},
        "DeltaShell.Gui.PortableSettingsProvider": {"get_ApplicationName", "get_SettingsXML", "RetrieveUserSettingFromUserConfigIfFileExist", "SetPropertyValues"}},
    "DelftTools.Utils.dll": {"DelftTools.Utils.SettingsHelper": {".cctor", "InitializeFromExecutingAssembly", "InitializeFromApplicationConfiguration", "InitializeFromSettings", "GetApplicationLocalUserSettingsDirectory", "GetApplicationLocalUserSettingsDirectoryName"}},
    "DeltaShell.Core.dll": {"DeltaShell.Core.DeltaShellUserDataFolderConverter": {"Convert", "DeleteOldLogFiles"}, "DeltaShell.Core.Properties.Settings": {".cctor"}},
    "System.Configuration.dll": {"System.Configuration.ClientConfigPaths": {".ctor", "GetPaths", "GetTypeAndHashSuffix"}},
    "System.Windows.Forms.dll": {"System.Windows.Forms.Application": {"get_ProductName", "get_ExecutablePath"}},
}


def binary_metadata(path):
    import dnfile
    path = Path(path); raw = path.read_bytes(); layout = pe_layout(raw)
    pe = dnfile.dnPE(data=raw)
    require(pe.net is not None, "Missing managed metadata")
    require(pe.net.struct.EntryPointTokenOrRva == layout["entry_token"], "Independent CLR entry token differs")
    owners = {}; selected = []
    for type_row in pe.net.mdtables.TypeDef:
        full = str(type_row.TypeNamespace) + "." + str(type_row.TypeName)
        for method in type_row.MethodList:
            owners[method.row_index] = full
    rows = pe.net.mdtables.MethodDef.rows
    def token_name(token):
        table, rid = token >> 24, token & 0xffffff
        if table == 0x70:
            item = pe.net.user_strings.get(rid)
            return {"kind": "user_string", "value": str(item.value) if item else "unavailable"}
        if table == 6 and 1 <= rid <= len(rows):
            return {"kind": "method", "name": owners.get(rid, "?") + "." + str(rows[rid - 1].Name)}
        if table == 10 and 1 <= rid <= len(pe.net.mdtables.MemberRef.rows):
            member = pe.net.mdtables.MemberRef.rows[rid - 1]; parent = member.Class.row
            return {"kind": "member_reference", "name": str(getattr(parent, "TypeNamespace", "")) + "." + str(getattr(parent, "TypeName", getattr(parent, "Name", "?"))) + "." + str(member.Name)}
        return {"kind": "other_metadata_token", "unresolved_token_hex": hex(token)}
    targets = TARGETS.get(path.name, {})
    for i, method in enumerate(rows, 1):
        owner = owners.get(i, "?"); name = str(method.Name)
        if not (layout["entry_token"] == 0x06000000 + i or name in targets.get(owner, ())):
            continue
        require(method.Rva, "Target managed method has no IL RVA")
        at, header, code = body(raw, layout, method.Rva)
        require(pe.get_data(method.Rva, header + len(code)) == raw[at:at + header + len(code)], "Independent section mapping differs from metadata library")
        references = [{**item, **token_name(item["token"])} for item in instructions(code)]
        selected.append({"type": owner, "method": name, "token": hex(0x06000000 + i), "rva": method.Rva,
            "row_anchor": anchor(raw, method.struct.get_file_offset(), method.row_size),
            "body_anchor": anchor(raw, at, header + len(code)), "il_bytes": len(code), "references": references})
    assembly = pe.net.mdtables.Assembly.rows[0]
    attrs = []
    for attribute in pe.net.mdtables.CustomAttribute:
        if attribute.Parent.table.name != "Assembly":
            continue
        constructor = attribute.Type.row
        klass = getattr(getattr(constructor, "Class", None), "row", None)
        name = str(getattr(klass, "TypeName", "?"))
        if name in ("AssemblyCompanyAttribute", "AssemblyProductAttribute", "AssemblyFileVersionAttribute", "TargetFrameworkAttribute"):
            attrs.append({"name": name, "serialized_blob_hex": attribute.Value.value.hex(),
                          "metadata_row_anchor": anchor(raw, attribute.struct.get_file_offset(), attribute.row_size)})
    record = {"path": str(path.resolve()), "sha256": digest(raw), "bytes": len(raw), "pe_machine": hex(layout["machine"]),
        "clr_flags": hex(layout["clr_flags"]), "entry_token": hex(layout["entry_token"]),
        "clr_header_anchor": anchor(raw, layout["clr_offset"], 24), "assembly_name": str(assembly.Name),
        "assembly_version": ".".join(str(getattr(assembly, k)) for k in ("MajorVersion", "MinorVersion", "BuildNumber", "RevisionNumber")),
        "assembly_row_anchor": anchor(raw, assembly.struct.get_file_offset(), assembly.row_size), "assembly_attributes": attrs, "methods": selected,
        "trust": "local provenance fingerprint only; no publisher/authenticode or live entry-context attestation"}
    require(digest(path.read_bytes()) == record["sha256"], "Binary changed during metadata inspection")
    return record


def compare_product_metadata(path, expected):
    """I metadata is the subject; V raw PE offsets and original bytes are oracle."""
    from research.workflows.replay.gui_entry_resolver_metadata import ManagedImage
    raw = Path(path).read_bytes()
    with ManagedImage(path) as image:
        actual = image.identity()
        for ikey, vkey in (("sha256", "sha256"), ("bytes", "bytes"), ("assembly_name", "assembly_name"),
                           ("assembly_version", "assembly_version"), ("entry_point_token", "entry_token"), ("machine", "pe_machine")):
            require(type(actual.get(ikey)) is type(expected[vkey]) and actual[ikey] == expected[vkey], "I/V installed binary identity mismatch: " + ikey)
        require(actual.get("target_code_executed") is False and actual.get("strong_name_signature_verified") is False,
                "Metadata or public-key token must not self-assert execution or signature verification")
        compared = []
        for method in expected["methods"]:
            code = image.method_record(int(method["token"], 16))
            check_anchor(raw, method["body_anchor"])
            require(code.get("rva") == method["rva"] and code.get("header_file_offset") == method["body_anchor"]["file_offset"] and code.get("il_bytes") == method["il_bytes"], "I/V method/PE offset mismatch")
            size = method["body_anchor"]["bytes"] - method["il_bytes"]
            start = method["body_anchor"]["file_offset"] + size
            require(code.get("il_file_offset") == start and code.get("il_sha256") == digest(raw[start:start + method["il_bytes"]]), "I IL hash/offset disagrees with actual byte anchor")
            own = [(item["il_offset"], item["opcode"], item["token"]) for item in method["references"]]
            other = [(item["il_offset"], item["opcode"], int(item["token"], 16)) for item in code["instructions"] if item["name"] in ("call", "callvirt", "ldstr", "newobj", "ldftn", "ldvirtftn")]
            require(own == other, "I/V IL instruction operand/token boundaries differ")
            for item in code["instructions"]:
                at = item["file_offset"]; encoded = bytes.fromhex(item["instruction_bytes"])
                require(raw[at:at + len(encoded)] == encoded, "I instruction anchor differs from original PE")
            compared.append({"token": method["token"], "method": method["type"] + "." + method["method"], "il_bytes": method["il_bytes"], "matched_references": len(own)})
    return {"state": "passed_independent_PE_method_anchor_comparison", "methods": compared, "actual_runtime_paths": "not_established"}


def config_metadata(path):
    path = Path(path); raw = path.read_bytes(); tree = ET.fromstring(raw)
    settings = {item.attrib["key"]: item.attrib["value"] for item in tree.findall("./appSettings/add") if item.attrib.get("key") in ("applicationName", "publicReleaseVersion", "distributionName")}
    anchors = []
    for literal in list(settings) + list(settings.values()) + ["%path{}", "DeltaShellUserDataFolderConverter", "supportedRuntime"]:
        encoded = literal.encode(); start = raw.find(encoded)
        if start >= 0:
            anchors.append({"literal": literal, **anchor(raw, start, len(encoded))})
    return {"path": str(path.resolve()), "sha256": digest(raw), "bytes": len(raw), "app_settings": settings, "anchors": anchors,
            "startup": [dict(item.attrib) for item in tree.findall("./startup/supportedRuntime")],
            "log_patterns": [dict(item.attrib) for item in tree.findall("./log4net/appender/file/conversionPattern")],
            "actual_configuration_manager_context": "not_observed"}


def validate_binary_binding(actual, expected):
    for key in ("path", "sha256", "bytes", "assembly_name", "assembly_version", "entry_token"):
        require(type(actual.get(key)) is type(expected.get(key)) and actual.get(key) == expected.get(key), "Wrong binary/provenance binding: " + key)
    require(actual.get("trust") == expected.get("trust"), "A self-asserted trust label cannot replace the original binary binding")
    return {"state": "same_recorded_binary", "cryptographic_authority": "not_established"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--framework-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--compare-product-metadata", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    messages = []
    class Capture(logging.Handler):
        def emit(self, record):
            if len(messages) < 100:
                messages.append(record.getMessage())
    handler = Capture(); logger = logging.getLogger("dnfile"); logger.addHandler(handler); logger.propagate = False
    report = {"state": "collecting", "processes_launched": 0, "target_code_loaded": False, "profile_config_writes": False, "binaries": {},
        "actual_resolved_paths": None, "launch_permission": False,
        "remaining_unknowns": ["Real target entry assembly/AppDomain and exact ConfigurationManager cache/evidence context not observed",
            "Selected framework root is an inspection input; actual runtime bitness/loaded framework must be separately bound",
            "Runtime String.GetHashCode/path initialization cannot be replaced by guessed folder names",
            "Portable, .NET local and roaming user.config and log directory remain separate authorities",
            "Calling SettingsHelper creates a directory; log converter can delete old logs; neither method is executed here",
            "No admitted resolver/key or publisher-trust assertion is derived from local hashes"]}
    try:
        paths = [args.install / "bin" / name for name in ("DeltaShell.Gui.exe", "DeltaShell.Console.exe", "DeltaShell.Core.dll", "DelftTools.Utils.dll")]
        paths += [args.framework_root / name for name in ("mscorlib.dll", "System.dll", "System.Configuration.dll", "System.Windows.Forms.dll")]
        for path in paths:
            report["binaries"][path.name] = binary_metadata(path)
            if args.compare_product_metadata:
                report.setdefault("product_metadata_comparison", {})[path.name] = compare_product_metadata(path, report["binaries"][path.name])
        report["application_config"] = config_metadata(args.install / "bin/DeltaShell.Gui.exe.config")
        from research.workflows.replay import gui_guest_controller_proof as proofs
        report["controller_admitted_resolvers"] = len(proofs.ADMITTED_RESOLVERS)
        require(not proofs.ADMITTED_RESOLVERS, "Resolver admission changed; independent contract re-review required")
        report.update(state="passed_static_metadata_provenance_actual_paths_unresolved", metadata_parser_diagnostics=messages)
    except Exception as exc:
        report.update(state="failed_static_metadata_review", error=str(exc), metadata_parser_diagnostics=messages)
    finally:
        logger.removeHandler(handler)
        save(out / "verification.json", report)
        print(json.dumps({"state": report["state"], "path": str(out / "verification.json"), "sha256": digest((out / "verification.json").read_bytes())}))
    return 0 if report["state"].startswith("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
