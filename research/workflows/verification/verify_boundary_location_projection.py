"""B04-CRS-PUBLIC-V end-to-end subprocess gate, native-free.

Stage before wiring: research/.venv/Scripts/python.exe -B -m
research.workflows.verification.verify_boundary_location_projection --out NEW --stage-only
After the public transform release, omit --stage-only for the actual gate.
Every producer invocation is `python -m dfm_cli` in a separate process.
"""
import argparse
import io
import json
import os
from pathlib import Path
import traceback
import unittest

from .verify_boundary_location_projection_fixture import (
    ROOT, Fixture, PublicCLI, directories, fingerprints, require, save, sha,
    snapshot, verify_copy,
)
from .verify_boundary_location_crs_controls import PROVENANCE, FORWARD_TOLERANCE_M

MESH_NEGATIVES = ("conflicting_epsg", "absent_crs", "orphan_mapping", "conflicting_xy_mapping",
                  "wrong_axis_units", "absent_axis_units", "wrong_axis_role", "unrelated_spoof")
STALE_CASES = ("raw_source_comment", "coordinate", "mesh_bytes", "unknown_input", "output_path")
DECLARATION = {
    "scope": "Public boundary location-import transformation; separate from pure CRS/PLI/export acceptance",
    "argv": "python -m dfm_cli boundary location-import MDU --source PLI --out NEW --coordinates transform --source-crs EPSG:4326 --target-crs EPSG:32631 --source-unit degree --target-unit m [--apply --expect-sha256 HASH]",
    "coordinate_controls_lon_lat": [[3,0],[4,50],[2,20]],
    "numerical_source": PROVENANCE, "absolute_tolerance_m": FORWARD_TOLERANCE_M,
    "source_untouched": "original MDU/model/NetFile/PLI inputs fingerprinted independently before/after",
    "preservation": "Every PLI byte outside six coordinate token spans; labels/supportIDs/row count/comments/tabs/mixed newline bytes retained",
    "mesh_attribution": "Actual selected [Geometry]NetFile, CF UGRID topology coordinates, each X/Y grid_mapping, projected_coordinate_system.EPSG_code='EPSG:32631', XY unitsm; unrelated variables/MDU guesses never substitute",
    "replacement": "Selected PLI coordinates changed; target EXT deactivated and selected BC block slices PHYSICALLY DELETED, never commented; other shared BC/EXT/MDU/NetFile bytes preserved; exact raw incoming and original changed files archived",
    "physical_retirement_regression": "Coordinator#130: a commented retired BC tail silently changed waterlevel despite exit0; authoring checks now require exact byte deletion. This gate still performs no solver/numerical validation.",
    "addition": "New line remains UNBOUND; graph and source inputs unchanged",
    "mesh_negatives": list(MESH_NEGATIVES), "stale_controls": list(STALE_CASES),
    "declaration_negatives": ["wrong_target_CRS", "wrong_target_unit", "metre_is_not_m", "missing_each_required_source_target_CRS_unit"],
    "dependency_gate": "Public as-is works under -S with opaqueNC and no optional imports; transform under-S refuses before writes",
    "no_solver_gui_or_install": True,
    "not_established": ["mesh containment", "live engine boundary", "scientific validity", "vertical datum conversion", "GUI parity"],
}


def success(api, fixture, **kwargs):
    row = api.call(fixture, **kwargs)
    require(row.get("ok") is True, "Public call failed: "+json.dumps(row))
    return row["result"]


def refusal(api, fixture, *, stale=False, **kwargs):
    before, dirs = snapshot(fixture.root), directories(fixture.root)
    row = api.call(fixture, **kwargs)
    require(row.get("ok") is False, "Unsafe public call accepted")
    if stale:
        require("stale" in row["error"]["code"], "Consent failure was not classified stale")
    require(snapshot(fixture.root) == before and directories(fixture.root) == dirs, "Refusal wrote or deleted inputs/output")
    require(not fixture.out.exists(), "Refusal created output")
    return {"public": row, "input_files": fingerprints(fixture.model), "no_output_writes": True}


def preview_apply(api, fixture, *, replacement):
    before, dirs = snapshot(fixture.root), directories(fixture.root)
    model_before = snapshot(fixture.model)
    source_before = fixture.source.read_bytes()
    preview = success(api, fixture)
    require(snapshot(fixture.root) == before and directories(fixture.root) == dirs and not fixture.out.exists(), "Preview wrote files/directories")
    result = success(api, fixture, apply=True, expect_sha256=preview["input_sha256"])
    require(result["input_sha256"] == preview["input_sha256"], "Apply no longer matches consent")
    independent = verify_copy(fixture, model_before, result, replacement=replacement)
    require(fixture.source.read_bytes() == source_before, "Incoming source changed")
    return {"preview":preview,"applied":result,"independent":independent,"independent_NetFile_metadata":fixture.mesh_metadata()}


