"""B09 bounded native preparation and independent raw comparator. NO launcher.

Only a coordinator with an explicit native slot may run the prepared commands.
prepare() performs Python CLI model creation/import only; compare() reads NetCDF.
Neither function launches Delft3D, a GUI, a VM, DIMR, MPI or a BMI worker.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import shutil

from .channel_fixture import write_mesh
from .verify_boundary_import_fixture import (ROOT, GENERAL, TIME_UNIT, NEW, PublicCLI, forcing, numeric_rows,
                                             require, save, sha, signals, snapshot)

CASES=("hand-authored-control","bc-import","csv-import")
UNIT=TIME_UNIT+" +00:00"
NATIVE_GENERAL=GENERAL.removeprefix(b"\xef\xbb\xbf")
DECLARATION={"task":"B09-V","fixture":"independent 48-cell channel, 65 nodes,112 edges,120x40m",
    "crs":"EPSG:32631","bed_elevation_m":-3,"vertical_datum":"synthetic local zero; no geodetic vertical datum realization",
    "clock_UTC":{"origin":"2026-01-01T00:00:00Z","stop":"2026-01-01T00:02:00Z","seconds":[0,60,120]},
    "meaning":"Each BC/CSV t is elapsed seconds since its declared UTC origin, not elapsed since TStart or host local time; model TZone=0",
    "selected_boundary":"east","east_supports":["east_0001","east_0002"],"east_m":[0,0.12,0.12],
    "west_m":[0,0,0],"stations":[{"id":"near_east","x":500115,"y":5700005},{"id":"near_west","x":500005,"y":5700005}],
    "duration_seconds":120,"output_seconds":10,"maximum_native_launches":3,"sequential":True,"attempts_per_case":1,
    "timeout_each_wall_seconds":60,"atol_m":1e-6,"rtol":0,"clock_atol_seconds":1e-6,"coordinate_atol_m":1e-7,
    "expected_map_shape":[13,48],"near_east_late_window_seconds":[90,120],"near_east_late_mean_range_m":[0.01,0.15],
    "comparison":"Import BC and CSV each vs hand-authored control at every raw map cell, station and time, plus final coordinate-joined restart",
    "native_launch_policy":"NO LAUNCHER in this harness; coordinator explicit slot required before executing any prepared run command",
    "native_BC_dialect":"BOM-free UTF8/ASCII before authored baseline/oracle/source and BEFORE public import; B09-G-BC-BOM-01 measured only EF BB BF removal",
    "portable_BOM_scope":"BOM preservation is a FILE-ONLY editor test; measured selected native reader rejects leading BOM",
    "GUI_runtime_parity":"not_claimed; original B09 G/C untested","scientific_scope":"bounded interpolation/equivalence and sign check, not calibration or general hydrodynamic validity"}


def control_bc():
    zero=(("0","0"),("60","0"),("120","0"))
    return NATIVE_GENERAL+b"".join(forcing(name,NEW if name.startswith("east_") else zero,comments=False,time_unit=UNIT)
                             for name in ("west_0001","west_0002","east_0001","east_0002"))


def prepare(root,cli,*,import_available):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    save(root/"predeclared.json",DECLARATION)
    source=root/"authoring";source.mkdir();mesh=source/"independent48_net.nc";mesh_report=write_mesh(mesh)
    spec=json.loads((ROOT/"examples/channel/model.json").read_text(encoding="utf-8"))
    spec["name"]="b09_independent_channel";spec["mesh"]={"path":mesh.name}
    spec["observations"]=DECLARATION["stations"]
    for boundary in spec["boundaries"]:
        boundary["signal"]={"function":"timeseries","time_unit":"s","time_origin":spec["clock"]["start"],"values":[[0,0],[60,0],[120,0]]}
    save(source/"model.json",spec)
    cli.invoke("model","create",source/"model.json","--out",root/"base")
    base=root/"base";bc=base/"boundaries.bc"
    # Both initial BC and oracle are authored here, never derived from import output.
    zero=(("0","0"),("60","0"),("120","0"))
    bc.write_bytes(NATIVE_GENERAL+b"".join(forcing(name,zero,comments=False,time_unit=UNIT)
                                   for name in ("west_0001","west_0002","east_0001","east_0002")))
    require(not bc.read_bytes().startswith(b"\xef\xbb\xbf"),"Authored baseline must be BOM-free BEFORE fork/import")
    save(root/"baseline-canonicalization.json",{"order":"authored BOM-free baseline written before generating source/oracle/candidates; no post-apply edits",
        "baseline_bc_sha256":sha(bc),"file_only_BOM_header_sha256":__import__("hashlib").sha256(GENERAL).hexdigest(),
        "native_header_sha256":__import__("hashlib").sha256(NATIVE_GENERAL).hexdigest(),"measured_basis":"B09-G-BC-BOM-01"})
    control=control_bc();(root/"oracle.bc").write_bytes(control)
    (source/"incoming.bc").write_bytes(NATIVE_GENERAL+forcing("east_0001",NEW,comments=False,time_unit=UNIT)+forcing("east_0002",NEW,comments=False,time_unit=UNIT))
    (source/"incoming.csv").write_bytes(b"t,level1,level2\n0,0,0\n60,0.12,0.12\n120,0.12,0.12\n")
    save(source/"mapping.json",{"version":1,"time_column":"t","time_unit":UNIT,"value_unit":"m","columns":{"east_0001":"level1","east_0002":"level2"}})
    result={"mesh":mesh_report,"cases":{},"native_launches":0,"state":"prepared_inputs_import_wiring_missing"}
    for name in CASES:
        folder=root/name;shutil.copytree(base,folder)
        row={"mdu":str(folder/"model.mdu"),"input_ready":False}
        if name=="hand-authored-control":
            (folder/"boundaries.bc").write_bytes(control);row["input_ready"]=True
        elif import_available:
            fmt="bc" if name=="bc-import" else "csv"
            args=("boundary","import",folder/"model.mdu","--boundary","east","--source",source/("incoming."+fmt),"--format",fmt,"--mode","replace",
                  *(("--mapping",source/"mapping.json") if fmt=="csv" else ()))
            before=snapshot(folder);source_before=snapshot(source);preview=cli.invoke(*args)
            require(snapshot(folder)==before and snapshot(source)==source_before,"Native-fixture preview wrote inputs")
            applied=cli.invoke(*args,"--apply","--expect-sha256",preview["input_sha256"])
            require(sha(folder/"boundaries.bc")==applied["receipt"]["after_sha256"],"BC changed after public apply")
            require(snapshot(source)==source_before,"Import changed external source/mapping/mesh/spec")
            after=snapshot(folder);expected=dict(before);expected["boundaries.bc"]=(folder/"boundaries.bc").read_bytes()
            require(after==expected,"Native import wrote more than its one BC")
            actual=signals(after["boundaries.bc"]);oracle=signals(control)
            require(set(actual)==set(oracle),"Native imported support inventory differs from independent oracle")
            for point in oracle:require(actual[point]["rows"]==oracle[point]["rows"],"Native imported data differs from oracle at "+point)
            for point in ("west_0001","west_0002"):
                require(actual[point]["raw"]==signals(before["boundaries.bc"])[point]["raw"],"Native shared BC west bytes changed")
            row.update(input_ready=True,preview_sha256=preview["input_sha256"],public_after_BC_sha256=applied["receipt"]["after_sha256"],
                       public_native_compatibility=applied.get("native_compatibility"),post_apply_edit_performed=False)
        row["input_sha256"]={path:__import__("hashlib").sha256(raw).hexdigest() for path,raw in snapshot(folder).items()}
        engine={path:digest for path,digest in row["input_sha256"].items() if path not in {"create-provenance.json","create-spec.json"}}
        row["engine_input_sha256"]=__import__("hashlib").sha256(json.dumps(engine,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        row["coordinator_command_after_explicit_lease"]=["dfm","run","start",str(folder/"model.mdu"),"--out",str(root/(name+"-native")),"--install","<LEASED-SUITE>","--route","direct","--timeout","60"]
        result["cases"][name]=row
    if all(v["input_ready"] for v in result["cases"].values()):result["state"]="ready_for_explicit_coordinator_native_lease"
    save(root/"preparation.json",result)
    return result


def _finite(variable):
    import numpy as np
    values=variable[:]
    require(not np.ma.getmaskarray(values).any() and np.isfinite(values).all(),"Raw NetCDF has masked/nonfinite values: "+variable.name)
    return np.asarray(values)


def _clock(variable,expected):
    import numpy as np
    from netCDF4 import date2num
    units=variable.units;calendar=getattr(variable,"calendar","standard")
    require(calendar in {"standard","gregorian","proleptic_gregorian"},"Unsupported raw calendar")
    epoch=date2num(datetime(2026,1,1),units,calendar=calendar)
    second=date2num(datetime(2026,1,1,0,0,1),units,calendar=calendar)-epoch
    values=(_finite(variable)-epoch)/second
    require(values.shape==expected.shape,"Raw clock shape differs")
    np.testing.assert_allclose(values,expected,rtol=0,atol=1e-6)
    return {"CF_units":units,"calendar":calendar,"seconds_since_declared_UTC_origin":values.tolist()}


def read_raw(run):
    import numpy as np
    from netCDF4 import Dataset,chartostring
    run=Path(run);output=run/"model/output"
    maps=list(output.glob("*_map.nc"));histories=list(output.glob("*_his.nc"))
    require(len(maps)==len(histories)==1,"Missing/ambiguous raw map/history")
    times=np.arange(0,121,10,dtype=float);result={"raw_hashes":{},"clocks":{}}
    with Dataset(maps[0]) as nc:
        result["clocks"]["map"]=_clock(nc["time"],times)
        xy=np.column_stack([_finite(nc["mesh2d_face_x"]),_finite(nc["mesh2d_face_y"])])
        expected=np.array([(500005+10*i,5700005+10*j) for j in range(4) for i in range(12)])
        order=[]
        for point in expected:
            matches=np.flatnonzero(np.max(abs(xy-point),axis=1)<1e-7)
            require(len(matches)==1,"Missing/ambiguous physical map cell");order.append(int(matches[0]))
        require(xy.shape==(48,2),"Wrong raw grid shape")
        require(nc["mesh2d_s1"].units=="m","Map elevation unit differs")
        level=_finite(nc["mesh2d_s1"]);require(level.shape==(13,48),"Raw map shape differs")
        result["map"]=level[:,order];result["xy"]=expected
        np.testing.assert_allclose(_finite(nc["mesh2d_node_z"]),-3,rtol=0,atol=1e-7)
    with Dataset(histories[0]) as nc:
        result["clocks"]["history"]=_clock(nc["time"],times)
        names=[str(n).strip(" \0") for n in chartostring(nc["station_name"][:])]
        require(nc["waterlevel"].units=="m","History elevation unit differs")
        water=_finite(nc["waterlevel"]);stations=[]
        sx,sy=_finite(nc["station_x_coordinate"]),_finite(nc["station_y_coordinate"])
        require(water.shape==(13,len(names)) and sx.shape==sy.shape==(len(names),),"Raw station array shapes differ")
        for station in DECLARATION["stations"]:
            require(names.count(station["id"])==1,"Missing/ambiguous raw station id")
            i=names.index(station["id"])
            np.testing.assert_allclose([sx[i],sy[i]],
                                       [station["x"],station["y"]],rtol=0,atol=1e-7)
            require(water.shape[0]==13,"Raw station time length differs")
            stations.append(water[:,i])
            cell=np.flatnonzero(np.max(abs(expected-[station["x"],station["y"]]),axis=1)<1e-7)
            require(len(cell)==1,"Station does not match declared containing cell")
            np.testing.assert_allclose(water[:,i],result["map"][:,cell[0]],rtol=0,atol=1e-6)
        result["history"]=np.column_stack(stations)
    candidates=[]
    for path in output.glob("*_rst.nc"):
        with Dataset(path) as nc:
            try:_clock(nc["time"],np.array([120.]));candidates.append(path)
            except AssertionError:continue
    require(len(candidates)==1,"Missing/ambiguous actual final restart")
    with Dataset(candidates[0]) as nc:
        result["clocks"]["restart"]=_clock(nc["time"],np.array([120.]))
        require(nc["s1"].units=="m","Restart elevation unit differs")
        xy=np.column_stack([_finite(nc["FlowElem_xcc"]),_finite(nc["FlowElem_ycc"])])
        restart=_finite(nc["s1"]).reshape(-1);joined=[]
        for point in expected:
            matches=np.flatnonzero(np.max(abs(xy-point),axis=1)<1e-7)
            require(len(matches)==1,"Missing/ambiguous physical restart cell");joined.append(restart[matches[0]])
        result["restart"]=np.asarray(joined)
        np.testing.assert_allclose(result["restart"],result["map"][-1],rtol=0,atol=1e-6)
    result["raw_hashes"]={p.name:sha(p) for p in [maps[0],histories[0],candidates[0]]}
    return result


def compare(runs):
    import numpy as np
    require(set(runs)==set(CASES),"Require exactly three independently run cases")
    roots=[Path(p).resolve(strict=True) for p in runs.values()]
    require(len(set(roots))==3 and all(not a.is_relative_to(b) for a in roots for b in roots if a!=b),
            "Comparator requires three disjoint run roots; one output set cannot stand for independent controls")
    data={name:read_raw(path) for name,path in runs.items()};control=data[CASES[0]]
    maxima={}
    for name in CASES[1:]:
        maxima[name]={}
        for key in ("map","history","restart"):
            np.testing.assert_allclose(data[name][key],control[key],rtol=0,atol=1e-6)
            maxima[name][key+"_max_abs_delta_m"]=float(np.max(abs(data[name][key]-control[key])))
    require(.01<float(control["history"][9:13,0].mean())<.15,"Independent control lacks bounded positive late head response")
    np.testing.assert_allclose(control["map"][0],0,rtol=0,atol=1e-6)
    return {"state":"passed_raw_numerical_comparison_only","runtime_acceptance":"not_assessed",
            "native_launches_by_comparator":0,"GUI_parity":"not_claimed","max_deltas":maxima,
            "cases":{name:{"raw_hashes":v["raw_hashes"],"clocks":v["clocks"],"station_waterlevel_m":v["history"].tolist()} for name,v in data.items()},
            "limits":"Raw output equivalence does not independently establish process ownership, launch provenance or scientific calibration"}
