"""Independent M3 replay using only public CLI and direct netCDF4 oracles.

Run with application venv and run extra. The caller must obtain the coordinator's
exclusive native slot before passing --native-slot-granted. A portable replay
without that flag never launches an engine. Every --out directory must be new.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .channel_fixture import DATUM, write_mesh, write_spec


def fingerprints(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def read_blocks(path: Path) -> list:
    """Minimal independent reader preserving repeated BC Quantity/Unit pairs."""
    blocks = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            blocks.append({"section": line[1:-1].strip().casefold(), "entries": [], "data": []})
        elif "=" in line:
            key, value = line.split("=", 1)
            assert blocks, path
            blocks[-1]["entries"].append((key.strip().casefold(), value.strip()))
        else:
            assert blocks, path
            blocks[-1]["data"].append(line.split())
    return blocks


def check_bundle(folder: Path, spec: dict, original_mesh: Path) -> dict:
    """Inspect serialized inputs without importing the product parser/writer."""
    import numpy as np

    assert (folder / "mesh_net.nc").read_bytes() == original_mesh.read_bytes()
    mdu = read_blocks(folder / "model.mdu")
    fields = {(b["section"], k): v for b in mdu for k, v in b["entries"]}
    assert fields["general", "program"] == "D-Flow FM", "Engine requires this exact model-definition identity"
    assert fields["general", "pathsrelativetoparent"] == "0"
    assert fields["geometry", "netfile"] == "mesh_net.nc"
    assert fields["geometry", "kmx"] == "0"
    assert fields["external forcing", "extforcefilenew"] == "boundaries.ext"
    assert fields["external forcing", "extforcefile"] == ""
    assert fields["output", "obsfile"] == "observations.xyn"
    assert fields["time", "startdatetime"] == "20010101000000"
    assert fields["time", "stopdatetime"] == "20010101000200"
    assert float(fields["time", "tzone"]) == 0
    assert float(fields["output", "hisinterval"]) == 10
    assert float(fields["output", "mapinterval"]) == 10
    assert any(k == "waterlevini" and float(v) == 0 for b in mdu for k, v in b["entries"])
    ext = [dict(b["entries"]) for b in read_blocks(folder / "boundaries.ext") if b["section"] == "boundary"]
    assert len(ext) == 2
    forcing = [b for b in read_blocks(folder / "boundaries.bc") if b["section"] == "forcing"]
    assert len(forcing) == 4  # Every PLI support point is explicit.
    by_name = {dict(b["entries"])["name"]: b for b in forcing}
    assert len(by_name) == len(forcing)
    for expected in spec["boundaries"]:
        filename = f"boundary_{expected['id']}.pli"
        matching = [b for b in ext if b["locationfile"] == filename]
        assert len(matching) == 1
        assert matching[0]["quantity"] == "waterlevelbnd" and matching[0]["forcingfile"] == "boundaries.bc"
        lines = (folder / filename).read_text(encoding="utf-8").splitlines()
        assert lines[0] == expected["id"] and lines[1].split() == ["2", "2"]
        np.testing.assert_array_equal([[float(n) for n in row.split()] for row in lines[2:]], expected["coordinates"])
        for i in (1, 2):
            block = by_name[f"{expected['id']}_{i:04d}"]
            entries = block["entries"]
            signal = expected["signal"]
            assert dict(entries)["function"] == signal["function"]
            columns = [(key, value) for key, value in entries if key in ("quantity", "unit")]
            if signal["function"] == "harmonic":
                assert columns == [("quantity", "harmonic component"), ("unit", "minutes"),
                                   ("quantity", "waterlevelbnd amplitude"), ("unit", "m"),
                                   ("quantity", "waterlevelbnd phase"), ("unit", "deg")]
                np.testing.assert_array_equal([[float(n) for n in row] for row in block["data"]], [[10, .05, 90]])
            else:
                assert columns[0] == ("quantity", "time")
                assert columns[1][0] == "unit" and columns[1][1].startswith("seconds since 2001-01-01 00:00:00")
                assert columns[2:] == [("quantity", "waterlevelbnd"), ("unit", "m")]
                np.testing.assert_array_equal([[float(n) for n in row] for row in block["data"]], [[0, 0], [120, 0]])
    observations = [row.split() for row in (folder / "observations.xyn").read_text(encoding="utf-8").splitlines() if row.strip()]
    assert len(observations) == len(spec["observations"])
    for actual, expected in zip(observations, spec["observations"]):
        assert list(map(float, actual[:2])) == [expected["x"], expected["y"]]
        assert " ".join(actual[2:]).strip("'\"") == expected["id"]
    normalized = json.loads((folder / "create-spec.json").read_text(encoding="utf-8"))
    assert normalized["mesh"]["path"] == "mesh_net.nc"
    provenance = json.loads((folder / "create-provenance.json").read_text(encoding="utf-8"))
    return {"files": fingerprints(folder), "provenance": provenance,
            "boundary_support_points": sorted(by_name), "observations": [o["id"] for o in spec["observations"]]}


def invalid_specs(spec: dict):
    """Acceptance cases with all non-target values kept valid."""
    cases = {}
    def add(label, mutate):
        value = copy.deepcopy(spec)
        mutate(value)
        cases[label] = value
    add("missing_level_unit", lambda s: s["initial_water_level"].pop("unit"))
    add("wrong_level_unit", lambda s: s["initial_water_level"].update(unit="cm"))
    add("wrong_time_unit", lambda s: s["boundaries"][1]["signal"].update(time_unit="min"))
    add("duplicate_observation", lambda s: s["observations"].append(dict(s["observations"][0])))
    add("duplicate_casefold_boundary", lambda s: s["boundaries"][1].update(id="WEST"))
    add("short_end_coverage", lambda s: s["boundaries"][1]["signal"].update(values=[[0, 0], [119, 0]]))
    add("short_start_coverage", lambda s: s["boundaries"][1]["signal"].update(values=[[1, 0], [120, 0]]))
    add("wrong_epoch_coverage", lambda s: s["boundaries"][1]["signal"].update(time_origin="2001-01-02T00:00:00Z"))
    add("datum_mismatch", lambda s: s["initial_water_level"].update(vertical_datum="unrelated zero"))
    add("crs_mismatch", lambda s: s["crs"].update(epsg=32632))
    add("outside_observation", lambda s: s["observations"][0].update(x=500999))
    add("interior_boundary", lambda s: s["boundaries"][0].update(coordinates=[[500010, 5700000], [500010, 5700040]]))
    return cases


def check_mesh(path: Path) -> dict:
    """Check geometry/topology from stored values, independent of writer loops."""
    import numpy as np
    from netCDF4 import Dataset

    with Dataset(path) as nc:
        topo = nc["mesh2d"]
        assert topo.cf_role == "mesh_topology" and topo.topology_dimension == 2
        xy = np.column_stack([nc[name][:] for name in topo.node_coordinates.split()])
        assert xy.shape == (65, 2) and np.isfinite(xy).all()
        assert np.unique(xy, axis=0).shape[0] == 65
        np.testing.assert_array_equal(np.unique(xy[:, 0]), np.arange(500000, 500121, 10))
        np.testing.assert_array_equal(np.unique(xy[:, 1]), np.arange(5700000, 5700041, 10))
        z = nc["mesh2d_node_z"]
        assert z.units == "m" and z.positive == "up" and z.vertical_datum == DATUM
        assert not np.ma.getmaskarray(z[:]).any()
        np.testing.assert_array_equal(z[:], np.full(65, -3.0))
        assert nc["projected_coordinate_system"].epsg == 32631
        connectivity = nc[topo.face_node_connectivity]
        assert connectivity.start_index == 1 and not np.ma.getmaskarray(connectivity[:]).any()
        faces = np.asarray(connectivity[:]) - int(connectivity.start_index)
        assert faces.shape == (48, 4) and faces.min() == 0 and faces.max() == 64
        incidence = Counter()
        for face in faces:
            assert len(set(map(int, face))) == 4
            polygon = xy[face] - xy[face[0]]
            area = .5 * np.sum(polygon[:, 0] * np.roll(polygon[:, 1], -1)
                               - polygon[:, 1] * np.roll(polygon[:, 0], -1))
            assert area == 100.0, (face.tolist(), area)
            for a, b in zip(face, np.roll(face, -1)):
                assert np.linalg.norm(xy[a] - xy[b]) == 10.0
                incidence[tuple(sorted((int(a), int(b))))] += 1
        edgevar = nc[topo.edge_node_connectivity]
        assert edgevar.start_index == 1 and not np.ma.getmaskarray(edgevar[:]).any()
        edges = np.asarray(edgevar[:]) - int(edgevar.start_index)
        assert edges.shape == (112, 2)
        stored = [tuple(sorted(map(int, pair))) for pair in edges]
        assert len(set(stored)) == 112 and set(stored) == set(incidence)
        assert Counter(incidence.values()) == {1: 32, 2: 80}
        # Verify a single connected component, not merely valid numeric indices.
        visited, pending = set(), [0]
        adjacency = {i: set() for i in range(65)}
        for a, b in stored:
            adjacency[a].add(b)
            adjacency[b].add(a)
        while pending:
            current = pending.pop()
            if current not in visited:
                visited.add(current)
                pending.extend(adjacency[current] - visited)
        assert len(visited) == 65 and 65 - len(stored) + len(faces) == 1
    return {"nodes": 65, "edges": 112, "faces": 48, "area_m2": 4800,
            "boundary_edges": 32, "interior_edges": 80,
            "connected_components": 1, "bed_m": -3.0, "epsg": 32631,
            "vertical_datum": DATUM, "checks": "stored coordinates, CCW areas, edge incidence, connectivity"}


def raw_time_axis(path: Path, expected_stop: datetime, cadence: int | None = None) -> dict:
    import numpy as np
    from netCDF4 import Dataset, date2num, num2date

    with Dataset(path) as nc:
        time = nc["time"]
        calendar = getattr(time, "calendar", "standard")
        data = time[:]
        assert data.ndim == 1 and data.size > 0 and not np.ma.getmaskarray(data).any()
        assert np.isfinite(data).all() and (data.size == 1 or (np.diff(data) > 0).all())
        target = date2num(expected_stop, time.units, calendar=calendar)
        np.testing.assert_allclose(data[-1], target, rtol=0, atol=1e-6)
        if cadence is not None:
            start = date2num(datetime(2001, 1, 1), time.units, calendar=calendar)
            step = date2num(datetime(2001, 1, 1, 0, 0, cadence), time.units, calendar=calendar) - start
            np.testing.assert_allclose(data, start + np.arange(13) * step, rtol=0, atol=1e-6)
        last = num2date(data[-1], time.units, calendar=calendar).isoformat()
        return {"path": str(path), "units": time.units, "calendar": calendar,
                "samples": int(data.size), "last": last,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def raw_map_fields(path: Path) -> dict:
    """Check the engine's actual processed domain, bed sign and initial depth."""
    import numpy as np
    from netCDF4 import Dataset
    with Dataset(path) as nc:
        assert len(nc.dimensions["mesh2d_nNodes"]) == 65
        assert len(nc.dimensions["mesh2d_nEdges"]) == 112
        assert len(nc.dimensions["mesh2d_nFaces"]) == 48
        bed = nc["mesh2d_node_z"][:]
        level = nc["mesh2d_s1"][:]
        depth = nc["mesh2d_waterdepth"][:]
        for values in (bed, level, depth):
            assert not np.ma.getmaskarray(values).any() and np.isfinite(values).all()
        np.testing.assert_array_equal(bed, np.full(65, -3.0))
        assert level.shape == depth.shape == (13, 48)
        np.testing.assert_array_equal(level[0], np.zeros(48))
        np.testing.assert_array_equal(depth[0], np.full(48, 3.0))
        np.testing.assert_allclose(depth - level, 3.0, rtol=0, atol=1e-6)
        assert float(depth.min()) > 0
        return {"nodes": 65, "edges": 112, "faces": 48,
                "bed_range_m": [float(bed.min()), float(bed.max())],
                "waterlevel_range_m": [float(level.min()), float(level.max())],
                "waterdepth_range_m": [float(depth.min()), float(depth.max())],
                "initial_waterdepth_m": 3.0,
                "depth_minus_level_m": 3.0, "float32_tolerance_m": 1e-6}