def review_retained_retirement_preview(old_case, out):
    """Actual old/new public previews on identical retained bytes; NEVER apply.

    The old fixture and its receipt remain immutable. Fresh command logs are
    written under the NEW experiment only. A fabricated/remapped old hash is
    not used as an oracle.
    """
    old_case=Path(old_case).resolve()
    old=json.loads((old_case/"public-cli/001.json").read_bytes())
    require(old.get("ok") is True and old["result"].get("applied") is False,"Not a genuine retained preview")
    plan=old["result"]["planned_inventory"]
    require(plan["removed_forcing_blocks"] and all("commented" in row["action"] for row in plan["removed_forcing_blocks"]),"Retained preview is not the pre-repair commented-retirement policy")
    fixture_root=old_case/"fixture"
    model=fixture_root/"dedicated model";mdu=model/"channel.mdu"
    source=fixture_root/"incoming/north.pli";output=fixture_root/"new output"
    require(str(output)==old["result"]["directory"] and not output.exists(),"Retained request/output path differs or output already exists")
    require(fingerprints(model)==plan["input_files"] and sha(source.read_bytes())==plan["source"]["sha256"],"Retained original inputs changed; cannot compare policy fingerprints")
    before,dirs=snapshot(fixture_root),directories(fixture_root)
    api=PublicCLI(out/"retained-policy-preview-calls",no_site=True)
    row=api.invoke(["boundary","location-import",mdu,"--source",source,"--out",output,"--coordinates","as-is"])
    require(row.get("ok") is True,"Repaired preview failed on identical retained inputs")
    require(snapshot(fixture_root)==before and directories(fixture_root)==dirs and not output.exists(),"Read-only policy review changed historical inputs/output")
    require(row["result"]["input_sha256"]!=old["result"]["input_sha256"],"Old commented-retirement consent still authorizes physically different output")
    require(all("physically_deleted" in block["action"] for block in row["result"]["removed_forcing_blocks"]),"Repaired preview still retires BC records as comments")
    return {"passed":True,"retained_case":str(old_case),"old_input_sha256":old["result"]["input_sha256"],"new_input_sha256":row["result"]["input_sha256"],"identical_input_files":True,"historical_files_unchanged":True,"apply_performed":False}


