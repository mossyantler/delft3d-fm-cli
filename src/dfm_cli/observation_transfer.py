"""Composable standalone named XYN transfer; registration owned by parent.

register(observation_subparsers), execute(args), contract(). Preview never writes.
Public APIs: export_xyn(mdu,out,*,apply=False,expect_sha256=None) and
import_xyn(mdu,source,*,mode,crs,unit,apply=False,expect_sha256=None).
No root source edits, model-ref rewrites, native runs or GUI parity assertions.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .common import DfmError
from .observation_inputs import Inputs, digest, publish
from .observation_text import parse, require_record_bounds, MAX_TEXT
from .observation_transfer_contract import CONTRACT, MAX_ROWS, SOURCE, LIMITS, contract
from .observation_transfer_io import Guard, fail, fresh_export, lexical_external, new_destination, source_file


def register(commands):
    for action in ("export","import"):
        parser=commands.add_parser(action,help="Exact standalone named XYN export" if action=="export" else "Import named XYN with an explicit collision/replacement policy")
        parser.add_argument("mdu",type=Path)
        if action=="export":
            parser.add_argument("--out",required=True,type=Path,help="Absent explicit .xyn outside model; parent must exist; never overwrite")
        else:
            parser.add_argument("--source",required=True,type=Path)
            parser.add_argument("--mode",required=True,choices=("append","replace-all"),help="append refuses every collision; replace-all replaces the entire ObsFile and discloses removed IDs")
            parser.add_argument("--crs",required=True,help="Explicit EPSG:NNNN for incoming file XY; must match actual projected model mesh; no transform")
            parser.add_argument("--unit",required=True,choices=("m",))
        parser.add_argument("--apply",action="store_true")
        parser.add_argument("--expect-sha256",help="input_sha256 from same graph/source/request/destination/output preview")
    return commands


def execute(args):
    if args.action=="export":
        return export_xyn(args.mdu,args.out,apply=args.apply,expect_sha256=args.expect_sha256)
    if args.action=="import":
        return import_xyn(args.mdu,args.source,mode=args.mode,crs=args.crs,unit=args.unit,apply=args.apply,expect_sha256=args.expect_sha256)
    fail("usage","Expected observation import or export",exit_code=2)


def _consent(apply,expected):
    if type(apply) is not bool:
        fail("usage","apply must be a Boolean",exit_code=2)
    if expected is not None and (type(expected) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}",expected)):
        fail("expected_hash","Expected one SHA256 hex string",exit_code=2)
    if apply and expected is None:
        fail("expected_hash","--apply requires the exact request preview --expect-sha256",exit_code=2)


def _named(raw,dataset):
    parsed=parse(raw)
    require_record_bounds(parsed,phase=dataset)
    if parsed["duplicate_or_casefold_aliases"]:
        fail("ambiguous_id","Duplicate/NFC/casefold station identities are refused",{"dataset":dataset,"groups":parsed["duplicate_or_casefold_aliases"]})
    return parsed


def _fingerprint(request,expected):
    fingerprint=digest(json.dumps(request,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii"))
    if expected is not None and fingerprint!=expected.lower():
        fail("stale_preview","Connected graph/source/request/destination/output differs from preview",{"actual_input_sha256":fingerprint},4)
    return fingerprint


def _graph(graph):
    return {"mdu":str(graph.mdu),"files":graph.inventory(),"references":graph.references,"outputs":graph.output_paths}


def _base(action,fingerprint,apply):
    return {"contract":CONTRACT,"operation":action,"applied":apply,"input_sha256":fingerprint,
            "gui_parity":"not_verified","GUI_collision_policy":"unknown","native_execution":"not_performed",
            "native_snapped_coordinates":None,"source_basis":SOURCE,"limits":LIMITS}


def export_xyn(mdu:Path,out:Path,*,apply=False,expect_sha256=None):
    try:
        _consent(apply,expect_sha256)
        out=lexical_external(out)
        graph=Inputs(mdu,full=False)
        if graph.obs is None:
            fail("missing_obsfile","Export requires a nonempty explicit existing ObsFile=.xyn reference")
        parsed=parse(graph.obs_raw)  # Exact archival export reports static issues.
        out,parent=new_destination(graph,out)
        output={"path":str(out),"sha256":digest(graph.obs_raw),"bytes":len(graph.obs_raw)}
        request={"contract":CONTRACT,"operation":"export","graph":_graph(graph),"source":str(graph.obs),
                 "destination":output,"parent_identity":list(parent),"selection":"entire standalone ObsFile exact bytes",
                 "binding_scope":"MDU and selected XYN only; other graph/mesh/CRS neither read nor validated"}
        fingerprint=_fingerprint(request,expect_sha256)
        guard=Guard(graph)
        if not apply:
            guard.recheck()
        result={**_base("export",fingerprint,apply),"mdu":str(graph.mdu),"source":graph.files[graph.obs],
                "output":output,"station_count":len(parsed["rows"]),"station_ids":[r["id"] for r in parsed["rows"]],
                "record_buffer_check":parsed["record_buffer_check"],"history_name_width_check":parsed["history_name_width_check"],
                "duplicate_or_casefold_aliases":parsed["duplicate_or_casefold_aliases"],
                "CRS":"not inferred or validated; byte export performs no coordinate operation",
                "binding_scope":"MDU and selected XYN only; other graph/mesh/CRS neither read nor validated",
                "bound_inputs":graph.inventory(),"non_target_files_written":[],"exact_bytes":True}
        if apply:
            result["published_file"]=fresh_export(guard,out,parent,graph.obs_raw)
        return result
    except DfmError:
        raise
    except (OSError,ValueError,TypeError,UnicodeError,OverflowError) as exc:
        fail("export_io","Cannot plan or publish standalone XYN export",str(exc),4 if apply else 3)


def _merge(graph,existing,incoming,source_raw,mode):
    old={r["identity_key"]:r["id"] for r in existing["rows"]}
    new={r["identity_key"]:r["id"] for r in incoming["rows"]}
    overlaps=set(old)&set(new)
    aliases=[{"existing":old[k],"incoming":new[k]} for k in sorted(overlaps) if old[k]!=new[k]]
    if aliases:
        fail("ambiguous_id","Cross-dataset case/NFC aliases are refused in every mode",aliases)
    if mode=="append":
        if overlaps:
            fail("id_collision","Append cannot skip or overwrite an existing station",[old[k] for k in sorted(overlaps)])
        drop=3 if source_raw.startswith(b"\xef\xbb\xbf") else 0
        payload=source_raw[drop:]
        bare=graph.obs_raw.removeprefix(b"\xef\xbb\xbf")
        framing=existing["append_newline"].encode("ascii") if bare and not graph.obs_raw.endswith((b"\r",b"\n")) else b""
        output=graph.obs_raw+framing+payload
        byte_edit={"existing_prefix_bytes":len(graph.obs_raw),"EOF_framing_hex":framing.hex(),"incoming_leading_BOM_bytes_removed":drop,
                   "incoming_preserved_byte_span":[drop,len(source_raw)],"output_source_span":[len(graph.obs_raw)+len(framing),len(output)]}
    else:
        output=source_raw
        byte_edit={"whole_ObsFile_replacement":True,"all_existing_target_trivia_replaced":True,
                   "source_span":[0,len(source_raw)],"output_source_span":[0,len(output)]}
    if len(output)>MAX_TEXT:
        fail("bound","Resulting XYN exceeds8MiB")
    final=_named(output,"candidate")
    disclosure={"added_ids":[r["id"] for r in incoming["rows"] if r["identity_key"] not in old],
                "removed_ids":[r["id"] for r in existing["rows"] if mode=="replace-all" and r["identity_key"] not in new],
                "replaced_ids":[r["id"] for r in existing["rows"] if mode=="replace-all" and r["identity_key"] in new],
                "retained_existing_ids":[r["id"] for r in existing["rows"]] if mode=="append" else []}
    return output,byte_edit,disclosure,final


def import_xyn(mdu:Path,source:Path,*,mode,crs,unit,apply=False,expect_sha256=None):
    try:
        _consent(apply,expect_sha256)
        if type(mode) is not str or mode not in ("append","replace-all"):
            fail("mode","Require explicit mode append or replace-all",exit_code=2)
        source=lexical_external(source)
        graph=Inputs(mdu,full=True)
        source,record,raw=source_file(graph,source)
        existing=_named(graph.obs_raw,"existing")
        incoming=_named(raw,"incoming")
        if not incoming["rows"]:
            fail("empty_import","Incoming import must contain at least one named station; clearing an ObsFile is outside this command")
        if len(existing["rows"])+len(incoming["rows"])>MAX_ROWS:
            fail("bound","Combined original and incoming positions exceed batch limit",{"limit":MAX_ROWS})
        output,byte_edit,disclosure,final=_merge(graph,existing,incoming,raw,mode)
        from .observation_transfer_mesh import prepare
        geometry=prepare(graph,crs,unit)
        positions=[geometry.locate(row,dataset) for dataset,parsed in (("existing",existing),("incoming",incoming)) for row in parsed["rows"]]
        proof=geometry.report()
        before={"path":str(graph.obs),"sha256":digest(graph.obs_raw),"bytes":len(graph.obs_raw)}
        after={"path":str(graph.obs),"sha256":digest(output),"bytes":len(output)}
        request={"contract":CONTRACT,"operation":"import","mode":mode,"crs":crs,"unit":unit,
                 "graph":_graph(graph),"source":record,"before":before,"after":after,"byte_edit":byte_edit,
                 "identity_disclosure":disclosure,"geometry":proof,"positions":positions}
        fingerprint=_fingerprint(request,expect_sha256)
        guard=Guard(graph,source,record)
        if not apply or output==graph.obs_raw:
            guard.recheck()
        result={**_base("import",fingerprint,apply),"mdu":str(graph.mdu),"mode":mode,"source":record,
                "before":before,"after":after,"byte_edit":byte_edit,"identity_disclosure":disclosure,
                "station_counts":{"existing":len(existing["rows"]),"incoming":len(incoming["rows"]),"final":len(final["rows"])},
                "positions":positions,"geometry":proof,"record_buffer_check":final["record_buffer_check"],
                "history_name_width_check":final["history_name_width_check"],"bound_inputs":graph.inventory(),
                "non_target_files_written":[],"source_unchanged_at_final_check":True,"no_op":output==graph.obs_raw}
        if apply:
            if output!=graph.obs_raw:
                publish(guard,output)
            result["published_sha256"]=digest(graph.obs.read_bytes())
        return result
    except DfmError:
        raise
    except (OSError,ValueError,TypeError,UnicodeError,OverflowError) as exc:
        fail("import_io","Cannot plan or publish standalone XYN import",str(exc),4 if apply else 3)