def check_history(cli, path: Path, spec: dict, out: Path) -> dict:
    """Compare M2 JSON/CSV with raw masks, station indices, values and CF dates."""
    import numpy as np
    from netCDF4 import Dataset, chartostring, num2date

    result = {}
    cli.invoke("results", "inspect", path)
    with Dataset(path) as nc:
        namesvar = nc["station_name"]
        namesraw = np.ma.filled(namesvar[:], b"\x00")
        names = chartostring(namesraw) if namesraw.ndim == 2 else namesraw
        names = [v.decode("utf-8") if isinstance(v, bytes) else str(v) for v in names]
        names = [v.rstrip("\x00 ") for v in names]
        assert names == [o["id"] for o in spec["observations"]], names
        var, time = nc["waterlevel"], nc["time"]
        assert var.units == "m"
        times = [v.isoformat() for v in num2date(time[:], time.units, calendar=getattr(time, "calendar", "standard"))]
        for obs in spec["observations"]:
            index = names.index(obs["id"])
            selection = tuple(index if d == namesvar.dimensions[0] else slice(None) for d in var.dimensions)
            raw = np.ma.asarray(var[selection])
            mask = np.ma.getmaskarray(raw) | ~np.isfinite(raw.data)
            expected = [None if missing else float(v) for v, missing in zip(raw.data, mask)]
            assert not mask.any(), "Synthetic wet channel unexpectedly has missing history samples"
            csvpath = out / (obs["id"] + "-series.csv")
            actual = cli.invoke("results", "series", path, "--variable", "waterlevel", "--station", obs["id"], "--csv", csvpath)
            assert actual["values"] == [expected]
            assert actual["mask"] == [mask.tolist()]
            assert actual["time"]["iso"] == times
            assert actual["time"]["units"] == time.units
            assert actual["variable"]["units"] == var.units
            assert actual["stations"][0]["id"] == obs["id"] and actual["stations"][0]["index"] == index
            for axis in ("x", "y"):
                rawcoord = float(nc[f"station_{axis}_coordinate"][index])
                assert rawcoord == obs[axis]
                assert actual["stations"][0]["coordinates"][axis]["values"] == rawcoord
            with csvpath.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == len(expected)
            assert [r["station"] for r in rows] == [obs["id"]] * len(rows)
            assert [r["time"] for r in rows] == times
            assert [float(r["value"]) for r in rows] == expected
            result[obs["id"]] = {"values": expected, "times": times, "units": var.units,
                                   "mask": mask.tolist(), "station_index": index,
                                   "csv": str(csvpath), "json_equals_raw_netcdf": True}
        assert any(abs(v) > 1e-8 for row in result.values() for v in row["values"]), "No resolved time-varying response"
    return result