def cases(root):
    """Build a new fixture for every trial; no reused mutated/retained source."""
    def setup(name, *, no_site=False):
        folder = root/name; folder.mkdir()
        return Fixture(folder/"fixture", real_mesh=True), PublicCLI(folder/"public-cli", no_site=no_site)
    result = {}
    def positive(name, replacement=True, upper=False):
        f,a = setup(name)
        if not replacement: f.write_source(label="new_line", basename="new_line.pli")
        if upper: f.mutate_mesh("only_uppercase_epsg")
        return preview_apply(a,f,replacement=replacement)
    result["replace_transform"] = lambda: positive("replace_transform")
    result["add_transform"] = lambda: positive("add_transform",False)
    result["actual_M3_uppercase_EPSG_code"] = lambda: positive("actual_M3_uppercase_EPSG_code",upper=True)
    for mutation in MESH_NEGATIVES:
        def run(kind=mutation):
            f,a = setup("mesh_"+kind); f.mutate_mesh(kind)
            return refusal(a,f)
        result["mesh_"+mutation] = run
    def missing_dependency():
        f,a = setup("missing_geo_dependency", no_site=True)
        row = refusal(a,f)
        require("depend" in json.dumps(row["public"]["error"]).lower(), "Missing geo stack not reported explicitly")
        return row
    result["missing_geo_dependency"] = missing_dependency
    def missing_consent():
        f,a = setup("missing_consent")
        return refusal(a,f,apply=True)
    result["missing_consent"] = missing_consent
    def wrong_hash():
        f,a = setup("wrong_hash")
        return refusal(a,f,apply=True,expect_sha256="0"*64,stale=True)
    result["wrong_hash"] = wrong_hash
    for mutation in STALE_CASES:
        def stale_case(kind=mutation):
            f,a = setup("stale_"+kind)
            preview = success(a,f)
            if kind in {"raw_source_comment","coordinate"}:
                path = f.source; info = path.stat(); raw = path.read_bytes()
                old,new = (b"INCOMING",b"incoming") if kind == "raw_source_comment" else (b"4.000000",b"4.100000")
                changed = raw.replace(old,new,1); require(changed != raw and len(changed)==len(raw), "Invalid same-size source control")
                path.write_bytes(changed); os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
            elif kind == "mesh_bytes":
                from netCDF4 import Dataset
                with Dataset(f.net,"a") as ds: ds.title = "Changed independent semantic-neutral mesh title"
            elif kind == "unknown_input":
                path=f.model/"unknown.bin"; path.write_bytes(path.read_bytes().replace(b"unknown",b"UNKNOWN"))
            elif kind == "output_path":
                f.out=f.root/"different new output"
            return refusal(a,f,apply=True,expect_sha256=preview["input_sha256"],stale=True)
        result["stale_"+mutation] = stale_case
    def output_overlap():
        f,a=setup("output_inside_source"); f.out=f.model/"new output"
        return refusal(a,f)
    result["output_inside_source"] = output_overlap
    def wrong_unit():
        f,a=setup("wrong_declared_target_unit")
        return refusal(a,f,target_unit="degree")
    result["wrong_declared_target_unit"] = wrong_unit
    for name, options in {
        "wrong_declared_target_crs": {"target_crs": "EPSG:32632"},
        "metre_is_not_cli_m": {"target_unit": "metre"},
        **{"missing_"+key: {key: None} for key in ("source_crs", "target_crs", "source_unit", "target_unit")},
    }.items():
        def invalid_declaration(label=name, kwargs=options):
            f,a=setup(label)
            return refusal(a,f,**kwargs)
        result[name]=invalid_declaration
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--stage-only",action="store_true",help="Stage inputs and run portable as-is checks; no public transform attempts")
    parser.add_argument("--retained-policy-preview",type=Path,help="Read-only comparison with genuine pre-repair preview-only testcase directory")
    args=parser.parse_args(argv)
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=False)
    save(out/"declaration.json",DECLARATION)
    report={"state":"not_completed","native_launches":0,"gui_launches":0,
            "numerical_validation":"not_performed","scientific_validation":"not_performed",
            "declaration":DECLARATION,"cases":{}}
    try:
        product_paths=sorted([*(ROOT/"src/dfm_cli").glob("boundary_location*.py"), ROOT/"src/dfm_cli/cli.py"])
        before={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in product_paths}
        report["source_hashes"]=before
        report["verifier_source_hashes"]={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in
            [*Path(__file__).parent.glob("verify_boundary_location_projection*.py"),
             ROOT/"tests/test_boundary_location_projection.py",
             Path(__file__).with_name("verify_boundary_location_crs_controls.py"),
             Path(__file__).with_name("channel_fixture.py")]}
        from tests import test_boundary_location_projection as portable_module
        portable_root=out/"portable"; portable_root.mkdir()
        token=portable_module.ARTIFACT_ROOT.set(portable_root)
        stream=io.StringIO()
        try:
            run=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(portable_module))
        finally:
            portable_module.ARTIFACT_ROOT.reset(token)
        (out/"portable.log").write_text(stream.getvalue(),encoding="utf-8")
        report["portable"]={"run":run.testsRun,"passed":run.wasSuccessful(),"skips":len(run.skipped),"errors":len(run.errors),"failures":len(run.failures)}
        api=PublicCLI(out/"discovery")
        help_row=api.invoke(["boundary","location-import","--help"])
        report["public_wired"]=all(flag in help_row["help"] for flag in ("--source-unit","--target-unit"))
        if args.stage_only:
            stage=Fixture(out/"staged-inputs",real_mesh=True)
            report["staged"]={"mdu":str(stage.mdu),"source":str(stage.source),"out":str(stage.out),"files":fingerprints(stage.model),"independent_NetFile_metadata":stage.mesh_metadata(),
                "preview_argv":["research/.venv/Scripts/python.exe","-B","-m","dfm_cli","boundary","location-import",str(stage.mdu),"--source",str(stage.source),"--out",str(stage.out),"--coordinates","transform","--source-crs","EPSG:4326","--target-crs","EPSG:32631","--source-unit","degree","--target-unit","m"]}
            report["state"]="prepared_public_projection_gate" if run.wasSuccessful() else "failed_portable_preparation"
        else:
            require(report["public_wired"],"Public transform units not wired; use --stage-only and wait for release")
            matrix=out/"public-cases"; matrix.mkdir()
            for name,case in cases(matrix).items():
                try: report["cases"][name]={"passed":True,"observation":case()}
                except Exception as error: report["cases"][name]={"passed":False,"error":str(error),"type":type(error).__name__,"traceback":traceback.format_exc()}
            report["case_summary"]=[{"case":name,"passed":row["passed"],
                "refusal_code":row.get("observation",{}).get("public",{}).get("error",{}).get("code"),
                "no_output_writes":row.get("observation",{}).get("no_output_writes"),"error":row.get("error")}
                for name,row in report["cases"].items()]
            save(out/"case-summary.json",report["case_summary"])
            report["failed_cases"]=[name for name,row in report["cases"].items() if not row["passed"]]
            report["state"]="passed_public_projection_gate" if run.wasSuccessful() and not report["failed_cases"] else "failed_public_projection_gate"
            if args.retained_policy_preview:
                report["retirement_policy_preview"]=review_retained_retirement_preview(args.retained_policy_preview,out)
        final_paths=sorted([*(ROOT/"src/dfm_cli").glob("boundary_location*.py"),ROOT/"src/dfm_cli/cli.py"])
        report["source_unchanged"]=before=={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in final_paths}
        if not report["source_unchanged"]: report["state"]="source_changed_during_gate"
    except Exception as error:
        report.update(state="failed_public_projection_gate",error=str(error),traceback=traceback.format_exc())
    save(out/"verification.json",report)
    print(json.dumps({"state":report["state"],"path":str(out/"verification.json"),"sha256":sha((out/"verification.json").read_bytes()),"failed_cases":report.get("failed_cases"),"error":report.get("error"),"native_launches":0}))
    return 0 if report["state"] in {"prepared_public_projection_gate","passed_public_projection_gate"} else 1


if __name__=="__main__":
    raise SystemExit(main())
