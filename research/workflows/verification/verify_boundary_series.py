"""B03 independent public-CLI byte/physics gate; no engine without an explicit slot.

Only this verifier reads its numeric oracle. Product parsers/results are never
imported. Native cases: zero control, selected-point head, future-only no-effect.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[3]
POINT = "east_0001"
TIME_UNIT = "seconds since 2026-01-01 00:00:00 +00:00"
DECLARATION = {
    "duration_seconds": 120, "output_seconds": 10, "bed_elevation_m": -3,
    "crs": "EPSG:32631", "selected_point": POINT,
    "near_boundary_station": {"id": "near_east", "x": 500115, "y": 5700005},
    "control": "all support points zero at 0,20,120,240 seconds",
    "changed": "east_0001 only: value20=value120=0.12m; initial0 and future240 stay0",
    "future_noeffect": "east_0001 only: value240=0.12m; 0,20,120 remain0",
    "maximum_launches": 3, "sequential": True, "attempts_per_case": 1,
    "history_map_cell_atol_m": 1e-6, "rest_and_future_noeffect_atol_m": 1e-6,
    "late_effect_window_seconds": [90, 120], "minimum_mean_near_boundary_effect_m": .01,
    "near_boundary_effect_upper_bound_m": .15,
    "restart_map_final_atol_m": 1e-6,
    "reason": "positive prescribed head must raise adjacent wet-cell elevation; future-only linear segment begins at120s and cannot affect earlier times",
    "limits": "bounded response/sign/isolation check; no calibrated flow prediction, flux closure or GUI parity",
    "source": "D-Flow FM UM2026.02 C.5 pp424ff (time+waterlevelbnd/m, linear); F.2.2 (history stores containing-cell value)",
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()}


def fingerprints(folder):
    return {k: hashlib.sha256(v).hexdigest() for k, v in snapshot(folder).items()}


def walk(value):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def series_rows(raw, point=POINT):
    """Own byte-offset scanner, retaining all comments, CRLF/BOM and other blocks."""
    blocks, block, offset = [], None, 0
    for number, original in enumerate(raw.splitlines(keepends=True), 1):
        line = original
        bom = 3 if number == 1 and line.startswith(b"\xef\xbb\xbf") else 0
        line = line[bom:]
        code = re.split(rb"[#;]", line, maxsplit=1)[0]
        if code.strip().startswith(b"["):
            block = {"fields": [], "rows": [], "section": code.strip().lower()}
            blocks.append(block)
        elif block is not None and code.strip():
            if b"=" in code:
                key, value = code.split(b"=", 1)
                block["fields"].append((key.strip().decode().casefold(), value.strip().decode()))
            else:
                tokens = list(re.finditer(rb"\S+", code))
                block["rows"].append({"tokens": [t[0].decode() for t in tokens], "line": number,
                                      "spans": [(offset + bom + t.start(), offset + bom + t.end()) for t in tokens]})
        offset += len(original)
    selected = [b for b in blocks if any(k == "name" and v.casefold() == point.casefold() for k, v in b["fields"])]
    require(len(selected) == 1, "Independent reader: ambiguous/missing selected point")
    b = selected[0]
    require([v for k, v in b["fields"] if k == "name"] == [point], "Case/exact point identity mismatch")
    require([v.casefold() for k, v in b["fields"] if k == "function"] == ["timeseries"], "Expected timeseries")
    pairs = [(k, v) for k, v in b["fields"] if k in ("quantity", "unit")]
    require(pairs == [("quantity", "time"), ("unit", TIME_UNIT), ("quantity", "waterlevelbnd"), ("unit", "m")], "Independent BC units/columns differ")
    previous = None
    for row in b["rows"]:
        require(len(row["tokens"]) == 2, "Independent BC row width differs")
        t, value = map(Decimal, row["tokens"])
        require(t.is_finite() and value.is_finite(), "Nonfinite BC axis/value")
        require(previous is None or float(t) > float(previous), "Duplicate/ambiguous/nonmonotonic BC axis")
        previous = t
    return b["rows"]


def expected_splice(raw, changes, point=POINT):
    rows = series_rows(raw, point)
    replacements = []
    seen = set()
    for change in changes:
        t = Decimal(change["time"])
        require(t not in seen, "Duplicate requested numeric time")
        seen.add(t)
        matching = [row for row in rows if Decimal(row["tokens"][0]) == t]
        require(len(matching) == 1, "Requested time is absent or ambiguous")
        left, right = matching[0]["spans"][1]
        replacements.append((left, right, change["value"].encode("ascii")))
    for left, right, value in sorted(replacements, reverse=True):
        raw = raw[:left] + value + raw[right:]
    return raw


class PublicCLI:
    def __init__(self, folder):
        self.folder = Path(folder); self.folder.mkdir(exist_ok=False)
        self.calls = []

    def invoke(self, *arguments, success=True):
        argv = [sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)]
        run = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=180)
        number = len(self.calls) + 1
        (self.folder / f"{number:03d}.stdout.json").write_bytes(run.stdout)
        (self.folder / f"{number:03d}.stderr.txt").write_bytes(run.stderr)
        entry = {"argv": argv, "returncode": run.returncode, "stdout": f"{number:03d}.stdout.json", "stderr": f"{number:03d}.stderr.txt"}
        self.calls.append(entry); save(self.folder / "invocations.json", self.calls)
        value = json.loads(run.stdout)
        require(value.get("protocol_version") == 2 and value.get("ok") == success and (run.returncode == 0) == success,
                "Public command result differs: " + str(value))
        if not success:
            require(value["error"]["code"] not in ("usage", "internal_error"), "Not a semantic rejection: " + str(value))
        return value.get("result", value.get("error"))


def authored_channel(root, cli):
    source = root / "authored-source"; source.mkdir()
    mesh_spec = source / "mesh.json"
    shutil.copyfile(ROOT / "examples/channel/mesh.json", mesh_spec)
    mesh_out = source / "public-mesh"
    preview = cli.invoke("mesh", "build", mesh_spec, "--out", mesh_out)
    require(not mesh_out.exists(), "Mesh preview wrote output")
    mesh = cli.invoke("mesh", "build", mesh_spec, "--out", mesh_out, "--apply", "--expect-sha256", preview["input_sha256"])
    spec = json.loads((ROOT / "examples/channel/model.json").read_text())
    spec["name"] = "b03_channel"
    spec["mesh"]["path"] = str(Path(mesh["net_file"]).relative_to(source).as_posix())
    for boundary in spec["boundaries"]:
        boundary["signal"] = {"function": "timeseries", "time_unit": "s", "time_origin": spec["clock"]["start"],
                              "values": [[0, 0], [20, 0], [120, 0], [240, 0]]}
    spec["observations"] = [DECLARATION["near_boundary_station"], {"id": "near_west", "x": 500005, "y": 5700005}]
    specpath = source / "model.json"; save(specpath, spec)
    before = fingerprints(source)
    cli.invoke("model", "create", specpath, "--out", root / "authored-model")
    require(fingerprints(source) == before, "Model creation changed source spec/mesh")
    return root / "authored-model"


def apply_checked(cli, folder, specpath, changes):
    before = snapshot(folder)
    bc = folder / "boundaries.bc"
    expected = expected_splice(bc.read_bytes(), changes)
    save(specpath, {"time_unit": TIME_UNIT, "value_unit": "m", "changes": changes})
    args = ("boundary", "series-set", folder / "model.mdu", "--point", POINT, "--values", specpath)
    preview = cli.invoke(*args)
    require(snapshot(folder) == before, "Series preview changed model bytes")
    require(re.fullmatch("[0-9a-f]{64}", preview["input_sha256"]), "Missing preview hash")
    applied = cli.invoke(*args, "--apply", "--expect-sha256", preview["input_sha256"])
    before["boundaries.bc"] = expected
    require(snapshot(folder) == before, "Apply changed bytes beyond selected value tokens")
    return {"preview": preview, "applied": applied, "independent_bytes": "passed", "input_fingerprints": fingerprints(folder)}


def read_clock(nc, regular):
    import numpy as np
    from netCDF4 import date2num, num2date
    var = nc["time"]; values = var[:]
    require(not np.ma.getmaskarray(values).any() and np.isfinite(values).all(), "Invalid raw clock")
    units, calendar = var.units, getattr(var, "calendar", "standard")
    epoch = date2num(datetime(2026, 1, 1), units, calendar=calendar)
    second = date2num(datetime(2026, 1, 1, 0, 0, 1), units, calendar=calendar) - epoch
    seconds = (values - epoch) / second
    np.testing.assert_allclose(seconds, np.arange(0, 121, 10) if regular else [120], rtol=0, atol=1e-6)
    return {"units": units, "calendar": calendar, "seconds": seconds.tolist(), "final": num2date(values[-1], units, calendar=calendar).isoformat()}


def raw_case(folder):
    import numpy as np
    from netCDF4 import Dataset, chartostring, date2num
    output = folder / "model/output"
    maps, histories = list(output.glob("*_map.nc")), list(output.glob("*_his.nc"))
    require(len(maps) == len(histories) == 1, "Ambiguous/missing map/history")
    result = {"files": {}, "clock": {}}
    with Dataset(maps[0]) as nc:
        result["clock"]["map"] = read_clock(nc, True)
        x, y = nc["mesh2d_face_x"][:], nc["mesh2d_face_y"][:]
        require(x.shape == y.shape == (48,), "Channel changed shape")
        near = np.where((abs(x - 500115) < 1e-7) & (abs(y - 5700005) < 1e-7))[0]
        require(len(near) == 1, "Near-boundary physical cell missing/ambiguous")
        var = nc["mesh2d_s1"]
        require(var.units == "m", "Wrong map elevation units")
        level = var[:]
        require(level.shape == (13, 48) and not np.ma.getmaskarray(level).any() and np.isfinite(level).all(), "Bad map elevation mask/shape")
        result["map"] = np.asarray(level)
        result["map_near"] = np.asarray(level[:, near[0]])
        result["xy"] = np.column_stack([x, y])
        np.testing.assert_allclose(nc["mesh2d_node_z"][:], -3, rtol=0, atol=1e-7)
        np.testing.assert_allclose(nc["mesh2d_waterdepth"][:] - level, 3, rtol=0, atol=1e-6)
    with Dataset(histories[0]) as nc:
        result["clock"]["history"] = read_clock(nc, True)
        names = [str(v).strip(" \0") for v in chartostring(nc["station_name"][:])]
        require(names.count("near_east") == 1, "Missing/ambiguous station")
        i = names.index("near_east")
        require(abs(float(nc["station_x_coordinate"][i]) - 500115) < 1e-7 and abs(float(nc["station_y_coordinate"][i]) - 5700005) < 1e-7, "Wrong station coordinates")
        var = nc["waterlevel"]
        require(var.units == "m" and not np.ma.getmaskarray(var[:]).any(), "Bad history elevation units/mask")
        result["history_near"] = np.asarray(var[:, i])
        np.testing.assert_allclose(result["history_near"], result["map_near"], rtol=0, atol=1e-6)
    final = []
    for path in output.glob("*_rst.nc"):
        with Dataset(path) as nc:
            axis = nc["time"]
            target = date2num(datetime(2026, 1, 1, 0, 2), axis.units, calendar=getattr(axis, "calendar", "standard"))
            if len(axis) and abs(float(axis[-1]) - float(target)) < 1e-6:
                final.append(path)
    require(len(final) == 1, "Expected one actual final restart")
    with Dataset(final[0]) as nc:
        result["clock"]["restart"] = read_clock(nc, False)
        var = nc["s1"]; require(var.units == "m", "Wrong restart elevation units")
        require(not np.ma.getmaskarray(var[:]).any(), "Masked restart elevation")
        xy = np.column_stack([nc["FlowElem_xcc"][:], nc["FlowElem_ycc"][:]])
        order = [np.where(np.max(abs(xy - point), axis=1) < 1e-7)[0] for point in result["xy"]]
        require(all(len(o) == 1 for o in order), "Restart cells missing/ambiguous")
        restart = np.asarray(var[:]).reshape(-1)[[o[0] for o in order]]
        np.testing.assert_allclose(restart, result["map"][-1], rtol=0, atol=1e-6)
        result["restart"] = restart
    result["files"] = {p.name: sha(p) for p in (*maps, *histories, *final)}
    return result


def independent_comparison(cases):
    import numpy as np
    control, changed, future = (cases[key] for key in ("control", "changed", "future_noeffect"))
    for key in ("map", "history_near", "restart"):
        np.testing.assert_allclose(control[key], 0, rtol=0, atol=1e-6)
        np.testing.assert_allclose(future[key], control[key], rtol=0, atol=1e-6)
    delta = changed["history_near"] - control["history_near"]
    np.testing.assert_allclose(changed["map"][0], control["map"][0], rtol=0, atol=1e-6)
    require(.01 < float(delta[9:13].mean()) < .15, "Predeclared late near-boundary head response absent/wrong sign/outside bound")
    require(float(delta.min()) > -.02 and float(np.max(abs(changed["map"]))) < .2, "Unexpected large/opposite response")
    return {"state": "passed_independent_raw_response_and_future_noeffect", "near_history_delta_m": delta.tolist(),
            "late_mean_delta_m": float(delta[9:13].mean()), "control_and_future_atol_m": 1e-6,
            "map_history_and_final_restart_atol_m": 1e-6, "declaration": DECLARATION}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot-granted")
    args = parser.parse_args(argv)
    if args.native_slot_granted and not args.install:
        parser.error("--install required with a coordinator slot")
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=False)
    cli = PublicCLI(root / "commands")
    report = {"state": "preparing", "native": "not_requested", "declaration": DECLARATION, "cases": {}}
    save(root / "predeclared.json", DECLARATION)
    repro = root / "repro-source"; repro.mkdir()
    shutil.copyfile(__file__, repro / Path(__file__).name)
    try:
        template_before = fingerprints(ROOT / "examples/channel")
        model = authored_channel(root, cli)
        require(fingerprints(ROOT / "examples/channel") == template_before, "Original examples changed")
        report["authored_channel"] = fingerprints(model)
        schema = cli.invoke("schema", "inspect")
        if not {"boundary series-inspect", "boundary series-set"}.issubset(schema["commands"]):
            report.update(state="blocked_public_series_commands_not_registered", native="not_launched", harness="prepared; public mesh/model fixture passed")
            return 3
        prepared = {}
        for name in ("control", "changed", "future_noeffect"):
            folder = root / (name + "-inputs"); shutil.copytree(model, folder)
            inspection = cli.invoke("boundary", "series-inspect", folder / "model.mdu", "--point", POINT)
            require(POINT in list(walk(inspection)) and TIME_UNIT in list(walk(inspection)), "Inspection lacks point/exact time-unit evidence")
            changes = [{"time": "20", "value": "0.12"}, {"time": "120", "value": "0.12"}] if name == "changed" else [{"time": "240", "value": "0.12"}]
            report["cases"][name] = ({"edit": "untouched matched control", "input_fingerprints": fingerprints(folder)} if name == "control" else
                                      apply_checked(cli, folder, root / (name + "-changes.json"), changes))
            cli.invoke("model", "validate", folder / "model.mdu")
            prepared[name] = folder
        report["state"] = "ready_portable_public_series_and_native_declaration"
        if args.native_slot_granted:
            report.update(native="launch_requested", native_slot=args.native_slot_granted)
            save(root / "verification.json", report)
            results = {}
            for name, folder in prepared.items():
                before = fingerprints(folder); dest = root / (name + "-native")
                result = cli.invoke("run", "start", folder / "model.mdu", "--out", dest, "--install", args.install,
                                    "--route", "direct", "--timeout", 60)
                report["native"] = "launched"
                require(result["state"] == "completed", "Native case failed: " + name)
                status = cli.invoke("run", "status", dest)
                require(status["record"]["state"] == "completed", "Public status is not completed")
                require(fingerprints(folder) == before, "Native mutated original copied inputs")
                results[name] = raw_case(dest)
                report["cases"][name]["native"] = {"manifest_sha256": sha(dest / "manifest.json"), "status": status,
                    "raw_clocks": results[name]["clock"], "raw_files": results[name]["files"], "inputs_unchanged": True}
                save(root / "verification.json", report)
            report["numerical_comparison"] = independent_comparison(results)
            report["state"] = "passed_native_boundary_series"
    except Exception as exc:
        report.update(state="failed_boundary_series_verification", error=str(exc), traceback=traceback.format_exc())
    finally:
        report["actual_native_manifests"] = {str(p.relative_to(root)): sha(p) for p in root.glob("*-native/manifest.json")}
        if report["actual_native_manifests"]:
            report["native"] = "launched"
        save(root / "verification.json", report)
        print(json.dumps({"state": report["state"], "path": str(root / "verification.json"), "sha256": sha(root / "verification.json"), "native": report["native"]}))
    return 0 if report["state"].startswith(("ready", "passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
