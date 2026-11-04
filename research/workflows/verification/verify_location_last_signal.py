"""Retire the LAST physical BC blocks; check that FM can still read the preceding harmonic table."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from research.workflows.replay.boundary_import_modes import check, public, outputs
from research.workflows.replay.boundary_location_controls import inventory
from .verify_location_import_native import ROOT, save, sha
from .verify_serial_experiment import dataset_comparison


def replay(base, out, install, number, contrast=False):
    slot = json.loads((ROOT/"research/experiments/roadmap-coordinator-20261104/dispatch.json").read_bytes())["native_slot"]
    check((slot["owner"], slot["sequence"]) == ("B04-order-G", number), "Wrong native lease")
    before = inventory(base)
    check(before.get("boundaries.bc") == "e7c6b2b80a976eea870152251c7146c0a8ac2ffbd82257c038b461441108e17a"
          and not out.is_relative_to(base) and not base.is_relative_to(out), "Wrong or overlapping source")
    out.mkdir(parents=True, exist_ok=False)
    if contrast:
        original = base
        base = out/"unequal-west-input"; shutil.copytree(original,base)
        p = base/"boundaries.bc"; head, tail = p.read_bytes().split(b"Name = west_0002")
        check(tail.count(b"10 0.05 90")==1, "Wrong west_0002 signal")
        p.write_bytes(head+b"Name = west_0002"+tail.replace(b"10 0.05 90",b"10 0.25 90",1))
        check(inventory(original)==before,"Changed historical input")
        before=inventory(base)
    source = out/"boundary_east.pli"; source.write_bytes(b"east\n2 2\n500120 5700001\n500120 5700039\n")
    hand = out/"manual"; shutil.copytree(base, hand)
    shutil.copy2(source, hand/source.name)
    for file, marker, token, count in (("boundaries.bc", b"[Forcing]", b"Name = east_", 2),
                                       ("boundaries.ext", b"[Boundary]", b"locationFile = boundary_east.pli", 1)):
        p = hand/file
        head,*rows = p.read_bytes().split(marker)
        check(len(rows)==2*count and all(token in row for row in rows[-count:]), "Expected target last")
        p.write_bytes(head + b"".join(marker+row for row in rows[:-count]))
    cmd = ("boundary","location-import",base/"model.mdu","--coordinates","as-is","--source",source,"--out",out/"candidate")
    pre = public(out,"preview",*cmd)
    public(out,"apply",*cmd,"--apply","--expect-sha256",pre["input_sha256"])
    result = {}
    names=["manual","candidate"]
    if contrast:
        # Isolate the retired BC bytes from all differences in geometry, EXT and folder provenance.
        repaired=out/"candidate-hand-BC"; shutil.copytree(out/"candidate",repaired)
        shutil.copyfile(hand/"boundaries.bc",repaired/"boundaries.bc"); names.append("candidate-hand-BC")
    for name in names:
        run = out/("run-"+name)
        p = subprocess.run([sys.executable,"-B","-m","dfm_cli","run","start",str(out/name/"model.mdu"),"--route",
                            "direct","--install",str(install),"--timeout","60","--out",str(run)],capture_output=True,timeout=120)
        (out/(name+".json")).write_bytes(p.stdout); (out/(name+".stderr")).write_bytes(p.stderr)
        m = json.loads((run/"manifest.json").read_bytes()); obs=m["ownership"]["normal_exit"]
        check(obs["root_exit_confirmed"] and obs["job_empty"], "Lost Job evidence")
        result[name] = {"engine_returncode":m["returncode"],"cli_exit":p.returncode,"state":m["state"],
                        "job_empty":True,"manifest_sha256":sha(run/"manifest.json")}
    check(result["manual"]["state"]=="completed" and inventory(base)==before,"Invalid hand control")
    report={"runs":result,"expected_valid":True,"mode":"as-is","source_graph_sha256":sha(ROOT/"src/dfm_cli/boundary_locations_graph.py")}
    if result["candidate"]["state"]=="completed":
        a,_=outputs(out/"run-manual"); b,_=outputs(out/"run-candidate")
        try:
            pairs=[dataset_comparison(x,y) for x,y in zip(a,b,strict=True)]
            check(all(not d["variable_attribute_differences"] for d in pairs),"Metadata mismatch")
            save(out/"array-comparison.json",pairs)
            report["equal_variables"]=sum(d["variable_count"] for d in pairs)
        except AssertionError as exc:
            report["first_raw_mismatch"]=str(exc)
        from netCDF4 import Dataset
        import numpy as np
        report["max_station_delta_vs_manual_m"]={}
        for name in names[1:]:
            with Dataset(out/"run-manual/model/output/model_his.nc") as x, Dataset(out/("run-"+name)/"model/output/model_his.nc") as y:
                report["max_station_delta_vs_manual_m"][name]=float(np.max(np.abs(x["waterlevel"][:]-y["waterlevel"][:])))
    report["passed"]=report.get("equal_variables")==159
    save(out/"verification.json",report); return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for n in ("baseline","out","install"): parser.add_argument("--"+n,type=Path,required=True)
    parser.add_argument("--native-slot",type=int,required=True)
    parser.add_argument("--contrast",action="store_true",help="Give retained west support points different forcing; isolate BC bytes in a third run")
    a=parser.parse_args()
    raise SystemExit(0 if replay(a.baseline.resolve(),a.out.resolve(),a.install,a.native_slot,a.contrast) else 1)
