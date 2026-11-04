"""Independent B09 public CLI gate and native preparation; never launches native.

python -m research.workflows.verification.verify_boundary_import --out FRESH
After separately leased coordinator runs:
python -m research.workflows.verification.verify_boundary_import --compare-root PREP/native-preparation --out FRESH
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import traceback
import unittest

from .verify_boundary_import_fixture import ROOT,Fixture,PublicCLI,save,sha,snapshot
from .verify_boundary_import_native import CASES,DECLARATION,compare,prepare


def source_hashes():
    paths=[ROOT/"src/dfm_cli/cli.py",ROOT/"src/dfm_cli/schema.py",*sorted((ROOT/"src/dfm_cli").glob("boundary*.py"))]
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths if p.is_file()}


def retain_stale_mesh(out,cli):
    """Retain actual before/mutated/after input bytes and CLI outcome, pass or fail."""
    fixture=Fixture(out/"stale-mesh-case")
    preview=cli.invoke(*fixture.arguments())
    shutil.copytree(fixture.root,out/"stale-mesh-before")
    before_bc=sha(fixture.bc);mesh=fixture.model/"mesh.nc";before_mesh=sha(mesh)
    mesh.write_bytes(mesh.read_bytes()+b"\nEXTERNAL CHANGE AFTER PREVIEW\n")
    mutated_mesh=sha(mesh)
    code,payload=cli.call(*fixture.arguments(),"--apply","--expect-sha256",preview["input_sha256"])
    shutil.copytree(fixture.root,out/"stale-mesh-after")
    save(out/"stale-mesh-preview.json",preview);save(out/"stale-mesh-apply.json",payload)
    result={"input_sha256":preview["input_sha256"],"mesh_before_sha256":before_mesh,"mesh_after_external_change_sha256":mutated_mesh,
            "bc_before_sha256":before_bc,"bc_after_sha256":sha(fixture.bc),"apply_exit_code":code,
            "stale_refused":payload["ok"] is False and payload.get("error",{}).get("code")=="stale_preview",
            "BC_changed_after_stale_mesh":before_bc!=sha(fixture.bc),"native_launches":0}
    save(out/"stale-mesh-finding.json",result)
    return result


def retain_restored_mtime_changes(out,cli):
    result={}
    for name in ("mesh","weather"):
        root=out/("same-size-"+name);root.mkdir()
        fixture=Fixture(root/"fixture")
        ext=fixture.model/"boundaries.ext"
        ext.write_bytes(ext.read_bytes()+b"[Meteo]\nquantity=rainfall\nforcingFile=weather.tim\n")
        (fixture.model/"weather.tim").write_bytes(b"0 0\n120 0\n")
        target=fixture.model/("mesh.nc" if name=="mesh" else "weather.tim")
        preview=cli.invoke(*fixture.arguments());shutil.copytree(fixture.root,root/"before")
        stat=target.stat();original=target.read_bytes();bc_before=sha(fixture.bc)
        mutated=original.replace(b"0 0",b"0 1",1) if name=="weather" else bytes([original[0]^1])+original[1:]
        target.write_bytes(mutated);os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        code,payload=cli.call(*fixture.arguments(),"--apply","--expect-sha256",preview["input_sha256"])
        shutil.copytree(fixture.root,root/"after")
        save(root/"preview.json",preview);save(root/"apply.json",payload)
        result[name]={"stale_refused":payload["ok"] is False and payload.get("error",{}).get("code")=="stale_preview",
            "same_size":target.stat().st_size==stat.st_size,"restored_mtime":target.stat().st_mtime_ns==stat.st_mtime_ns,
            "bytes_changed":original!=target.read_bytes(),"BC_unchanged":bc_before==sha(fixture.bc),"apply_exit_code":code}
        save(root/"finding.json",result[name])
    return result


class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.contract_evidence=[]
    def addSuccess(self,test):
        super().addSuccess(test)
        if hasattr(test,"verification_evidence"):
            self.contract_evidence.append({"test":str(test),"evidence":test.verification_evidence})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--compare-root",type=Path,help="Read existing leased run outputs only; does not launch")
    args=parser.parse_args(argv);out=args.out.absolute();out.mkdir(parents=True,exist_ok=False)
    before=source_hashes();save(out/"producer-source-hashes.json",before)
    producer_copy=out/"producer-source";producer_copy.mkdir()
    for relative,expected in before.items():
        target=producer_copy/Path(relative).name
        shutil.copyfile(ROOT/relative,target)
        if sha(target)!=expected:
            save(out/"source-copy-race.json",{"path":relative,"before_sha256":expected,"copied_sha256":sha(target)})
            return 2
    code=1;report={"task":"B09-V","state":"preparing","native_GUI_VM_launches":0,"GUI_runtime_parity":"not_claimed; original G/C untested",
                   "contract_basis":"User B09 contract + FM UM2026.02 rev81168 section7.4.8.2 PDF121-125; B03 legacy unchanged",
                   "source_sha256":before,"declaration":DECLARATION}
    frozen=out/"repro-source";frozen.mkdir()
    for path in [*Path(__file__).parent.glob("verify_boundary_import*.py"),*(ROOT/"tests").glob("test_boundary_import*.py")]:
        shutil.copyfile(path,frozen/path.name)
    try:
        if args.compare_root:
            report["comparison"]=compare({name:args.compare_root/(name+"-native") for name in CASES})
            report["state"]="passed_raw_comparator_only";code=0
        else:
            cli=PublicCLI(out/"commands");schema=cli.invoke("schema","inspect")
            available="boundary import" in schema["commands"]
            report["public_import_registered"]=available
            fixture=Fixture(out/"portable-fixture")
            report["portable_fixture"]={"path":str(fixture.root),"mesh":"opaque; no native launch allowed",
                "target_boundary":"east, stored in coast.pli; exact support ids east_0001..east_0004",
                "shared_bc_other_boundary":"west, other.pli; two populated supports in shared.bc",
                "target_initial_states":{"east_0001":"populated","east_0002":"empty block","east_0003":"populated unmatched","east_0004":"absent"},
                "expected_modes":{"replace":"replace1/add2/preserve3/add4","extend":"preserve1/add2/preserve3/add4","overwrite-all":"replace1/add2/clear3/add4"},
                "hashes":{p:__import__("hashlib").sha256(raw).hexdigest() for p,raw in snapshot(fixture.root).items()}}
            if available:
                preview=cli.invoke(*fixture.arguments());save(out/"first-public-preview.json",preview)
                report["stale_mesh_probe"]=retain_stale_mesh(out,cli)
                report["same_size_restored_mtime_probes"]=retain_restored_mtime_changes(out,cli)
            manual=ROOT/"research/manuals/D-Flow_FM_User_Manual.txt"
            if manual.is_file():
                text=manual.read_text(encoding="utf-8");pages=re.split(r"===== PDF PAGE (\d+) =====",text)
                excerpts=[]
                for i in range(1,len(pages),2):
                    if 121<=int(pages[i])<=125:excerpts.append("===== PDF PAGE "+pages[i]+" ====="+pages[i+1])
                (out/"manual-121-125.txt").write_text("\n".join(excerpts),encoding="utf-8")
                pdf=manual.with_suffix(".pdf")
                report["local_manual"]={"pdf_sha256":sha(pdf),"text_sha256":sha(manual),"excerpt_sha256":sha(out/"manual-121-125.txt"),"scope":"document claim, not observed GUI behavior"}
            report["native_preparation"]=prepare(out/"native-preparation",cli,import_available=available)
            if available:
                from .verify_boundary_import_intervention import qualify
                report["BOM_intervention_vs_original_89"]=qualify(out/"native-preparation")
            stream=io.StringIO();suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern="test_boundary_import*.py")
            result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=EvidenceResult).run(suite)
            report["tests"]={"run":result.testsRun,"failures":[(str(t),s) for t,s in result.failures],"errors":[(str(t),s) for t,s in result.errors],
                             "skipped":[(str(t),reason) for t,reason in result.skipped],"expected_failures":len(result.expectedFailures),"successful":result.wasSuccessful()}
            report["tests"]["bounded_contract_evidence"]=result.contract_evidence
            (out/"tests.txt").write_text(stream.getvalue(),encoding="utf-8")
            if not available:report["state"]="blocked_public_boundary_import_not_registered";code=3
            elif result.wasSuccessful():report["state"]="passed_portable_ready_for_coordinator_native_lease";code=0
            else:report["state"]="failed_portable_contract";code=1
    except Exception as exc:
        report.update(state="failed_independent_boundary_import",error=str(exc),traceback=traceback.format_exc())
    finally:
        after=source_hashes();report.update(source_after_sha256=after,source_stable=before==after)
        if before!=after:report["state"]="invalidated_concurrent_product_change";code=2
        save(out/"verification.json",report)
        print(json.dumps({"state":report["state"],"report":str(out/"verification.json"),"native_GUI_VM_launches":0,"source_stable":before==after}))
    return code


if __name__=="__main__":raise SystemExit(main())
