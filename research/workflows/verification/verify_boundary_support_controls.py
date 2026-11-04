"""Hand-authored east/west 120s controls for future B10 native G. NO launcher.

DC harmonic means and constant linear series make prescribed values explicit.
Manual references never call product editors. Optional candidates use only the
selected file-only interface, then compare against these independent references.
"""
import hashlib
import json
from pathlib import Path
import shutil

from .channel_fixture import write_mesh
from .verify_boundary_support_fixture import GENERAL,UNIT,harmonic,linear,signals,semantic,snapshot,save,require,sha,replacement_reference,numeric_tail_comments

DECLARATION={"scope":"future G reference package only; no native authorization or launcher",
    "mesh":{"cells":48,"nodes":65,"edges":112,"length_m":120,"width_m":40,"bed_m":-3,"CRS":"EPSG:32631"},
    "vertical_datum":"synthetic local zero; not a realized geodetic vertical datum",
    "clock_UTC":{"origin":"2026-01-01T00:00:00Z","duration_s":120,"output_step_s":10},
    "functions":"harmonic DC rows period=0 minutes, phase=0deg; explicit mean in m; linear constant rows at0/60/120s with own UTC epoch",
    "base_east_means_m":{"east_0001":0.12,"east_0002":0.04},"west_means_m":{"west_0001":0,"west_0002":0},
    "linear_replacement_east_m":{"east_0001":0.04,"east_0002":0.08},"harmonic_return_east_m":{"east_0001":0.08,"east_0002":0.02},
    "disabled_east_0002":"Only east_0001 remains active; documented single-point uniform signal for whole PLI, verify in G",
    "observations":[{"id":"near_east_south","x":500115,"y":5700005},{"id":"near_east_north","x":500115,"y":5700035},{"id":"near_west","x":500005,"y":5700005}],
    "numeric_gate":{"clock_s":list(range(0,121,10)),"map_shape":[13,48],"history_stations":3,"final_restart_s":120,"values_unit":"m",
        "require_finite_unmasked":True,"manual_vs_candidate_rtol":0,"manual_vs_candidate_atol_m":1e-6,
        "map_history_and_coordinate_joined_restart_atol_m":1e-6,
        "operation_sensitivity":"For each changed reference (disable, linear, return) require max absolute late station delta vs harmonic base >0.001m; enable equals harmonic base",
        "limits":"Matched raw numerical control, not an analytic PDE solution, calibration or GUI parity"}}


def dc(name,value):return harmonic(name,value,rows=(("0",value,"0"),))


def constant(name,value):return linear(name,rows=(("0",value),("60",value),("120",value)))


def bc(kind):
    west=dc("west_0001","0")+dc("west_0002","0")
    if kind=="base":east=dc("east_0001","0.12")+dc("east_0002","0.04")
    elif kind=="disabled":east=dc("east_0001","0.12")
    elif kind=="linear":east=constant("east_0001","0.04")+constant("east_0002","0.08")
    elif kind=="returned":east=dc("east_0001","0.08")+dc("east_0002","0.02")
    else:raise AssertionError("Unknown manual control")
    return GENERAL+west+east