class PublicCLI:
    def __init__(self, out: Path):
        self.out = out
        self.calls = []
        (out / "commands").mkdir()

    def invoke(self, *arguments, success=True):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        completed = subprocess.run(argv, capture_output=True, timeout=100)
        number = len(self.calls) + 1
        stem = self.out / "commands" / f"{number:02d}"
        stem.with_suffix(".stdout.json").write_bytes(completed.stdout)
        stem.with_suffix(".stderr.txt").write_bytes(completed.stderr)
        self.calls.append({"argv": argv, "returncode": completed.returncode})
        (self.out / "invocations.json").write_text(json.dumps(self.calls, indent=2), encoding="utf-8")
        payload = json.loads(completed.stdout)
        assert payload["protocol_version"] == 2, payload
        assert payload["ok"] is success, payload
        assert (completed.returncode == 0) is success, payload
        assert completed.returncode != 70, payload
        return payload.get("result", payload.get("error"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot-granted", action="store_true")
    args = parser.parse_args()
    if args.native_slot_granted and args.install is None:
        parser.error("--install is required with --native-slot-granted")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repro = out / "repro-source"
    repro.mkdir()
    # Retain the exact small oracle/generator and example alongside transcripts;
    # subsequent application changes cannot silently change this replay source.
    root = Path(__file__).resolve().parents[3]
    for source in (Path(__file__), Path(__file__).with_name("channel_fixture.py"),
                   root / "tests/test_create.py", root / "examples/channel/model.json"):
        shutil.copyfile(source, repro / source.name)
    summary = {"status": "failed", "native_requested": args.native_slot_granted,
               "native_performed": False, "experiment": str(out),
               "repro_source_hashes": fingerprints(repro)}
    cli = PublicCLI(out)
    try:
        summary.update(replay(out, cli, args.install, args.native_slot_granted))
        summary["status"] = "passed"
    except Exception as exc:
        summary["error"] = str(exc)
        summary["traceback"] = traceback.format_exc()
        raise
    finally:
        summary["invocations"] = cli.calls
        manifest_path = out / "native-direct/manifest.json"
        if manifest_path.is_file():
            summary["native_performed"] = True
            summary["manifest_path"] = str(manifest_path)
            summary["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            summary["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        (out / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "experiment": str(out),
                      "native_status": summary.get("native_status"),
                      "negative_cases": len(summary.get("negative_cases", {})),
                      "public_cli_invocations": len(cli.calls),
                      "manifest": summary.get("manifest_path"),
                      "raw_output_axes": summary.get("raw_output_axes")}, indent=2))


def replay(out, cli, install, native):
    source = out / "source"
    source.mkdir()
    mesh = source / "channel_net.nc"
    mesh_metadata = write_mesh(mesh)
    mesh_checks = check_mesh(mesh)
    specpath = source / "model.json"
    spec = write_spec(specpath, mesh)
    source_before = fingerprints(source)
    negatives = {}
    negative_dir = out / "negative_specs"
    negative_dir.mkdir()
    for name, bad_spec in invalid_specs(spec).items():
        badpath = negative_dir / (name + ".json")
        badpath.write_text(json.dumps(bad_spec, indent=2), encoding="utf-8")
        rejected = negative_dir / (name + "_output")
        error = cli.invoke("model", "create", badpath, "--out", rejected, success=False)
        assert not rejected.exists(), (name, "failed authoring left a partial model")
        negatives[name] = error
    created = out / "authored"
    authored_result = cli.invoke("model", "create", specpath, "--out", created)
    bundle = check_bundle(created, spec, mesh)
    assert fingerprints(source) == source_before
    provenance = bundle["provenance"]
    assert provenance["source_mesh"]["sha256"] == mesh_metadata["sha256"]
    assert provenance["source_spec"]["sha256"] == source_before["model.json"]
    for entry in provenance["files"]:
        assert bundle["files"][entry["relative_path"]] == entry["sha256"]
    assert provenance["checks"]["simulation"] == "not_performed"
    # Both the complete generated folder and original sources are moved. The
    # engine-input graph must be relative; provenance paths are historical only.
    relocated = out / "relocated inputs"
    assert created.resolve().is_relative_to(out) and relocated.resolve().is_relative_to(out)
    assert not relocated.exists()
    created.rename(relocated)
    hidden = out / "source moved after creation"
    assert not hidden.exists() and hidden.resolve().is_relative_to(out)
    source.rename(hidden)
    assert fingerprints(relocated) == bundle["files"]
    cli.invoke("model", "validate", relocated / "model.mdu")
    cli.invoke("model", "inspect", relocated / "model.mdu")
    cli.invoke("model", "create", relocated / "create-spec.json", "--out", out / "normalized_replay")
    assert (out / "normalized_replay/model.mdu").read_bytes() == (relocated / "model.mdu").read_bytes()
    before_conflict = fingerprints(relocated)
    cli.invoke("model", "create", relocated / "create-spec.json", "--out", relocated, success=False)
    assert fingerprints(relocated) == before_conflict
    result = {"native_performed": False, "mesh": mesh_metadata, "mesh_checks": mesh_checks,
              "negative_cases": negatives, "authored_result": authored_result,
              "relocated": str(relocated), "bundle": bundle,
              "normalized_spec_replay": "passed", "source_files_unchanged": True,
              "scope": "synthetic 2D channel input/reference verification; no scientific calibration"}
    if not native:
        result["native_status"] = "not_requested; coordinator slot required"
        return result
    run = out / "native-direct"
    execution = cli.invoke("run", "start", relocated / "model.mdu", "--out", run,
                           "--install", install, "--route", "direct", "--timeout", "60", "--progress")
    assert execution["state"] == "completed", execution
    state = cli.invoke("run", "status", run)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 3 and manifest["state"] == "completed" and manifest["returncode"] == 0
    assert state["record"] == manifest
    output = run / "model/output"
    axes = {kind: raw_time_axis(output / name, datetime(2001, 1, 1, 0, 2), cadence=10)
            for kind, name in [("history", "model_his.nc"), ("map", "model_map.nc")]}
    restarts = list(output.glob("*_rst.nc"))
    assert len(restarts) >= 2
    axes["initial_restart"] = raw_time_axis(sorted(restarts)[0], datetime(2001, 1, 1))
    axes["final_restart"] = raw_time_axis(sorted(restarts)[-1], datetime(2001, 1, 1, 0, 2))
    fields = raw_map_fields(output / "model_map.nc")
    series = check_history(cli, output / "model_his.nc", spec, out)
    assert fingerprints(relocated) == before_conflict
    assert fingerprints(hidden) == source_before
    result.update(native_performed=True, native_status="completed", raw_output_axes=axes,
                  history_series=series, raw_map_fields=fields, manifest_path=str(manifest_path),
                  manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  manifest=manifest, relocated_inputs_unchanged_by_run=True)
    return result


if __name__ == "__main__":
    main()
