"""Independent frozen-wheel B03-ROWS 2026 five-case replay.

First invoke --out NEW for public-edit/input dry checks. Then use that SAME
folder with --execute-prepared --native-slot GRANTED to execute each prescribed
case exactly once. --profile-derivative makes the separately authorized minimal
common MDU correction, from the retained native2026 B03 control, before edits.
No product/test imports, model correction, tolerance adjustment or native retry.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import traceback
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[3]
STAGE=ROOT/"research/experiments/B03-ROWS-V-stage-01"
PACKAGE=ROOT/"research/experiments/PKG-G-B03-rows-01"
LEDGER=ROOT/"research/experiments/roadmap-coordinator-20261104/dispatch.json"
CLI=PACKAGE/"venv/Scripts/dfm.exe"
INSTALL=Path("C:/Program Files/Deltares/Delft3D FM Suite 2026.02 OpenHMWQ")
DECLARATION_SHA="25e2000a8dc84a48e630e02f53fd890b5a1419d974b71b2196d7162beb8e6fa3"
CASES=("manual-base","manual-collinear","manual-spike","candidate-collinear","candidate-spike")
UNIT="seconds since 2026-01-01 00:00:00 +00:00"
STATIONS=("east_south","east_north","west")
XY=((500115.,5700005.),(500115.,5700035.),(500005.,5700005.))
D=Decimal
PRIOR=ROOT/"research/experiments/B03-V-native-slot77-20261104-212609-c9f856ee"
FAILED=ROOT/"research/experiments/B03-ROWS-2026-V-20261105-011213-056e8727"
FAILED_NATIVE=ROOT/"research/experiments/B03-ROWS-2026-V-derivative-20261105-011733-3d6564e7"
CORRECTION=b"\n[waves]\nWaveModelNr = 0\n\n[trachytopes]\nTrtRou = N\n"
PROGRAM_LINE=b"Program = D-Flow FM\n"


def check(value,message):
    if not value: raise AssertionError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def snapshot(path):
    return {p.relative_to(path).as_posix():digest(p) for p in sorted(Path(path).rglob("*")) if p.is_file()}


def stage_snapshot():
    return {part:snapshot(STAGE/part) for part in ("native-plan","requests")}


def lease(out,label,sequence):
    raw=LEDGER.read_bytes();record=json.loads(raw);slot=record["native_slot"]
    check((slot["owner"],slot["sequence"])==("B03-ROWS-2026-V",sequence),"Native lease owner/sequence changed; no launch")
    (out/(label+"-lease.json")).write_bytes(raw)
    return {"owner":slot["owner"],"sequence":slot["sequence"],"ledger_sha256":hashlib.sha256(raw).hexdigest(),"checked_at_utc":datetime.now(timezone.utc).isoformat()}


def call(out,label,args,*,native=False,native_slot=None):
    row={"argv":[str(CLI),*map(str,args)],"cwd":str(out),"native":native}
    if native:
        check(type(native_slot) is int,"An explicitly granted native slot is required")
        row["lease"]=lease(out,label,native_slot)  # immediately before THIS native call
    env=dict(os.environ,PYTHONNOUSERSITE="1");env.pop("PYTHONPATH",None)
    try:
        process=subprocess.run(row["argv"],cwd=out,env=env,capture_output=True,timeout=90)
        stdout,stderr,code=process.stdout,process.stderr,process.returncode
    except subprocess.TimeoutExpired as error:
        (out/(label+".stdout")).write_bytes(error.stdout or b"")
        (out/(label+".stderr")).write_bytes(error.stderr or b"")
        save(out/(label+".call.json"),dict(row,error="controller subprocess timeout; no retry"))
        raise
    (out/(label+".stdout")).write_bytes(stdout);(out/(label+".stderr")).write_bytes(stderr)
    row.update(returncode=code)
    save(out/(label+".call.json"),row)
    response=json.loads(stdout)
    check(code==0 and response.get("protocol_version")==2 and response.get("ok") is True,f"{label}: public CLI failure {response}")
    return response["result"]


def blocks(raw):
    """Independent small BC lexer: fields kept ordered, Decimal rows exact."""
    check(not raw.startswith(b"\xef\xbb\xbf"),"Unexpected BOM in predeclared native fixture")
    headers=list(re.finditer(rb"(?mi)^\[([^\]\r\n]+)\][ \t]*\r?$",raw))
    result={}
    for i,head in enumerate(headers):
        end=headers[i+1].start() if i+1<len(headers) else len(raw)
        if head.group(1).lower()!=b"forcing": continue
        fields=[];rows=[]
        for line in raw[head.end():end].decode().splitlines():
            line=line.split("#",1)[0].strip()
            if not line or line.startswith(";"): continue
            if "=" in line:
                key,value=line.split("=",1);fields.append((key.strip().lower(),value.strip()))
            else:
                words=line.split();check(len(words)==2,"Not an independently supported two-column table")
                rows.append(tuple(D(v.replace("D","E").replace("d","e")) for v in words))
        names=[v for k,v in fields if k=="name"];check(len(names)==1 and names[0] not in result,"Ambiguous BC name")
        check([v for k,v in fields if k=="unit"]==[UNIT,"m"],"Unexpected units/UTC origin")
        check(dict(fields)["function"]=="timeseries" and dict(fields)["time-interpolation"]=="linear","Wrong boundary function")
        check(len(rows)>=2 and all(a[0]<b[0] for a,b in zip(rows,rows[1:])),"Duplicate/reversed time knots")
        result[names[0]]={"fields":fields,"rows":rows,"raw":raw[head.start():end]}
    check(set(result)=={"west_0001","west_0002","east_0002","east_0001"},"Wrong boundary graph")
    return result


def interpolation(rows,t):
    for a,b in zip(rows,rows[1:]):
        if a[0]<=t<=b[0]: return a[1]+(t-a[0])*(b[1]-a[1])/(b[0]-a[0])
    raise AssertionError("Insufficient signal coverage")


def package_check():
    record=json.loads((PACKAGE/"verification.json").read_bytes())
    wheel=PACKAGE/"wheels"/record["wheel"]
    check(record["state"]=="passed" and digest(wheel)==record["wheel_sha256"],"Frozen wheel drift")
    with ZipFile(wheel) as archive:
        files=[name for name in archive.namelist() if name.startswith("dfm_cli/") and not name.endswith("/")]
        for name in files:
            check((PACKAGE/"venv/Lib/site-packages"/name).read_bytes()==archive.read(name),"Installed wheel payload changed: "+name)
    return {"wheel_sha256":digest(wheel),"cli_sha256":digest(CLI),"verified_installed_files":len(files)}


def mdu_fields(raw):
    result={};section=None
    for line in raw.decode().splitlines():
        line=line.split("#",1)[0].strip()
        if line.startswith("[") and line.endswith("]"): section=line[1:-1].lower()
        elif "=" in line and section:
            key,value=line.split("=",1);address=section+"/"+key.strip().lower()
            check(address not in result,"Duplicate MDU address")
            result[address]=value.strip()
    return result


def correction_source():
    import netCDF4 as nc
    import numpy as np
    source=PRIOR/"authored-model/model.mdu";staged=PRIOR/"control-native/model/model.mdu"
    manifest=PRIOR/"control-native/manifest.json";record=json.loads(manifest.read_bytes())
    check(record["state"]=="completed" and record["returncode"]==0,"Prior native control not completed")
    check(source.read_bytes()==staged.read_bytes(),"Prior native MDU is not the source control")
    fields=mdu_fields(source.read_bytes())
    check(fields["general/program"]=="D-Flow FM" and fields["waves/wavemodelnr"]=="0" and fields["trachytopes/trtrou"]=="N" and fields["time/refdate"]=="20260101" and fields["time/tstop"]=="120","Prior source values/clock differ")
    clock=PRIOR/"control-native/model/output/model_his.nc"
    with nc.Dataset(clock) as ds:
        check(np.array_equal(ds["time"][:],np.arange(0,121,10)),"Prior native control lacks thirteen actual ticks")
        dates=nc.num2date(ds["time"][:],ds["time"].units,getattr(ds["time"],"calendar","standard"))
        check(dates[0].isoformat()=="2026-01-01T00:00:00" and dates[-1].isoformat()=="2026-01-01T00:02:00","Prior native UTC origin differs")
    return {"path":str(source),"mdu_sha256":digest(source),"native_staged_mdu_sha256":digest(staged),"manifest_sha256":digest(manifest),"raw_history_sha256":digest(clock),
            "prior_state":"completed","prior_returncode":0,"actual_CF_samples":13,"actual_first":"2026-01-01T00:00:00","actual_final":"2026-01-01T00:02:00",
            "sourced_settings":{"general/program":"D-Flow FM","waves/wavemodelnr":"0","trachytopes/trtrou":"N"},"limits":"Prior native data sources explicit identity/profile settings only; no new physics or owned-handle acceptance is borrowed."}


def corrected_mdu(original,identity):
    fields=mdu_fields(original)
    check("waves/wavemodelnr" not in fields and "trachytopes/trtrou" not in fields,"Correction fields already exist")
    corrected=original;offset=None
    if identity:
        check("general/program" not in fields,"Native identity already exists")
        found=list(re.finditer(rb"(?mi)^\[General\][ \t]*\r?\n",original))
        check(len(found)==1,"Require one exact General header")
        offset=found[0].end();corrected=original[:offset]+PROGRAM_LINE+original[offset:]
    corrected+=CORRECTION
    added={k:v for k,v in mdu_fields(corrected).items() if k not in fields}
    expected={"waves/wavemodelnr":"0","trachytopes/trtrou":"N"}
    if identity: expected["general/program"]="D-Flow FM"
    check(added==expected and all(mdu_fields(corrected)[k]==v for k,v in fields.items()),"Correction changed an original MDU value")
    restored=corrected[:-len(CORRECTION)]
    if identity: restored=restored[:offset]+restored[offset+len(PROGRAM_LINE):]
    check(restored==original,"Removing only added spans did not restore exact original bytes")
    return corrected,{"program_insert_original_offset":offset,"program_insert_ascii":PROGRAM_LINE.decode() if identity else None,
                      "append_original_offset":len(original),"append_ascii":CORRECTION.decode(),"added_bytes":len(CORRECTION)+(len(PROGRAM_LINE) if identity else 0),
                      "original_bytes_preserved_in_order":True,"removing_added_spans_restores_original_exactly":True,"changed_original_bytes":0}


def native_load_identity_audit(target):
    """Independent static engine identity plus complete prior metadata comparison."""
    import netCDF4 as nc
    import numpy as np
    prior=PRIOR/"authored-model"
    expected=mdu_fields((prior/"model.mdu").read_bytes());actual=mdu_fields((target/"model.mdu").read_bytes())
    differences={key:{"prior":expected.get(key),"derivative":actual.get(key)} for key in sorted(set(expected)|set(actual)) if expected.get(key)!=actual.get(key)}
    check(differences=={"geometry/netfile":{"prior":"mesh_net.nc","derivative":"mesh.nc"}},"Unexplained MDU metadata difference vs accepted2026 control")
    check(actual["general/program"]=="D-Flow FM" and actual["general/filetype"]=="modelDef" and actual["general/fileversion"]=="1.09","Static native identity gate failed")
    def general(raw):
        headers=list(re.finditer(rb"(?mi)^\[([^\]\r\n]+)\][ \t]*\r?$",raw))
        return mdu_fields(raw[:headers[1].start()])
    a=(prior/"boundaries.bc").read_bytes();b=(target/"shared.bc").read_bytes()
    check(general(a)==general(b)=={"general/fileversion":"1.01","general/filetype":"boundConds"},"BC General metadata differs")
    old,new=blocks(a),blocks(b)
    check(all(old[key]["fields"]==new[key]["fields"] for key in old),"BC function/units/name/quantity/interpolation metadata differs")
    check(general((prior/"boundaries.ext").read_bytes())==general((target/"boundaries.ext").read_bytes()),"EXT version/type metadata differs")
    lines=(target/"observations.xyn").read_text().splitlines()
    check([line.split()[2] for line in lines]==list(STATIONS),"Observation name metadata differs from declaration")
    pli={}
    for label in ("west","east"):
        path=target/(label+".pli");data=[line.split("#",1)[0].strip() for line in path.read_text().splitlines() if line.strip()]
        check(data[0]==label and data[1].split()==["2","2"] and len(data)==4,"PLI identity/row/column metadata invalid")
        values=[list(map(float,line.split())) for line in data[2:]]
        check(all(len(row)==2 and np.isfinite(row).all() for row in values),"PLI XY metadata invalid")
        check({label+"_0001",label+"_0002"}<=set(new),"PLI support identities not covered by BC")
        pli[label]={"path":path.name,"rows":2,"columns":2,"support_ids":[label+"_0001",label+"_0002"]}
    def canonical(path):
        with nc.Dataset(path) as ds:
            points=list(zip(map(float,ds["mesh2d_node_x"][:]),map(float,ds["mesh2d_node_y"][:])))
            f,e=ds["mesh2d_face_nodes"],ds["mesh2d_edge_nodes"]
            faces=sorted(tuple(sorted(points[int(i)-int(f.start_index)] for i in row.compressed())) for row in np.ma.asarray(f[:]))
            edges=sorted(tuple(sorted(points[int(i)-int(e.start_index)] for i in row)) for row in e[:])
            mapping=ds["projected_coordinate_system"]
            codes=[mapping.getncattr(k) for k in mapping.ncattrs() if k.casefold() in {"epsg","epsg_code"}]
            check(codes and all(str(value) in {"32631","EPSG:32631"} for value in codes) and ds["mesh2d_node_z"].units=="m" and ds["mesh2d_node_z"].positive=="up","Mesh CRS/bed unit/sign differs")
            check(mapping.grid_mapping_name=="transverse_mercator" and all(ds["mesh2d_node_"+axis].units=="m" and ds["mesh2d_node_"+axis].standard_name=="projection_"+axis+"_coordinate" for axis in ("x","y")),"Mesh XY axis/unit/projection metadata differs")
            check(float(ds["mesh2d_node_z"][:].min())==float(ds["mesh2d_node_z"][:].max())==-3,"Bed differs")
            return sorted(points),faces,edges
    check(canonical(prior/"mesh_net.nc")==canonical(target/"mesh.nc"),"Physical node/face/edge geometry differs from accepted2026 control")
    fortran=ROOT/"research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90"
    source=fortran.read_text();check("call prop_get(md_ptr, bnam, 'Program', program, success)" in source and "Wrong model definition file." in source,"Pinned source Program gate missing")
    lock=json.loads((ROOT/"research/sources.lock.json").read_bytes())
    return {"state":"passed_static_native_identity_and_metadata_audit","all_MDU_fields_compared":len(set(expected)|set(actual)),"all_original_fields_except_documented_additions_preserved":True,
            "remaining_MDU_differences":differences,"remaining_difference_reason":"Contained relative mesh filename differs; actual EPSG, bed and canonical nodes/faces/edges equal despite storage ordering. No mesh/BC/time/initial-state edits.",
            "BC_General":general(b),"all_BC_forcing_fields_match_prior":True,"BC_fields_by_support":{key:row["fields"] for key,row in new.items()},
            "prior_BC_order":list(old),"derivative_BC_order":list(new),"intentional_signal_differences":"Prescribed 2026 ramps/insertions/spike and selected east_0001 last atEOF; numeric tables remain exactly the authored manual/CLI controls, not copied from prior zero forcing.",
            "EXT_General_metadata_matches":True,"PLI_metadata":pli,"canonical_mesh_geometry_equal":True,"program_gate_source":{"path":str(fortran),"sha256":digest(fortran),"read_line":819,"rejection_line":824,"commit":lock["repositories"]["Delft3D"]["commit"]},
            "limitations":"Static source is a pinned reference, not an identified commit of the installed binary. Native load/outputs remain untested on this derivative."}


def standalone_profile(out,name,mdu):
    """Installed isolated interpreter calls validation/profile, NEVER run.prepare."""
    script="""import json,sys,subprocess
