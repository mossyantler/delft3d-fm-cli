"""Real installed E007 file-scan comparison; no CLR/GUI/Console/engine execution."""
import argparse
import json
import logging
from pathlib import Path
import shutil
import struct
import subprocess
import traceback
from unittest.mock import patch

from .verify_gui_entry_resolver import require, digest, save, pe_layout, body, anchor, instructions, config_metadata

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return digest(Path(path).read_bytes())


def string_operand(raw, heap_offset, index):
    at = heap_offset + index
    require(at < len(raw), "User-string token outside file")
    first = raw[at]
    width = 1 if first < 0x80 else 2 if first < 0xc0 else 4 if first < 0xe0 else 0
    require(width and at + width <= len(raw), "Invalid compressed user-string size")
    length = first & {1: 0x7f, 2: 0x3f, 4: 0x1f}[width]
    for byte in raw[at + 1:at + width]:
        length = length * 256 + byte
    require(1 <= length <= 12000 and length % 2 == 1 and at + width + length <= len(raw), "Invalid bounded UTF16 user-string length")
    value = raw[at + width:at + width + length - 1].decode("utf-16-le", errors="surrogatepass")
    return value, anchor(raw, at, width + length)


def verify_image(image):
    import dnfile
    expected = image["identity"]; path = Path(expected["path"]); raw = path.read_bytes(); layout = pe_layout(raw)
    require(sha(path) == expected["sha256"] and len(raw) == expected["bytes"], "I recorded file differs from actual bytes")
    require(expected["target_code_executed"] is False and expected["strong_name_signature_verified"] is False, "Metadata must not claim execution or cryptographic verification")
    pe = dnfile.dnPE(data=raw)
    try:
        assembly = pe.net.mdtables.Assembly.rows[0]
        require(expected["assembly_name"] == str(assembly.Name) and expected["assembly_version"] == ".".join(str(getattr(assembly, k)) for k in ("MajorVersion", "MinorVersion", "BuildNumber", "RevisionNumber")), "Actual CLR assembly identity differs")
        require(expected["entry_point_token"] == hex(layout["entry_token"]) and expected["machine"] == hex(layout["machine"]) and expected["cli_flags"] == layout["clr_flags"], "Independent native/CLR headers differ")
        methods = pe.net.mdtables.MethodDef.rows
        owners = {m.row_index: str(t.TypeNamespace) + "." + str(t.TypeName) for t in pe.net.mdtables.TypeDef for m in t.MethodList}
        fields = {m.row_index: str(t.TypeNamespace) + "." + str(t.TypeName) for t in pe.net.mdtables.TypeDef for m in t.FieldList}
        tables = {table.number: table for table in pe.net.mdtables.tables_list}

        def check_reference(token, resolved):
            table_id, rid = token >> 24, token & 0xffffff
            if table_id == 0x70:
                literal, _ = string_operand(raw, pe.net.user_strings.file_offset, rid)
                require(resolved.get("kind") == "user_string" and resolved.get("value") == literal, "I string-token rendering differs")
                return
            require(table_id in tables and 1 <= rid <= len(tables[table_id].rows), "I reference token outside actual metadata")
            table = tables[table_id]; row = table.rows[rid - 1]
            require(resolved.get("table") == table.name and type(resolved.get("index")) is int and resolved["index"] == rid, "I resolved token table/index differs")
            if table_id in (4, 6):
                require(resolved["name"] == str(row.Name) and resolved["owner"] == (fields if table_id == 4 else owners)[rid], "I member identity differs from actual owning type")
            elif table_id in (1, 2):
                require(resolved["owner"] == str(row.TypeNamespace) and resolved["name"] == str(row.TypeName), "I type identity differs")
                if table_id == 1 and row.ResolutionScope.table is not None and row.ResolutionScope.table.name == "AssemblyRef":
                    require(resolved.get("assembly_scope") == str(row.ResolutionScope.row.Name), "I assembly reference scope differs")
            elif table_id == 10:
                require(resolved["name"] == str(row.Name) and resolved["signature_hex"] == bytes(row.Signature.value).hex(), "I MemberRef name/signature differs")
                parent = row.Class
                if parent.table is not None and parent.table.number in (1, 2):
                    actual_owner = (str(parent.row.TypeNamespace) + "." + str(parent.row.TypeName)).lstrip(".")
                    require(resolved.get("owner") == actual_owner, "I MemberRef owning type differs")
            elif table_id == 43:
                reference = row.Method
                require(resolved["instantiation_hex"] == bytes(row.Instantiation.value).hex(), "I generic method signature differs")
                check_reference((reference.table.number << 24) | reference.row_index, resolved["method"])
            elif table_id == 27:
                require(resolved["signature_hex"] == bytes(row.Signature.value).hex(), "I TypeSpec signature differs")

        checked = []
        for method in image["methods"]:
            token = int(method["token"], 16); rid = token & 0xffffff
            require(token >> 24 == 6 and 1 <= rid <= len(methods), "I method token outside original MethodDef table")
            row = methods[rid - 1]
            require(row.Rva == method["rva"] and str(row.Name) == method["name"] and owners[rid] == method["owner"], "I method owner/token/RVA does not bind actual row")
            result = {"token": method["token"], "owner": owners[rid], "name": str(row.Name), "row_anchor": anchor(raw, row.struct.get_file_offset(), row.row_size)}
            if not row.Rva:
                require(method["body_state"] == "no_managed_body", "I fabricated managed body")
                result["managed_body"] = "absent; native/runtime semantics unresolved"
            else:
                at, header, code = body(raw, layout, row.Rva)
                require(method["header_file_offset"] == at and method["il_file_offset"] == at + header and method["il_bytes"] == len(code) and method["il_sha256"] == digest(code), "I code hash or file extent differs from independent PE mapping")
                own = [(r["il_offset"], r["opcode"], r["token"]) for r in instructions(code)]
                actual = [(r["il_offset"], r["opcode"], int(r["token"], 16)) for r in method["instructions"] if r["name"] in ("call", "callvirt", "ldstr", "newobj", "ldftn", "ldvirtftn")]
                require(own == actual, "Independent IL token/operand extents differ")
                result["body_anchor"] = anchor(raw, at, header + len(code))
                result["user_string_anchors"] = []
                for item in method["instructions"]:
                    encoded = bytes.fromhex(item["instruction_bytes"]); pos = item["file_offset"]
                    require(raw[pos:pos + len(encoded)] == encoded, "I instruction byte anchor differs")
                    if "resolved" in item:
                        check_reference(int(item["token"], 16), item["resolved"])
                    if item["name"] == "ldstr":
                        literal, source = string_operand(raw, pe.net.user_strings.file_offset, int(item["token"], 16) & 0xffffff)
                        require(item["resolved"]["value"] == literal, "I rendered user string differs from actual UTF16 heap bytes")
                        result["user_string_anchors"].append({"value": literal, **source})
            checked.append(result)
        require(sha(path) == expected["sha256"], "Image changed during independent verification")
        return {"state": "passed_raw_PE_CLR_IL_string_anchors", "file_sha256": expected["sha256"], "methods": checked}
    finally:
        pe.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--framework-root", required=True, type=Path)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--anchor-sha256", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    report = {"state": "in_progress", "processes_launched": 0, "target_code_loaded": False,
              "profile_config_writes": False, "actual_resolved_paths": None, "production_admitted": False}
    source = ROOT / "research/workflows/replay"
    before = {str(p.relative_to(ROOT)): sha(p) for p in source.glob("gui_entry_resolver*.py")}
    try:
        require(sha(args.anchor) == args.anchor_sha256, "Independent out-of-band original anchor differs")
        from research.workflows.replay import gui_entry_resolver as product
        from research.workflows.replay import gui_guest_controller_proof as proofs
        with patch.object(subprocess, "Popen", side_effect=AssertionError("No target/tool process allowed in file-only V scan")):
            result = product.scan(args.install, args.framework_root, args.anchor, args.anchor_sha256, out / "product-file-scan")
        evidence = Path(result["report"])
        require(sha(evidence) == result["sha256"], "Published I receipt hash differs")
        actual = json.loads(evidence.read_text())
        require(actual["state"] == "partial_unresolved" and actual["target_code_executed"] is False and actual["CLR_started"] is False, "Static scan promoted runtime context")
        for key in ("native_ready", "production_admitted", "controller_proof_emitted"):
            require(actual[key] is False, "Static scan promoted launch authority: " + key)
        require(not proofs.ADMITTED_RESOLVERS, "Controller production admission changed")
        checks = {}
        for name, image in actual["managed_images"].items():
            checks[name] = verify_image(image)
        config = config_metadata(args.install / "bin/DeltaShell.Gui.exe.config")
        require(actual["application_policy"]["sha256"] == config["sha256"] and all(actual["application_policy"]["app_settings"][k] == v for k, v in config["app_settings"].items()), "Selected app config provenance differs")
        for name in ("portable_user_config", "core_user_config_local", "core_user_config_roaming", "log_directory"):
            require(actual["resolution"][name]["absolute_path"] is None and actual["resolution"][name]["exact_path_proven"] is False, "Uncertain path promoted: " + name)
        report.update(state="passed_independent_installed_file_scan_actual_paths_unresolved", product_scan=result, checked_images=checks,
                      config_anchors=config, source_sha256=before, controller_admitted_resolvers=0,
                      remaining_unknowns=actual["residual_requirements"], controller_proof_emitted=False)
    except Exception as exc:
        report.update(state="failed_independent_file_scan_review", error=str(exc), traceback=traceback.format_exc())
    finally:
        after = {str(p.relative_to(ROOT)): sha(p) for p in source.glob("gui_entry_resolver*.py")}
        report["product_sources_unchanged_during_review"] = before == after
        report["source_sha256_after"] = after
        if before != after:
            report["state"] = "unverified_product_changed_during_review"
        save(out / "verification.json", report)
        print(json.dumps({"state": report["state"], "path": str(out / "verification.json"), "sha256": sha(out / "verification.json")}))
    return 0 if report["state"].startswith("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