def prepare(root,cli=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=False);save(root/"predeclared.json",DECLARATION)
    model=root/"hand-authored-baseline";model.mkdir();mesh=write_mesh(model/"mesh.nc")
    mdu=("# Independent B10-V hand-authored control. EPSG:32631, synthetic local zero.\n"
        "[General]\nfileVersion=1.09\nfileType=modelDef\nprogram=D-Flow FM\nPathsRelativeToParent=0\n"
        "[geometry]\nNetFile=mesh.nc\nKmx=0\nBedlevType=3\nWaterLevIni=0\n"
        "[time]\nRefDate=20260101\nTZone=0\nTUnit=S\nTStart=0\nTStop=120\n"
        "StartDateTime=20260101000000\nStopDateTime=20260101000200\nDtUser=1\nDtMax=1\nDtInit=1\n"
        "[numerics]\nCFLMax=0.7\nTlfsmo=0\n[physics]\nSalinity=0\nTemperature=0\nUnifFrictType=1\nUnifFrictCoef=0.023\n"
        "[external forcing]\nExtForceFile=\nExtForceFileNew=boundaries.ext\n[restart]\nRestartFile=\n"
        "[waves]\nWaveModelNr=0\n[trachytopes]\nTrtRou=N\n[output]\nOutputDir=output\nObsFile=observations.xyn\n"
        "HisFile=model_his.nc\nMapFile=model_map.nc\nHisInterval=10\nMapInterval=10\nRstInterval=120\nMapFormat=4\nNcFormat=3\n")
    (model/"model.mdu").write_text(mdu,encoding="ascii")
    (model/"boundaries.ext").write_bytes(b"[General]\nfileVersion=2.02\nfileType=extForce\n"
        b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=west.pli\nforcingFile=boundaries.bc\n"
        b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=east.pli\nforcingFile=boundaries.bc\n")
    (model/"west.pli").write_bytes(b"west\n2 2\n500000 5700000\n500000 5700040\n")
    (model/"east.pli").write_bytes(b"east\n2 2\n500120 5700000\n500120 5700040\n")
    (model/"observations.xyn").write_bytes(b"500115 5700005 near_east_south\n500115 5700035 near_east_north\n500005 5700005 near_west\n")
    (model/"boundaries.bc").write_bytes(bc("base"));source=root/"explicit-requests";source.mkdir()
    (source/"enable-east2.bc").write_bytes(GENERAL+dc("east_0002","0.04"))
    (source/"east-linear.bc").write_bytes(GENERAL+constant("east_0001","0.04")+constant("east_0002","0.08"))
    (source/"east-harmonic.bc").write_bytes(GENERAL+dc("east_0001","0.08")+dc("east_0002","0.02"))
    manual={}
    for kind in ("base","disabled","linear","returned"):
        target=root/("manual-"+kind);shutil.copytree(model,target);(target/"boundaries.bc").write_bytes(bc(kind));manual[kind]=target
    result={"state":"manual_controls_prepared_no_native","native_launches":0,"mesh":mesh,"declaration":DECLARATION,
            "manual_controls":{},"candidates":{},"native_authorization":"none; coordinator separate slot required"}
    for kind,target in manual.items():
        result["manual_controls"][kind]={"path":str(target),"file_sha256":{k:hashlib.sha256(v).hexdigest() for k,v in snapshot(target).items()},
            "signals":{name:{"function":b["function"],"columns":semantic(b)["columns"],"rows":b["rows"]} for name,b in signals((target/"boundaries.bc").read_bytes()).items()}}
    plans=[("disable","base","disabled",("support","--point","east_0002","--state","disable")),
           ("enable","disabled","base",("support","--point","east_0002","--state","enable","--signal",source/"enable-east2.bc")),
           ("to-linear","base","linear",("function-set","--function","timeseries","--signals",source/"east-linear.bc")),
           ("to-harmonic","linear","returned",("function-set","--function","harmonic","--signals",source/"east-harmonic.bc"))]
    for name,start,expected,tail in plans:
        target=root/("candidate-"+name);shutil.copytree(manual[start],target)
        args=("boundary",tail[0],target/"model.mdu","--boundary","east",*tail[1:])
        row={"start_control":start,"expected_control":expected,"argv":list(map(str,args)),"input_ready":False}
        if cli is not None:
            before=snapshot(target);requests_before=snapshot(source);preview=cli.invoke(*args)
            require(snapshot(target)==before,"Candidate preview changed independent source inputs")
            applied=cli.invoke(*args,"--apply","--expect-sha256",preview["input_sha256"])
            require(snapshot(source)==requests_before,"Candidate edit changed explicit BC request")
            after=snapshot(target);check=dict(before);check["boundaries.bc"]=after["boundaries.bc"]
            require(after==check,"Candidate changed geometry/EXT/mesh/clock/stations")
            actual=signals(after["boundaries.bc"]);oracle=signals((manual[expected]/"boundaries.bc").read_bytes())
            require(set(actual)==set(oracle) and all(semantic(actual[k])==semantic(oracle[k]) for k in oracle),"Candidate differs from independently authored numeric control")
            retired=() if name=="enable" else ("east_0002",) if name=="disable" else ("east_0001","east_0002")
            replacement_names=() if name=="disable" else ("east_0002",) if name=="enable" else ("east_0001","east_0002")
            # Source slices, including inline comments, are independent authored
            # bytes; full output equality rules out in-stream tombstones.
            request_blocks=signals(Path(tail[-1]).read_bytes()) if replacement_names else {}
            require(after["boundaries.bc"]==replacement_reference(before["boundaries.bc"],retired,(request_blocks[n] for n in replacement_names)),"Numeric candidate full bytes contain retirement residue or unexpected edits")
            require(after["boundaries.bc"]==(manual[expected]/"boundaries.bc").read_bytes(),"Numeric candidate differs bytewise from independently hand-authored complete BC")
            require(not numeric_tail_comments(after["boundaries.bc"]),"Candidate has forbidden standalone numeric-tail comments")
            for old in scan_west(before["boundaries.bc"]):require(after["boundaries.bc"].count(old)==1,"Candidate changed unrelated west bytes")
            require(not after["boundaries.bc"].startswith(b"\xef\xbb\xbf") and sha(target/"boundaries.bc")==applied["receipt"]["after_sha256"],"Candidate encoding changed or post-apply edit occurred")
            row.update(input_ready=True,preview_sha256=preview["input_sha256"],after_BC_sha256=sha(target/"boundaries.bc"),post_apply_edit=False)
        row["file_sha256"]={k:hashlib.sha256(v).hexdigest() for k,v in snapshot(target).items()};result["candidates"][name]=row
    if cli is not None:result["state"]="four_candidates_match_independent_numeric_controls_no_native"
    save(root/"preparation.json",result)
    return result


def scan_west(raw):
    from .verify_boundary_support_fixture import scan
    return [b["raw"] for b in scan(raw) if b["name"].startswith("west_")]
