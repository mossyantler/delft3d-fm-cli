"""Read-only pump inspect registry. No reverse/write API or publisher import."""
from pathlib import Path
import hashlib
import json

from .common import DfmError
from .pump_graph import PumpInputs
from .pump_text import fail,identifier,protected,summary,row_evidence
from .pump_contract import CONTRACT,LIMITS,SOURCE,NATIVE_LIMIT,contract


def register(groups):
    commands=groups.add_parser("pump",help="Read-only pump input rows/capacity/polarity; no hydraulic reversal capability").add_subparsers(dest="action",required=True)
    return register_inspect(commands)


def register_inspect(commands):
    p=commands.add_parser("inspect",help="Describe modern scalar-capacity XY pump inputs; no native/GUI or hydraulic outcome prediction")
    p.add_argument("mdu",type=Path)
    p.add_argument("--id",help="Exact pump structure ID, not the PLI label")
    return commands


def execute(args):
    if args.action!="inspect":fail("usage","Only read-only pump inspect is registered; no mutation command",exit_code=2)
    return inspect(args.mdu,args.id)


def inspect(mdu:Path,id=None):
    try:
        if id is not None:identifier(id,request=True)
        graph=PumpInputs(mdu)
        blocks=[graph.select(id)] if id is not None else graph.pumps()
        pumps=[];total_rows=0
        for block in blocks:
            report,pli,raw,target,role=graph.describe(block)
            if not report["recognized_scalar_profile"]:
                fail("inspect_scope","Pump lies outside the bounded unambiguous read-only profile",report["profile_notes"])
            total_rows+=len(pli["rows"])
            if total_rows>10000:fail("bound","Total returned XY rows exceed10000; inspect one --id")
            report["capacity_raw"]=block["fields"]["capacity"].value
            report["capacity"]["interpretation"]="Declared input scalar only; realized total discharge is not inferred"
            value=report["capacity"]["binary64"]
            report["declared_polarity"]={"orientation":report["orientation_raw"],"capacity_sign":"positive" if value>0 else "negative" if value<0 else "zero",
                                         "basis":"Input tokens only; no hydraulic direction assertion"}
            report["properties"]=protected(block)
            report["linked_files"]={"structure":{"path":str(block["path"]),"sha256":graph.files[block["path"]]["sha256"]},
                                    "location":{"path":str(target),"sha256":graph.files[target]["sha256"],"bytes":len(raw)}}
            report["PLI"]={"label_used_for_structure_selection":False,**summary(pli),**row_evidence(pli)}
            pumps.append(report)
        graph.recheck()
        binding={"contract":CONTRACT,"mdu":str(graph.mdu),"id":id,"files":graph.inventory(),"references":graph.references,"outputs":graph.output_paths}
        fingerprint=hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
        return {"contract":CONTRACT,"action":"inspect","mdu":str(graph.mdu),"id":id,"read_only":True,"write_commands":[],"input_sha256":fingerprint,
            "pumps":pumps,"selected":pumps[0] if id is not None else None,"input_files":graph.inventory(),"references":graph.references,
            "output_destinations_not_written":graph.output_paths,"files_written":[],
            "hydraulic_effect":"not_predicted_or_verified","hydraulic_use":"unqualified","native_validation":"not_performed","native_gate":NATIVE_LIMIT["gate"],
            "gui_parity":"not_verified","native_execution":"not_performed","native_limit":NATIVE_LIMIT,"source_basis":SOURCE,"limits":LIMITS,
            "fingerprint_scope":"read-only input snapshot; NOT consent for a write command"}
    except DfmError:
        raise
    except (OSError,UnicodeError,ValueError,TypeError,OverflowError,IndexError,KeyError) as exc:
        fail("io","Cannot establish bounded read-only pump input inventory",str(exc))
