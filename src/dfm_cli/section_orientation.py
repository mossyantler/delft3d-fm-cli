"""Inspect/reverse raw observation-section orientation, never solver results."""
from pathlib import Path
import re

from .boundary_import import _digest, _hash, _patch_receipt
from .boundary_support_write import replace
from .common import DfmError
from .section_orientation_contract import CONTRACT, LIMITS, contract
from .section_orientation_graph import SectionInputs
from .section_orientation_text import parse, select, summary, row_evidence, reverse as reverse_records, fail


def register(groups):
    group=groups.add_parser("section",help="Inspect/reverse existing CrsFile observation-section direction")
    actions=group.add_subparsers(dest="action",required=True)
    p=actions.add_parser("inspect",help="Inventory all sections or select one exact full ID")
    p.add_argument("mdu",type=Path);p.add_argument("--id")
    p=actions.add_parser("reverse",help="Preview/apply selected full XY record-body reversal; preserve trivia and other inputs")
    p.add_argument("mdu",type=Path);p.add_argument("--id",required=True)
    p.add_argument("--apply",action="store_true");p.add_argument("--expect-sha256",help="input_sha256 from this exact reverse preview")
    return actions


def execute(args):
    if args.action=="inspect":return inspect(args.mdu,args.id)
    if args.action=="reverse":return reverse(args.mdu,args.id,args.apply,args.expect_sha256)
    raise DfmError("usage","Unknown section action",2)


def inspect(mdu,id=None):
    return _operation(mdu,id,"inspect",False,None)


def reverse(mdu,id,apply=False,expect_sha256=None):
    return _operation(mdu,id,"reverse",apply,expect_sha256)


def _operation(mdu,id,action,apply,expected):
    if type(apply) is not bool:raise DfmError("usage","apply must be boolean",2)
    if apply and expected is None:raise DfmError("expected_hash_required","--apply requires --expect-sha256 from the exact reverse preview",2)
    if expected is not None and (type(expected) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}",expected)):
        raise DfmError("usage","Expected a 64-digit hexadecimal preview hash",2)
    try:
        graph=SectionInputs(mdu);original=graph.target_raw;before=parse(original)
        selected=select(before,id) if id is not None else None
        patches=[];changed=original
        if action=="reverse":
            if selected is None:fail("id","Reverse needs an exact section ID",exit_code=2)
            changed,patches=reverse_records(original,selected)
            after=parse(changed);written=select(after,id)
            if [s["id"] for s in before]!=[s["id"] for s in after]:fail("preservation","Section identities/order changed",exit_code=4)
            if [r["body"] for r in written["rows"]]!=[r["body"] for r in reversed(selected["rows"])]:
                fail("preservation","Result is not exact selected row-body reversal",exit_code=4)
            for old,new in zip(before,after):
                if old["id"]!=id and [r["body"] for r in old["rows"]]!=[r["body"] for r in new["rows"]]:
                    fail("preservation","An unselected section changed",old["id"],4)
        else:after=before;written=selected
        spans=_patch_receipt(patches)
        request={"contract":CONTRACT,"action":action,"mdu":str(graph.mdu),"id":id,"target":str(graph.target)}
        binding={"request":request,"files":graph.inventory(),"references":graph.references,"output_destinations":graph.output_paths,
                 "before_sha256":_hash(original),"after_sha256":_hash(changed),"operation_spans_sha256":spans["patches_sha256"]}
        fingerprint=_digest(binding)
        if expected is not None and fingerprint!=expected.lower():raise DfmError("stale_preview","Section request, input graph/roles or exact target plan changed",4)
        graph.coherence()
        receipt={"patch_offsets_snapshot":"before_edit; patch spans refer to original CrsFile even after apply","request":request,
                 "before_sha256":_hash(original),"after_sha256":_hash(changed),
                 "selected_before":{"snapshot":"before_edit",**summary(selected)} if selected else None,
                 "selected_after":{"snapshot":"intended_after",**summary(written)} if written and action=="reverse" else None,
                 "mapping":("original selected record slot i receives body from original slot N-1-i; original newline/trivia chunks retained"
                            if action=="reverse" else "inspect only; no edit or permutation"),**spans}
        result={"contract":CONTRACT,"action":action,"applied":apply,"changed":changed!=original,"input_sha256":fingerprint,
                "mdu":str(graph.mdu),"target":{"role":"output/crsfile","path":str(graph.target)},
                "sections":[summary(section) for section in before],"sections_snapshot":"before_edit",
                "selected_rows":row_evidence(selected) if selected else None,
                "receipt":receipt,"receipt_sha256":_digest(receipt),"files_snapshot":"before_edit","files":graph.inventory(),
                "references":graph.references,"output_destinations_not_inputs":graph.output_paths,
                "signed_quantity_meaning":contract()["signed_quantity_meaning"],
                "validation":{"supported_graph_and_PLI_preservation":"passed","native_execution":"not_performed","scientific_validation":"not_performed"},
                "CRS_units_datum":"not_inferred_or_modified","limitations":LIMITS}
        if apply:
            if changed==original:graph.recheck()
            else:
                try:replace(graph,graph.target,changed)
                except DfmError as exc:raise DfmError("section_publication","CrsFile publication failed; retained cleanup evidence is attached",exc.exit_code,exc.details) from exc
        return result
    except DfmError as exc:
        if expected is not None and exc.exit_code in (2,3):
            raise DfmError("stale_preview","Current graph/section cannot revalidate the supplied preview; no publication",4,{"cause":exc.code,"message":str(exc)}) from exc
        raise
    except (OSError,ValueError,TypeError) as exc:
        raise DfmError("stale_preview" if expected is not None else "section_io","Cannot establish section input graph/plan",4 if expected is not None else 3,str(exc)) from exc
