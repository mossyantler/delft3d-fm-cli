"""Owned adapter self-check, not independent V or native modeling evidence.

Run with research Python (netCDF4+pyproj installed), an existing read-only M3 MDU,
and a new evidence directory. All adversarial edits use owned temporary copies::

    python examples/boundary_location_projection/check_projection.py --mdu M3.mdu --out NEW
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from dfm_cli.boundary_location_projection import project_locations
from dfm_cli.boundary_locations_graph import pli
from dfm_cli.common import DfmError

RAW = (b"\xef\xbb\xbf# preserved header\r\n; preserved comment\r\nwest # label\r\n"
       b"2\t2 # count\r\n +3.000D+0\t +0.000e0 west_0001 # first\r\n"
       b" 3.001 0.001 west_0002 # second\r\n; unchanged footer\r\n")
KW = dict(source_crs="EPSG:4326", target_crs="EPSG:32631", source_unit="degree", target_unit="m")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write("\n")


def fixture(folder, code=32631):
    from netCDF4 import Dataset
    from pyproj import CRS
    folder.mkdir()
    mdu = folder / "model.mdu"
    mdu.write_bytes(b"[General]\nPathsRelativeToParent = 0\n[geometry]\nNetFile = mesh.nc\nKmx = 0\n")
    crs = CRS.from_epsg(code)
    cf = crs.to_cf()
    if code == 28992:
        cf.update(grid_mapping_name="oblique_stereographic", semi_major_axis=6377397.155,
                  inverse_flattening=299.1528128, latitude_of_projection_origin=52.15616055555555,
                  longitude_of_projection_origin=5.3876388888888895, scale_factor_at_projection_origin=0.9999079,
                  false_easting=155000.0, false_northing=463000.0)
    if code == 3857:
        cf.update(grid_mapping_name="mercator", semi_major_axis=6378137.0, semi_minor_axis=6378137.0,
                  longitude_of_projection_origin=0.0, standard_parallel=0.0, false_easting=0.0, false_northing=0.0)
    origin_x, origin_y = {32731: (500000, 9000000), 32652: (500000, 4000000), 5179: (1000000, 2000000),
                          28992: (155000, 463000), 3857: (500000, 5000000), 4258: (5, 52),
                          4737: (127.5, 38)}.get(code, (3, 0) if crs.is_geographic else (500000, 0))
    delta = .01 if crs.is_geographic else 100
    with Dataset(folder / "mesh.nc", "w", format="NETCDF3_64BIT_OFFSET") as ds:
        for key, value in (("nodes", 3), ("faces", 1), ("corners", 3)):
            ds.createDimension(key, value)
        topology = ds.createVariable("mesh2d", "i4")
        topology.setncatts(dict(cf_role="mesh_topology", topology_dimension=2,
                               node_coordinates="x y", face_node_connectivity="face_nodes"))
        mapping = ds.createVariable("projected_coordinate_system", "i4")
        mapping.assignValue(code)
        mapping.setncatts(dict(cf, EPSG_code=f"EPSG:{code}", epsg=code))
        for name, standard, units, values in (
            ("x", "longitude" if crs.is_geographic else "projection_x_coordinate",
             "degrees_east" if crs.is_geographic else "m", [3, 3.01, 3.01] if crs.is_geographic else [500000, 500100, 500100]),
            ("y", "latitude" if crs.is_geographic else "projection_y_coordinate",
             "degrees_north" if crs.is_geographic else "m", [0, 0, 0.01] if crs.is_geographic else [0, 0, 100]),
        ):
            values = [origin_x, origin_x + delta, origin_x + delta] if name == "x" else [origin_y, origin_y, origin_y + delta]
            var = ds.createVariable(name, "f8", ("nodes",))
            var.setncatts(dict(standard_name=standard, units=units, grid_mapping=mapping.name)); var[:] = values
        face = ds.createVariable("face_nodes", "i4", ("faces", "corners"))
        face.start_index = 1; face[:] = [[1, 2, 3]]
    return mdu


def raw_points(points):
    return ("line\n2 2\n" + "\n".join(" ".join(map(str, p)) for p in points) + "\n").encode()


def run(mdu, out):
    import netCDF4
    from pyproj import CRS
    from dfm_cli import boundary_location_crs as helper
    source_path = ROOT / "src/dfm_cli/boundary_location_projection.py"
    helper_path = ROOT / "src/dfm_cli/boundary_location_crs.py"
    source_hash, helper_hash = sha(source_path.read_bytes()), sha(helper_path.read_bytes())
    out.mkdir(parents=True, exist_ok=False)
    checks = []
    def accept(name, function):
        function(); checks.append({"name": name, "state": "passed"})
    def refuse(name, function, expected=None):
        try:
            function()
        except DfmError as exc:
            assert exc.code != "boundary_projection_unavailable", (name, "Unexpected generic reader failure", exc.details)
            assert expected is None or exc.code == expected, (name, exc.code)
            checks.append({"name": name, "state": "refused", "code": exc.code})
        else:
            raise AssertionError(name + " was accepted")
    parsed = pli(RAW, "owned source")[0]; original = copy.deepcopy(parsed)
    changed, evidence = project_locations(RAW, parsed, mdu=mdu, **KW)
    assert parsed == original and sha(RAW) == evidence["source_raw_sha256"]
    check = pli(changed, "changed")[0]
    assert abs(float(check["points"][0]["tokens"][0][2]) - 500000) < 1e-7
    assert float(check["points"][0]["tokens"][1][2]) == 0
    assert changed.startswith(b"\xef\xbb\xbf# preserved header\r\n")
    assert b"west_0001 # first\r\n" in changed and b"west_0002 # second\r\n" in changed
    assert b"; unchanged footer\r\n" in changed
    assert project_locations(RAW, parsed, mdu=mdu, **KW) == (changed, evidence)
    checks.append({"name": "actual_M3_readonly_origin_XY_identity_supports_comments_BOM_CRLF_and_repeatability", "state": "passed"})
    (out / "source.pli").write_bytes(RAW); (out / "projected.pli").write_bytes(changed)
    write_json(out / "actual-M3-receipt.json", evidence)
    altered = copy.deepcopy(parsed); altered["points"].reverse()
    refuse("reordered_parsed_points", lambda: project_locations(RAW, altered, mdu=mdu, **KW))
    altered = copy.deepcopy(parsed); t = altered["points"][0]["tokens"][0]; altered["points"][0]["tokens"][0] = (t[0]+1, t[1], t[2])
    refuse("forged_token_span", lambda: project_locations(RAW, altered, mdu=mdu, **KW))
    refuse("multiple_lines", lambda: project_locations(RAW + b"second\n2 2\n3 0\n3.01 0.01\n", parsed, mdu=mdu, **KW))
    refuse("public_metre_flag_is_not_m", lambda: project_locations(RAW, parsed, mdu=mdu, **(KW | {"target_unit": "metre"})))
    comment = RAW.replace(b"preserved header", b"different header")
    _, other = project_locations(comment, pli(comment, "comment")[0], mdu=mdu, **KW)
    assert other["coordinate_input_sha256"] == evidence["coordinate_input_sha256"] and other["consent_sha256"] != evidence["consent_sha256"]
    checks.append({"name": "consent_binds_original_raw_bytes_beyond_numeric_hash", "state": "passed"})
    with tempfile.TemporaryDirectory(prefix="dfm-projection-owned-") as temp:
        root = Path(temp)
        cases = [
            ("missing_EPSG_and_full_definition", lambda ds: [ds["projected_coordinate_system"].delncattr(k) for k in ("epsg", "EPSG_code", "crs_wkt")]),
            ("conflicting_EPSG", lambda ds: ds["projected_coordinate_system"].setncattr("epsg", 32632)),
            ("conflicting_WKT", lambda ds: ds["projected_coordinate_system"].setncattr("spatial_ref", CRS.from_epsg(32632).to_wkt())),
            ("conflicting_global_EPSG", lambda ds: ds.setncattr("EPSG_code", "EPSG:28992")),
            ("conflicting_CF_parameter", lambda ds: ds["projected_coordinate_system"].setncattr("longitude_of_central_meridian", 4.0)),
            ("conflicting_PROJ", lambda ds: ds["projected_coordinate_system"].setncattr("proj4_params", "+proj=utm +zone=32 +datum=WGS84 +units=m")),
            ("missing_X_reference", lambda ds: ds["x"].delncattr("grid_mapping")),
            ("conflicting_Y_reference", lambda ds: ds["y"].setncattr("grid_mapping", "other")),
            ("wrong_X_unit", lambda ds: ds["x"].setncattr("units", "degrees_east")),
            ("wrong_X_standard_name", lambda ds: ds["x"].setncattr("standard_name", "latitude")),
            ("wrong_X_axis", lambda ds: ds["x"].setncattr("axis", "Y")),
            ("wrong_node_dimension", lambda ds: ds["mesh2d"].setncattr("node_dimension", "other")),
            ("masked_node", lambda ds: ds["x"].setncattr("missing_value", 500000.0)),
            ("nonfinite_node", lambda ds: ds["x"].__setitem__(0, float("nan"))),
            ("no_2D_topology", lambda ds: ds["mesh2d"].setncattr("topology_dimension", 1)),
            ("multiple_CRS_vars", lambda ds: ds.createVariable("other", "i4").setncattr("epsg", 32631)),
        ]
        for name, mutate in cases:
            model = fixture(root / name)
            with netCDF4.Dataset(model.parent / "mesh.nc", "r+") as ds:
                mutate(ds)
            refuse(name, lambda model=model: project_locations(RAW, parsed, mdu=model, **KW))
        for code, points in ((32631, [[3, 0], [3.001, .001]]), (32731, [[3, -1], [3.001, -1.001]]),
                             (32652, [[129, 36], [129.001, 36.001]]), (5179, [[1000000, 2000000], [1000100, 2000100]]),
                             (28992, [[155000, 463000], [155100, 463100]]), (3857, [[500000, 5000000], [500100, 5000100]]),
                             (4326, [[3, 0], [3.001, .001]]), (4258, [[5, 52], [5.001, 52.001]]), (4737, [[127.5, 38], [127.501, 38.001]])):
            model = fixture(root / f"positive-{code}", code)
            unit = "degree" if code in {4326, 4258, 4737} else "m"
            raw = raw_points(points if code not in {32631, 32731, 32652} else [[500000, 0 if code != 32731 else 9000000], [500100, 100 if code != 32731 else 9000100]])
            project_locations(raw, pli(raw, "profile")[0], mdu=model, source_crs=f"EPSG:{code}", target_crs=f"EPSG:{code}", source_unit=unit, target_unit=unit)
            checks.append({"name": f"bounded_mapping_EPSG_{code}", "state": "passed"})
        model = fixture(root / "WKT-only")
        with netCDF4.Dataset(model.parent / "mesh.nc", "r+") as ds:
            for key in ("epsg", "EPSG_code"):
                ds["projected_coordinate_system"].delncattr(key)
        project_locations(RAW, parsed, mdu=model, **KW)
        checks.append({"name": "explicit_equivalent_WKT_without_EPSG_attribute", "state": "passed"})
        for name, transform in (("duplicate_NetFile", lambda raw: raw + b"NetFile=mesh.nc\n"),
                                ("missing_NetFile", lambda raw: raw.replace(b"NetFile = mesh.nc", b"NetFile =")),
                                ("absolute_NetFile", lambda raw: raw.replace(b"mesh.nc", b"C:/foreign/mesh.nc")),
                                ("conflicting_MDU_EPSG", lambda raw: raw + b"EPSG_code = EPSG:32632\n"),
                                ("conflicting_MDU_CRS", lambda raw: raw + b"CRS = EPSG:28992\n"),
                                ("conflicting_MDU_unit", lambda raw: raw + b"coordinate_units = degree\n"),
                                ("conflicting_MDU_spherical", lambda raw: raw + b"JSferic = 1\n")):
            model = fixture(root / name); model.write_bytes(transform(model.read_bytes()))
            refuse(name, lambda model=model: project_locations(RAW, parsed, mdu=model, **KW))
        for part in ("mesh", "mdu"):
            model = fixture(root / f"stale-{part}"); original_prepare = helper.prepare_transform
            def mutate_after(*args, **kwargs):
                prepared = original_prepare(*args, **kwargs)
                path = model.parent / "mesh.nc" if part == "mesh" else model
                before = path.stat()
                if part == "mesh":
                    with netCDF4.Dataset(path, "r+") as ds:
                        ds["projected_coordinate_system"].false_easting = 500001.0
                else:
                    path.write_bytes(path.read_bytes().replace(b"Kmx = 0", b"Kmx = 1"))
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                assert path.stat().st_size == before.st_size
                return prepared
            with patch.object(helper, "prepare_transform", side_effect=mutate_after):
                refuse("same_size_mtime_stale_" + part, lambda: project_locations(RAW, parsed, mdu=model, **KW), "boundary_projection_stale")
    code = "import sys;sys.path.insert(0,sys.argv[1]);import dfm_cli.boundary_location_projection;assert 'pyproj' not in sys.modules and 'netCDF4' not in sys.modules"
    subprocess.run([sys.executable, "-S", "-B", "-c", code, str(ROOT / "src")], check=True, capture_output=True)
    checks.append({"name": "fresh_no_site_import_is_optional_dependency_free", "state": "passed"})
    assert source_hash == sha(source_path.read_bytes()) and helper_hash == sha(helper_path.read_bytes())
    report = {"state": "passed", "classification": "implementation_self_check_not_independent_V_or_G", "cases": len(checks), "checks": checks,
              "adapter_sha256": source_hash, "frozen_helper_sha256": helper_hash, "example_check_sha256": sha(Path(__file__).read_bytes()),
              "actual_M3_receipt_sha256": sha((out / "actual-M3-receipt.json").read_bytes()), "native_suite_launches": 0,
              "source_and_target_untouched": True, "limitations": "No public parser/authoring integration or native/scientific validation"}
    write_json(out / "verification.json", report)
    print(json.dumps({"state": report["state"], "cases": len(checks), "adapter_sha256": source_hash, "evidence": str(out)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mdu", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    run(options.mdu, options.out)
