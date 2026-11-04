"""Allocated-slot-only 3D-V pair, public CLI and independent raw-array oracle.

python -m research.workflows.verification.verify_layers_native --out NEW
    --install SUITE --native-slot-granted

At most two sequential 20-second native trials are launched: bottom-weighted
west-boundary salinity perturbation and an otherwise identical control. Input
read-back, engine consumption, raw layered geometry/profiles, shared CF schedule,
final restart and public layers verify are reported separately. No product
comparator or product verifier supplies the independent numerical oracle.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback

from .verify_layers import (ROOT, TOLERANCES, check_bundle, check_outputs, cf_times,
                            fingerprints, ordered, require, sha, specification,
                            write_json)


MIN_BOUNDARY_RESPONSE_PPT = 10*TOLERANCES["salinity_ppt_atol"]


class PublicCLI:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir()
        self.calls = []

    def invoke(self, *arguments, expected=0):
        n = len(self.calls)+1
        argv = [sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)]
        stdout, stderr = [self.root / f"{n:02d}.{suffix}" for suffix in ("stdout.json", "stderr.jsonl")]
        entry = {"argv": argv, "stdout": str(stdout), "stderr": str(stderr)}
        self.calls.append(entry)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=75)
            stdout.write_bytes(result.stdout)
            stderr.write_bytes(result.stderr)
            entry["returncode"] = result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout.write_bytes(exc.stdout or b"")
            stderr.write_bytes(exc.stderr or b"")
            entry["controller_timeout"] = True
            raise
        payload = json.loads(result.stdout)
        require(payload.get("protocol_version") == 2, "Unexpected public JSON protocol")
        if expected is not None:
            require(result.returncode == expected and payload["ok"] == (expected == 0), f"Public command failed: {argv}: {payload}")
        return result.returncode, payload


def response(perturbed, control, spec):
    from netCDF4 import Dataset
    import numpy as np

    a_path, b_path = [Path(folder) / "model/output/model_map.nc" for folder in (perturbed, control)]
    require(cf_times(a_path)["iso"] == cf_times(b_path)["iso"], "Control clocks differ")
    with Dataset(a_path) as a, Dataset(b_path) as b:
        sal = a["mesh2d_sa1"]
        etadims = a["mesh2d_s1"].dimensions
        face = next(d for d in etadims if d != "time")
        layer = next(d for d in sal.dimensions if d not in ("time", face))
        x, y = ordered(a["mesh2d_sa1"], ("time", face, layer), {"ppt", "1e-3"}), ordered(b["mesh2d_sa1"], ("time", face, layer), {"ppt", "1e-3"})
        np.testing.assert_allclose(x[0], y[0], rtol=0, atol=TOLERANCES["salinity_ppt_atol"])
        delta = x-y
        per_layer = np.max(abs(delta[1:]), axis=(0, 1))
        maximum = float(np.max(abs(delta[1:])))
        require(maximum > MIN_BOUNDARY_RESPONSE_PPT, "No predeclared significant salinity response to the sole boundary perturbation")
        from .verify_layers import containing_face
        west = next(o for o in spec["observations"] if o["id"] == "near_west")
        index = containing_face(a, (west["x_m"], west["y_m"]))
        return {"passed": True, "sole_input_changed": "boundaries.bc; west t3D endpoint salinity values only",
                "minimum_response_predeclared_ppt": MIN_BOUNDARY_RESPONSE_PPT, "maximum_absolute_salinity_change_ppt": maximum,
                "per_layer_maximum_change_ppt": per_layer.tolist(), "near_west_final_change_ppt": delta[-1, index].tolist(),
                "scope": "Controlled native response establishes boundary consumption; not an analytic transport/calibration solution"}


def final_restart_check(run, spec):
    from netCDF4 import Dataset
    import numpy as np

    paths = list((run / "model/output").glob("*_rst.nc"))
    require(paths, "No final native restart dataset")
    final = max(paths, key=lambda p: cf_times(p)["seconds"][-1])
    axis = cf_times(final)
    stop = datetime.fromisoformat(spec["clock"]["stop"].replace("Z", "+00:00")).replace(tzinfo=None)
    expected = (stop-datetime(2001, 1, 1)).total_seconds()
    require(len(axis["seconds"]) == 1 and abs(axis["seconds"][0]-expected) < 1e-9, "Native final restart has the wrong actual CF time")
    with Dataset(final) as ds:
        candidates = [v for v in ds.variables.values() if getattr(v, "standard_name", "") == "sea_water_salinity" or v.name.casefold() == "salinity"]
        require(len(candidates) == 1, "Missing/ambiguous final restart salinity")
        v = candidates[0]
        require(v.ndim == 3 and v.units in {"ppt", "1e-3"}, "Restart is not genuinely layered salinity")
        k = len(spec["layers"]["fractions"])
        layer = [d for d in v.dimensions if d != "time" and "lay" in d.casefold() and len(ds.dimensions[d]) == k]
        require(len(layer) == 1, "Final restart lacks the requested layer dimension")
        values = np.ma.asarray(v[:])
        require(not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(), "Final layered state is masked/nonfinite")
        return {"path": str(final), "sha256": sha(final), "actual_last_datetime": axis["iso"][-1],
                "salinity_variable": v.name, "dimensions": list(v.dimensions), "shape": list(v.shape),
                "layer_count": k, "salinity_range_ppt": [float(values.min()), float(values.max())]}


def runtime_settings(path, spec):
    from .verify_layers import blocks
    text = path.read_text(encoding="utf-8", errors="replace")
    required = {"Kmx": len(spec["layers"]["fractions"]), "LayerType": 1, "Salinity": 1}
    result = {}
    for key, value in required.items():
        matches = re.findall(rf"(?mi)^\s*{key}\s*=\s*([^#\r\n]+)", text)
        require(len(matches) == 1 and float(matches[0].strip()) == value, f"Native effective setting {key} differs")
        result[key] = value
    return {"path": str(path), "sha256": sha(path), "effective_settings": result}


def replay(out, install, cli, report):
    baseline = specification()
    # Predeclared bottom-weighted profile perturbation. Time-zero profiles and
    # water levels remain identical between the actual two native cases.
    baseline["boundaries"][0]["salinity"]["values"][-1] = [20, 34, 22, 5]
    control = copy.deepcopy(baseline)
    control["boundaries"][0]["salinity"]["values"][-1] = [20, 30, 20, 5]
    models = {}
    for name, spec in (("perturbed", baseline), ("control", control)):
        path, folder = out / (name+".json"), out / (name+"-inputs")
        write_json(path, spec)
        cli.invoke("layers", "create", path, "--out", folder)
        _, inspected = cli.invoke("layers", "inspect", folder / "model.mdu")
        report.setdefault("input_readback", {})[name] = check_bundle(folder, spec)
        models[name] = {"spec": spec, "folder": folder, "report": inspected["result"], "sha256": fingerprints(folder)}
    inventories = [{f["relative_path"]: f["sha256"] for f in models[name]["report"]["files"]} for name in ("perturbed", "control")]
    changed = [name for name in inventories[0] if inventories[0][name] != inventories[1][name]]
    require(set(inventories[0]) == set(inventories[1]) and changed == ["boundaries.bc"], f"Control also changes non-target engine inputs: {changed}")
    report["engine_input_difference"] = changed
    report["runs"] = {}
    for name in ("perturbed", "control"):
        item, run = models[name], out / (name+"-run")
        code, payload = cli.invoke("run", "start", item["folder"] / "model.mdu", "--out", run,
                                   "--install", install, "--profile", "layers", "--route", "direct",
                                   "--timeout", 45, "--progress", expected=None)
        report["native_started"] = True
        entry = {"run": str(run), "returncode": code, "result": payload,
                 "source_inputs_unchanged": fingerprints(item["folder"]) == item["sha256"]}
        report["runs"][name] = entry
        manifest_path = run / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            entry["manifest"] = {"path": str(manifest_path), "sha256": sha(manifest_path), "record": manifest}
        output = run / "model/output"
        if (output / "model_map.nc").is_file() and (output / "model_his.nc").is_file():
            try:
                entry["raw_oracle"] = check_outputs(output / "model_map.nc", output / "model_his.nc", item["spec"])
                entry["raw_oracle_passed"] = True
                entry["runtime_settings"] = runtime_settings(output / "model.dia", item["spec"])
                entry["final_restart"] = final_restart_check(run, item["spec"])
            except Exception as exc:
                entry.update(raw_oracle_passed=False, raw_oracle_error=str(exc), raw_oracle_traceback=traceback.format_exc())
        verify_code, verify_payload = cli.invoke("layers", "verify", run / "model/model.mdu", expected=None)
        entry["public_layers_verify"] = {"returncode": verify_code, "payload": verify_payload}
        require(entry["source_inputs_unchanged"], "Native run changed original authored inputs")
        require(code == verify_code == 0 and entry.get("raw_oracle_passed") is True,
                f"{name} native/public/raw verification failed; preserve this trial for Bacon")
        require(manifest["state"] == "completed" and manifest["ownership"]["final_job_pids"] == [], "Native ownership/completion not confirmed")
    report["boundary_consumption"] = response(out / "perturbed-run", out / "control-run", baseline)
    report["scope"] = "Two 20-second, 12-cell, three unequal sigma-layer salinity runs; raw geometry/initial profiles and controlled boundary response. No broad 3D/scientific approval."


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--native-slot-granted", action="store_true", required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "failed", "native_started": False, "tolerances_predeclared": TOLERANCES,
              "minimum_boundary_response_ppt": MIN_BOUNDARY_RESPONSE_PPT, "max_native_trials": 2,
              "verifier_sha256": sha(Path(__file__)),
              "oracle_sha256": sha(Path(__file__).with_name("verify_layers.py")),
              "implementation_sha256": {str(p): sha(p) for p in sorted((ROOT / "src/dfm_cli").glob("layers*.py"))}}
    write_json(out / "predeclared.json", report)
    cli = PublicCLI(out / "commands")
    code = 1
    try:
        replay(out, args.install, cli, report)
        report["status"] = "passed_scoped_3d_native_and_boundary_control"
        code = 0
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report["invocations"] = cli.calls
        report["artifact_sha256"] = fingerprints(out)
        write_json(out / "verification.json", report)
        print(json.dumps({"status": report["status"], "native_started": report["native_started"],
                          "verification": str(out / "verification.json"), "error": report.get("error")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
