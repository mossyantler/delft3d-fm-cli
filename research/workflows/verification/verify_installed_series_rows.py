"""Compare installed series-rows edits and direct FM runs to the pinned M3 manual controls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile

from research.workflows.replay.boundary_import_modes import UNIT, check, digest, outputs, save, snapshot
from .verify_output_toggle_controls import compare_datasets


DESIGNS = (
    ("two-insertions", "base", [("30","0.20"),("60","-0.06")], []),
    ("delete-first", "two-insertions", [], ["30.00"]),
    ("replace-knot", "two-insertions", [("45","0.14")], ["30"]),
    ("base", "two-insertions", [], ["60","30"]),
)
REVIEWED_CONTROLS = "239486541079f5bc01cbe1fecd4ba19b8423b11653a94f3b33a5e844ca0f080f"


def run(package, controls, out, install=None, slot=None):
    check((install is None) == (slot is None), "Specify both install and assigned slot for native comparisons")
    check(not any(out.is_relative_to(p) or p.is_relative_to(out) for p in (package, controls)), "Output overlaps inputs")
    original = controls / "verification.json"
    check(digest(original) == REVIEWED_CONTROLS, "Wrong or changed manual controls")
    oracle = json.loads(original.read_bytes())["cases"]
    pkg = json.loads((package / "verification.json").read_bytes())
    wheel = package / "wheels" / pkg["wheel"]
    check(pkg["state"] == "passed" and digest(wheel) == pkg["wheel_sha256"], "Unverified wheel")
    with ZipFile(wheel) as z:
        for name in z.namelist():
            if name.startswith("dfm_cli/") and not name.endswith("/"):
                check((package / "venv/Lib/site-packages" / name).read_bytes() == z.read(name), f"Installed package differs: {name}")
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    env.pop("PYTHONPATH", None)
    report = {"state":"incomplete", "wheel_sha256":pkg["wheel_sha256"], "manual_receipt":REVIEWED_CONTROLS,
              "runner_sha256":digest(Path(__file__)), "native_slot":slot, "cases":{}, "calls":[]}

    def call(label, *args):
        argv = list(map(str, (package / "venv/Scripts/dfm.exe", *args)))
        proc = subprocess.run(argv, cwd=out, env=env, capture_output=True, timeout=150)
        (out / (label+".stdout.json")).write_bytes(proc.stdout)
        (out / (label+".stderr.txt")).write_bytes(proc.stderr)
        report["calls"].append({"argv":argv,"code":proc.returncode})
        response = json.loads(proc.stdout)
        check(proc.returncode == 0 and response.get("protocol_version") == 2 and response.get("ok") is True,
              f"{label}: {response.get('error')}")
        return response["result"]

    try:
        check("boundary series-rows" in call("schema", "schema", "inspect")["commands"], "Command not discoverable")
        for name, source, insert, delete in DESIGNS:
            # Subsequent edits deliberately start from the result of the first public apply.
            src = controls / "cases/base" if source == "base" else out / "cases" / source
            check(snapshot(src) == snapshot(controls / "cases" / source), "Public starting point differs from manual graph")
            case = out / "cases" / name
            shutil.copytree(src, case)
            before = snapshot(case)
            request = out / (name + "-request.json")
            save(request, {"time_unit":UNIT, "value_unit":"m", "insert":[dict(time=t,value=v) for t,v in insert],"delete":delete})
            argv = ("boundary","series-rows",case/"model.mdu","--point","east_0001","--rows",request)
            preview = call(name+"-preview", *argv)
            check(preview["applied"] is False and snapshot(case) == before, "Preview mutated inputs")
            applied = call(name+"-apply", *argv, "--apply","--expect-sha256",preview["input_sha256"])
            edited = snapshot(case)
            check(applied["applied"] is True and preview["receipt_sha256"] == applied["receipt_sha256"] and
                  edited == snapshot(controls / "cases" / name) and edited["boundaries.bc"] == oracle[name]["BC"]
                  and edited["boundaries.bc"] == applied["receipt"]["after_sha256"], "Public edit differs from manual result")
            check({k for k,h in before.items() if edited.get(k) != h} == {"boundaries.bc"}, "Wrong changed input")
            row = report["cases"][name] = {"source":source,"BC_sha256":edited["boundaries.bc"],"all_nine_inputs_exact":True,
                                          "input_sha256":preview["input_sha256"],"receipt_sha256":applied["receipt_sha256"]}
            if install is None:
                continue
            root = Path(__file__).resolve().parents[3]
            lease = json.loads((root / "research/experiments/roadmap-coordinator-20261104/dispatch.json").read_bytes())["native_slot"]
            check((lease["owner"],lease["sequence"]) == ("B03-ROWS-PUBLIC-G",slot), "Wrong native slot")
            folder, hand = out/("run-"+name), controls/("run-"+name)
            result = call(name+"-run","run","start",case/"model.mdu","--route","direct","--install",install,"--out",folder,"--timeout",60)
            m = json.loads((folder/"manifest.json").read_bytes())
            ref = json.loads((hand/"manifest.json").read_bytes())
            check(digest(hand/"manifest.json") == oracle[name]["manifest"] and m["executable_sha256"] == ref["executable_sha256"]
                  and m["returncode"] == 0 and m["state"] == result["state"] == "completed", "Engine/exit mismatch")
            check(all(m["ownership"]["normal_exit"].get(k) is True for k in ("job_empty","root_exit_confirmed","all_owned_members_exit_confirmed")), "Ownership unverified")
            files, mean = outputs(folder)
            expected, manual_mean = outputs(hand)
            counts = {}
            for left, right in zip(expected, files, strict=True):
                check(left.name == right.name and digest(left) == oracle[name]["four_output_sha256"][left.name], "Wrong reference output")
                diff = compare_datasets(left,right)
                check(diff["shared_exact"], f"{name}/{left.name}: {diff['differences'][:1]}")
                counts[left.name] = len(diff["variables"])
            check(mean == manual_mean and snapshot(case) == edited, "Changed inputs or changed east water level")
            row.update(variables_by_file=counts,exact_variables=sum(counts.values()),final_seconds=120,
                       final_restart=True,closed_job=True,east_4_final_mean_m=mean,manifest_sha256=digest(folder/"manifest.json"))
        report["state"] = "public_native_passed" if install else "installed_edits_passed_no_native"
    except Exception as exc:
        report["failure"] = {"type":type(exc).__name__,"message":str(exc)}
        raise
    finally:
        save(out / "verification.json",report)
    print(report["state"], len(report["cases"]), "cases")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package","controls","out","install"):
        parser.add_argument("--"+name,required=name!="install",type=lambda p:Path(p).resolve())
    parser.add_argument("--slot",type=int)
    run(**vars(parser.parse_args()))