from pathlib import Path
from unittest.mock import patch
with patch.object(subprocess,'Popen',side_effect=AssertionError('Offline profile must never launch a process')):
    import dfm_cli.runs as runs
    from dfm_cli.model import Mdu,validate_mdu
    model=Mdu(Path(sys.argv[1])); validation=validate_mdu(model)
    assert not validation['issues'],validation['issues']
    profile=runs.profile(validation,model,'short')
    print(json.dumps({'state':'passed_standalone_offline_profile','issues':validation['issues'],'clock':validation['clock'],'profile':profile,'runs_module':runs.__file__,'native_launch_calls':0}))
"""
    argv=[str(PACKAGE/"venv/Scripts/python.exe"),"-I","-B","-c",script,str(mdu)]
    env=dict(os.environ,PYTHONNOUSERSITE="1");env.pop("PYTHONPATH",None)
    process=subprocess.run(argv,cwd=out,env=env,capture_output=True,timeout=30)
    (out/(name+"-offline-profile.stdout")).write_bytes(process.stdout);(out/(name+"-offline-profile.stderr")).write_bytes(process.stderr)
    save(out/(name+"-offline-profile.call.json"),{"argv":argv,"returncode":process.returncode,"native_launches":0})
    check(process.returncode==0,"Standalone offline runs.profile failure: "+process.stderr.decode(errors="replace"))
    result=json.loads(process.stdout)
    check(Path(result["runs_module"]).resolve()==(PACKAGE/"venv/Lib/site-packages/dfm_cli/runs.py").resolve(),"Offline check imported live product instead of frozen wheel")
    check(result["state"]=="passed_standalone_offline_profile" and result["native_launch_calls"]==0,"Offline profile not proven")
    return result


def prepare(out,*,derivative=False,native_identity=False):
    from netCDF4 import Dataset
    check(digest(STAGE/"native-plan/declaration.json")==DECLARATION_SHA,"Pinned declaration differs")
    declaration=json.loads((STAGE/"native-plan/declaration.json").read_bytes())
    check(declaration["native_cases_prospective"]==list(CASES) and declaration["UTC_epoch"]=="2026-01-01T00:00:00+00:00","Different native design")
    before=stage_snapshot();pkg=package_check()
    report={"state":"dry_check_incomplete","slot":None,"owner":"B03-ROWS-2026-V","stage_before":before,"package":pkg,"runner_sha256":digest(__file__),"declaration_sha256":DECLARATION_SHA,"cases":{},
            "thresholds":{"collinear_waterlevel_atol_m":1e-6,"rtol":0,"target_east_south_spike_30_120s_greater_than_m":1e-4},"native_calls":0}
    failed_before=snapshot(FAILED) if derivative else None
    failed_native_before=snapshot(FAILED_NATIVE) if native_identity else None
    if derivative:
        report["profile_correction_source"]=correction_source()
        report["common_added_MDU_bytes_ascii"]=CORRECTION.decode()
        report["common_program_insertion_ascii"]=PROGRAM_LINE.decode() if native_identity else None
        report["prior_attempt"]={"state":"native_not_reached","failure_phase":"public_run_profile_preflight","code":"missing_setting","setting":"waves/wavemodelnr",
            "native_processes_created":0,"native_manifest_created":False,"verification_sha256":digest(FAILED/"verification.json"),"path":str(FAILED),
            "not_a_native_launch_failure":True}
        if native_identity:
            failed_manifest=FAILED_NATIVE/"run-manual-base/manifest.json"
            prior_native=json.loads(failed_manifest.read_bytes())
            check(prior_native["state"]=="failed" and prior_native["returncode"]==1,"Prior native failure evidence changed")
            report["prior_native_attempt"]={"state":"native_reached_input_definition_rejected","slot":147,"native_returncode":1,"manifest_sha256":digest(failed_manifest),"path":str(FAILED_NATIVE),"boundary_consumption":"not_reached","no_correction_to_failed_artifacts":True}
    (out/"declaration.json").write_bytes((STAGE/"native-plan/declaration.json").read_bytes())
    (out/"requests").mkdir();(out/"cases").mkdir()
    base=STAGE/"native-plan/manual-base";base_bc=blocks((base/"shared.bc").read_bytes())
    with Dataset(base/"mesh.nc") as mesh:
        check(digest(base/"mesh.nc")==declaration["geometry"]["sha256"],"Wrong known mesh")
        check(len(mesh.dimensions["mesh2d_nNodes"])==65 and len(mesh.dimensions["mesh2d_nFaces"])==48,"Wrong channel dimensions")
        check(float(mesh["mesh2d_node_z"][:].min())==float(mesh["mesh2d_node_z"][:].max())==-3,"Wrong known bed")
        check(mesh["projected_coordinate_system"].EPSG_code=="EPSG:32631","Wrong actual mesh EPSG")
    for name in CASES:
        stage_name=name if name.startswith("manual") else name+"-UNAPPLIED"
        source=STAGE/"native-plan"/stage_name;target=out/"cases"/name
        shutil.copytree(source,target)
        if derivative:
            original=(target/"model.mdu").read_bytes()
            corrected,byte_diff=corrected_mdu(original,native_identity)
            (target/"model.mdu").write_bytes(corrected)
        initial=snapshot(target)
        mdu=(target/"model.mdu").read_text()
        for token in ("RefDate=20260101","TZone=0","TStop=120","StartDateTime=20260101000000","StopDateTime=20260101000200","HisInterval=10","MapInterval=10","RstInterval=120","BedlevType=3"):
            check(token in mdu,"Wrong authored clock/settings: "+token)
        if name.startswith("candidate"):
            check({k:v for k,v in initial.items() if k!="model.mdu"}=={k:v for k,v in snapshot(base).items() if k!="model.mdu"},"Unapplied candidate is not the known base")
            check((target/"model.mdu").read_bytes()==(corrected_mdu((base/"model.mdu").read_bytes(),native_identity)[0] if derivative else (base/"model.mdu").read_bytes()),"Candidate MDU correction differs")
            kind=name.split("-",1)[1];req_name="collinear-insert-delete.json" if kind=="collinear" else "analytic-spike.json"
            request=out/"requests"/req_name
            if not request.exists(): shutil.copyfile(STAGE/"requests"/req_name,request)
            req=json.loads(request.read_bytes())
            check(req["time_unit"]==UNIT and req["value_unit"]=="m" and [D(v) for v in req["delete"]]==[D(60)],"Wrong actual staged request")
            check([(D(v["time"]),D(v["value"])) for v in req["insert"]]==[(D(t),D(v)) for t,v in ((15,".015"),(45,".045" if kind=="collinear" else ".105"),(75,".075"),(105,".105"))],"Changed request design")
            args=["boundary","series-rows",target/"model.mdu","--point","east_0001","--rows",request]
            preview=call(out,name+"-preview",args)
            check(snapshot(target)==initial and preview["applied"] is False,"Preview wrote model")
            applied=call(out,name+"-apply",[*args,"--apply","--expect-sha256",preview["input_sha256"]])
            check(applied["applied"] is True and {k for k,v in initial.items() if snapshot(target).get(k)!=v}=={"shared.bc"},"Wrong public edit scope")
        actual=blocks((target/"shared.bc").read_bytes());kind=name.split("-",1)[1]
        manual=blocks((STAGE/"native-plan"/("manual-"+kind)/"shared.bc").read_bytes())
        check({k:(v["fields"],v["rows"]) for k,v in actual.items()}=={k:(v["fields"],v["rows"]) for k,v in manual.items()},"Candidate/manual physical tables differ")
        check(all(actual[k]["raw"]==base_bc[k]["raw"] for k in actual if k!="east_0001"),"Unselected signal bytes changed")
        check({k:v for k,v in snapshot(target).items() if k not in {"shared.bc","model.mdu"}}=={k:v for k,v in snapshot(base).items() if k not in {"shared.bc","model.mdu"}},"Non-BC fixtures differ")
        check((target/"model.mdu").read_bytes()==(corrected_mdu((base/"model.mdu").read_bytes(),native_identity)[0] if derivative else (base/"model.mdu").read_bytes()),"Model time/initial state/geometry correction is not identical across cases")
        rows=actual["east_0001"]["rows"]
        if kind in {"base","collinear"}:
            check(all(interpolation(rows,D(t))==D(t)/1000 for t in range(121)),"Collinear analytical oracle fails on INPUT tables")
        else:
            check(interpolation(rows,D(45))-D(".045")==D(".06") and interpolation(rows,D(60))-D(".060")==D(".03"),"Spike input design fails")
        offline_before=snapshot(target)
        validation=call(out,name+"-model-validate",["model","validate",target/"model.mdu"])
        check(not validation["issues"],"Public model validation issues")
        offline=standalone_profile(out,name,target/"model.mdu")
        check(snapshot(target)==offline_before,"Offline checker changed inputs")
        identity_audit=native_load_identity_audit(target) if native_identity else {"state":"not_performed"}
        report["cases"][name]={"inputs":snapshot(target),"tables":{key:[[str(t),str(v)] for t,v in item["rows"]] for key,item in actual.items()},"physical_tables_match_manual":True,
            "offline_validation":validation,"standalone_profile":offline,"profile_derivative":derivative,
            "static_native_identity_audit":identity_audit,
            "MDU_byte_diff":{"original_sha256":digest(source/"model.mdu"),"corrected_sha256":digest(target/"model.mdu"),**(byte_diff if derivative else {"added_bytes":0})}}
    check(stage_snapshot()==before,"Original staged inputs changed")
    if derivative:
        check(snapshot(FAILED)==failed_before,"Failed attempt evidence changed")
        report["failed_attempt_unchanged"]=True
        if native_identity:
            check(snapshot(FAILED_NATIVE)==failed_native_before,"Failed native attempt evidence changed")
            report["failed_native_attempt_unchanged"]=True
        save(out/"profile-correction.json",{"source":report["profile_correction_source"],"common_append_ascii":CORRECTION.decode(),"common_program_insertion_ascii":report["common_program_insertion_ascii"],"cases":{k:v["MDU_byte_diff"] for k,v in report["cases"].items()},
            "explanation":"Add only explicit Program identity, Waves-disabled and trachytopes-disabled metadata as in the accepted2026 B03 control. Original bytes restore exactly by removing documented insertion/append spans. All clock, initial state, mesh and boundary inputs are unchanged apart from prescribed row edits. No failed artifact is edited.","native_launches":0})
    report["state"]="dry_checks_passed_no_native";save(out/"dry-check.json",report)
    print(json.dumps({"state":report["state"],"path":str(out/"dry-check.json"),"native_calls":0}),flush=True)


def owned(manifest):
    n=manifest["ownership"]["normal_exit"];t=n["member_trace"];members=t["members"]
    check(manifest["state"]=="completed" and manifest["returncode"]==0,"Native state/exit failure")
    check(all(n.get(k) is True for k in ("root_exit_confirmed","job_empty","all_owned_members_exit_confirmed")),"Owned terminal proof incomplete")
    check(n["termination_attempted"] is False and n["unobserved_member_count"]==0,"Forced/unobserved member")
    values=n["job_accounting"]["values"];check(values["ActiveProcesses"]==0 and values["TotalProcesses"]==len(members)==n["confirmed_member_exit_count"],"Lifetime count/retained handles mismatch")
    check(n["job_members"]["pids"]==[] and n["job_pids_after"]==[],"Job not empty")
    for member in members:
        e=member["exit"]
        check(member["identity"]==member["exit_identity"] and member["retained_until_exit_check"] is True,"Retained PID/birth identity failure")
        check(type(member["capture_wait_result"]) is int and member["capture_wait_result"]==258 and member["job_membership"]["is_member"] is True,"No prospective same-Job member")
        check(e["state"]=="signalled" and e["same_retained_handle"] is True and type(e["wait_result"]) is int and e["wait_result"]==0 and e["exit_code_query"]=="captured" and type(e["exit_code"]) is int and e["exit_code"]==0,"Member handle wait/exit code failed")
    return {"retained_handles":len(members),"ever_assigned":values["TotalProcesses"],"empty_job":True,"all_member_exits_confirmed":True,"raw_ownership":manifest["ownership"]}


def outputs(run):
    folder=run/"model/output"
    paths=sorted(folder.glob("*.nc"))
    expected={"model_his.nc","model_map.nc","model_20260101_000000_rst.nc","model_20260101_000200_rst.nc"}
    check({p.name for p in paths}==expected,"Unexpected raw output dataset inventory")
    return {p.name:p for p in paths}


def clocks(run):
    import netCDF4 as nc
    import numpy as np
    evidence={}
    for name,path in outputs(run).items():
        with nc.Dataset(path) as ds:
            v=ds["time"];calendar=getattr(v,"calendar","standard");raw=v[:]
            check(not np.ma.getmaskarray(raw).any(),"Masked CF clock")
            dates=nc.num2date(raw,v.units,calendar=calendar)
            seconds=[(d-dates[0].replace(year=2026,month=1,day=1,hour=0,minute=0,second=0,microsecond=0)).total_seconds() for d in dates]
            expected=[0] if "000000_rst" in name else [120] if "000200_rst" in name else list(range(0,121,10))
            check(seconds==expected and all(d.year==2026 and d.month==1 and d.day==1 for d in dates),"Actual CF dates/ticks do not match2026 0..120s")
            evidence[name]={"sha256":digest(path),"time_units":v.units,"calendar":calendar,"seconds":seconds,"actual_CF_dates":[d.isoformat() for d in dates]}
            wl=next((k for k in ("waterlevel","mesh2d_s1","s1") if k in ds.variables),None)
            check(wl is not None and ds[wl].units=="m" and ds[wl].standard_name=="sea_surface_height","Waterlevel variable/units unavailable")
            if name=="model_his.nc":
                names=[str(s).rstrip("\0 ") for s in nc.chartostring(ds["station_name"][:])]
                check(names==list(STATIONS),"Unexpected station identities/order")
                check(np.array_equal(ds["station_x_coordinate"][:],np.array(XY)[:,0]) and np.array_equal(ds["station_y_coordinate"][:],np.array(XY)[:,1]),"Observation coordinates differ")
                evidence[name]["station_ids"]=names
    return evidence


def array_equal(a,b):
    import numpy as np
    return np.array_equal(a,b,equal_nan=True) if a.dtype.kind in "fc" and b.dtype.kind in "fc" else np.array_equal(a,b)


def exact_pair(left,right):
    import netCDF4 as nc
    import numpy as np
    evidence={}
    for name,a in outputs(left).items():
        b=outputs(right)[name]
        with nc.Dataset(a) as x,nc.Dataset(b) as y:
            check(set(x.dimensions)==set(y.dimensions) and all(len(x.dimensions[k])==len(y.dimensions[k]) for k in x.dimensions),"Dataset dimensions differ")
            check(set(x.variables)==set(y.variables),"Dataset variable inventory differs")
            names=[]
            for key,v in x.variables.items():
                w=y[key];va,wa=np.ma.asarray(v[:]),np.ma.asarray(w[:])
                check(v.dimensions==w.dimensions and v.dtype==w.dtype and va.shape==wa.shape,"Variable layout differs: "+name+"/"+key)
                check(np.array_equal(np.ma.getmaskarray(va),np.ma.getmaskarray(wa)) and array_equal(va.data,wa.data),"Exact candidate/manual arrays differ: "+name+"/"+key)
                check(set(v.ncattrs())==set(w.ncattrs()) and all(array_equal(np.asarray(v.getncattr(k)),np.asarray(w.getncattr(k))) for k in v.ncattrs()),"Variable attributes differ: "+key)
                names.append(key)
            evidence[name]={"variables_exact":names,"count":len(names),"manual_sha256":digest(a),"candidate_sha256":digest(b),"global_attributes_not_an_array_gate":True}
    return evidence


def waterlevel_pair(base,changed,*,spike=False):
    import netCDF4 as nc
    import numpy as np
    result={}
    for name,a in outputs(base).items():
        with nc.Dataset(a) as x,nc.Dataset(outputs(changed)[name]) as y:
            key=next(k for k in ("waterlevel","mesh2d_s1","s1") if k in x.variables)
            v,w=np.ma.asarray(x[key][:]),np.ma.asarray(y[key][:])
            check(v.shape==w.shape and np.array_equal(np.ma.getmaskarray(v),np.ma.getmaskarray(w)),"Waterlevel masks/shapes differ")
            delta=np.abs(v-w);maximum=float(delta.max())
            if not spike: check(np.allclose(v,w,rtol=0,atol=1e-6,equal_nan=True),"Analytical collinear output gate FAILED; no fixture/tolerance change")
            result[name]={"maximum_absolute_waterlevel_difference_m":maximum}
            if spike and name=="model_his.nc":
                target=np.asarray(delta)[3:13,:]
                result[name]["station_30_120s_maximum_m"]={station:float(target[:,i].max()) for i,station in enumerate(STATIONS)}
                check(result[name]["station_30_120s_maximum_m"]["east_south"]>1e-4,"Target east_south spike gate FAILED; no threshold change")
    return result


def execute(out,native_slot):
    dry=json.loads((out/"dry-check.json").read_bytes())
    check(dry["state"]=="dry_checks_passed_no_native" and dry["runner_sha256"]==digest(__file__),"Dry-check runner drift")
    check(stage_snapshot()==dry["stage_before"] and package_check()==dry["package"],"Stage/wheel drift after dry checks")
    check(not (out/"native-started.json").exists() and not any((out/("run-"+name)).exists() for name in CASES),"No native retries/reused directories")
    check(all(snapshot(out/"cases"/name)==dry["cases"][name]["inputs"] for name in CASES),"Prepared model drift")
    check(type(native_slot) is int,"Execute requires an explicitly granted slot")
    lease(out,"execution-entry",native_slot)
    save(out/"native-started.json",{"slot":native_slot,"time_utc":datetime.now(timezone.utc).isoformat()})
    report={"state":"incomplete","native_slot":native_slot,"owner":"B03-ROWS-2026-V","cases":{},"comparisons":{},"launches":[],"dry_check_sha256":digest(out/"dry-check.json")}
    try:
        for name in CASES:
            print(json.dumps({"launching":name,"slot":native_slot}),flush=True)
            run=out/("run-"+name)
            report["launches"].append(name);save(out/"verification.json",report)
            result=call(out,name+"-native",["run","start",out/"cases"/name/"model.mdu","--route","direct","--profile","short","--install",INSTALL,"--out",run,"--timeout","60"],native=True,native_slot=native_slot)
            manifest=json.loads((run/"manifest.json").read_bytes())
            terminal=owned(manifest)
            report["cases"][name]={"manifest_sha256":digest(run/"manifest.json"),"state":result["state"],"returncode":manifest["returncode"],"owned":terminal,"CF_outputs":clocks(run),"native_executable_sha256":manifest["executable_sha256"]}
            check(snapshot(out/"cases"/name)==dry["cases"][name]["inputs"],"Public run modified source inputs")
            if name=="manual-collinear": report["comparisons"]["manual_collinear_vs_base"]=waterlevel_pair(out/"run-manual-base",run)
            if name=="manual-spike": report["comparisons"]["manual_spike_vs_base"]=waterlevel_pair(out/"run-manual-base",run,spike=True)
            if name.startswith("candidate"):
                kind=name.split("-",1)[1]
                report["comparisons"][name+"_vs_manual_exact"]=exact_pair(out/("run-manual-"+kind),run)
                report["comparisons"][name+"_vs_base"]=waterlevel_pair(out/"run-manual-base",run,spike=kind=="spike")
            check(stage_snapshot()==dry["stage_before"],"Original stage inputs changed")
            save(out/"verification.json",report)
            print(json.dumps({"terminal":name,"owned_members":terminal["retained_handles"],"empty_job":True}),flush=True)
        report["state"]="passed_five_case_independent_native_gate"
    except Exception as error:
        report.update(state="failed_stopped_no_retry",failure={"type":type(error).__name__,"message":str(error),"traceback":traceback.format_exc(),"classification":"native_or_output_failure; inspect preserved raw evidence before another launch"})
    finally:
        report["stage_unchanged"]=stage_snapshot()==dry["stage_before"]
        save(out/"verification.json",report)
        terminal_files={}
        for name in report["launches"]:
            p=out/("run-"+name)/"manifest.json"
            if p.exists():
                m=json.loads(p.read_bytes());terminal_files[name]={"state":m["state"],"manifest_sha256":digest(p),"job_empty":m.get("ownership",{}).get("normal_exit",{}).get("job_empty"),"all_owned_members_exit_confirmed":m.get("ownership",{}).get("normal_exit",{}).get("all_owned_members_exit_confirmed")}
        released=bool(terminal_files) and all(v["state"] in {"completed","failed","timed_out","cancelled"} and v["job_empty"] is True and v["all_owned_members_exit_confirmed"] is True for v in terminal_files.values())
        save(out/"slot-release.json",{"slot":native_slot,"owner":"B03-ROWS-2026-V","no_more_launches":True,"all_launched_jobs_terminal_and_owned":released,"manifests":terminal_files,"ledger_not_modified_by_verifier":True})
    print(json.dumps({"state":report["state"],"path":str(out/"verification.json"),"sha256":digest(out/"verification.json"),"failure":report.get("failure")}),flush=True)
    return 0 if report["state"]=="passed_five_case_independent_native_gate" else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",required=True,type=Path);parser.add_argument("--execute-prepared",action="store_true")
    parser.add_argument("--profile-derivative",action="store_true");parser.add_argument("--native-slot",type=int)
    parser.add_argument("--native-identity-derivative",action="store_true")
    args=parser.parse_args(argv);out=args.out.resolve()
    check(out.name.startswith("B03-ROWS-2026-V-"),"Use a fresh owned experiment prefix")
    if args.execute_prepared: return execute(out,args.native_slot)
    out.mkdir(parents=True,exist_ok=False)
    check(not args.native_identity_derivative or args.profile_derivative,"Native identity derivative requires explicit common profile derivative")
    try: prepare(out,derivative=args.profile_derivative,native_identity=args.native_identity_derivative)
    except Exception as error:
        save(out/"dry-failure.json",{"state":"fixture_or_public_edit_failure_no_native","type":type(error).__name__,"message":str(error),"traceback":traceback.format_exc(),"native_calls":0});raise
    return 0


if __name__=="__main__": raise SystemExit(main())
