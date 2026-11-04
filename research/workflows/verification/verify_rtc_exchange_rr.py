"""Independent read-only f152 RR/FM candidate audit. No native launch path.

Consumes the complete matching HYDROLIB tree, never c11 identifiers. Classifies
empty/missing FNM inputs using observed node/options and pinned reader conditions.
Static eligibility, raw-data exchange requirements and native evidence stay separate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from .verify_rtc_exchange import (ENGINE_PIN, HELPER_PIN, TOLERANCES, config_contract, contained,
    fingerprints, fnm_inputs, git_blob, ini_rows, near, require, rr_oracle, series_contract, sha, write)

F152 = "tests/data/input/e02/f152_1d2d_projectmodels_rhu/c04_DHydamo-MGB-initialisation"
RECEIPT_SHA = "fe60d030675b5aaa778398d759a06c690599788012a83e260210fa1affc6b48b"
RR_ENGINE = "src/engines_gpl/rr/packages/rr_kernel_f/src/"


def blocks(raw):
    result=[]
    for line in raw.decode("utf-8-sig").splitlines():
        line=line.split("#",1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            result.append({"section":line[1:-1].casefold(),"fields":[]})
        elif "=" in line and result:
            key,value=line.split("=",1)
            result[-1]["fields"].append((key.strip().casefold(),value.strip()))
    return result


def one(block,key):
    values=[v for k,v in block["fields"] if k==key.casefold()]
    require(len(values)==1,"Missing/ambiguous model field: "+key)
    return values[0]


def token_records(raw, keyword):
    result=[]
    for number,line in enumerate(raw.decode("utf-8-sig").splitlines(),1):
        if not re.match(r"^\s*"+re.escape(keyword)+r"\b",line):
            continue
        tokens=[]
        for match in re.finditer(r"'((?:[^']|'')*)'|([^\s']+)",line):
            tokens.append(match[1].replace("''", "'") if match[1] is not None else match[2])
        require(tokens[-1].casefold()==keyword.casefold(),"Unterminated topology/parameter record")
        result.append({"tokens":tokens,"line":number})
    return result


def token(row,key,offset=1):
    positions=[i for i,value in enumerate(row["tokens"]) if value.casefold()==key.casefold()]
    require(len(positions)==1 and positions[0]+offset<len(row["tokens"]),"Missing/ambiguous token: "+key)
    return row["tokens"][positions[0]+offset]


def rr_topology(nodes_raw, links_raw):
    nodes={}
    for row in token_records(nodes_raw,"NODE"):
        name=token(row,"id")
        require(name not in nodes and name.casefold() not in {n.casefold() for n in nodes},"Duplicate RR node identity")
        require(token(row,"mt")=="1","Unexpected RR model type slot")
        nodes[name]={"internal_type":int(token(row,"mt",2)),"external_nt":int(token(row,"nt")),"line":row["line"]}
    require(nodes,"RR node topology is empty")
    links={}
    for row in token_records(links_raw,"BRCH"):
        name=token(row,"id");begin,end=token(row,"bn"),token(row,"en")
        require(name not in links,"Duplicate RR branch identity")
        require(begin in nodes and end in nodes and begin!=end,"RR link names an absent/self node; never invent links")
        links[name]={"begin":begin,"end":end,"type":int(token(row,"bt")),"line":row["line"]}
    require(links,"RR link topology is empty")
    incident={name:[] for name in nodes}
    for name,link in links.items():
        incident[link["begin"]].append(name);incident[link["end"]].append(name)
    unconnected=[name for name,values in incident.items() if not values]
    require(all(nodes[name]["internal_type"]==6 for name in unconnected),"Disconnected active runoff node with no authoritative link")
    return {"nodes":nodes,"links":links,"internal_type_counts":dict(Counter(str(v["internal_type"]) for v in nodes.values())),
            "external_nt_counts":dict(Counter(str(v["external_nt"]) for v in nodes.values())),
            "boundaries":sorted(name for name,v in nodes.items() if v["internal_type"]==6),
            "boundary_nodes_without_links":sorted(unconnected),"link_policy":"Original graph retained exactly; unconnected boundary endpoints are not supplied invented runoff links"}


def matching_exchanges(contract, graph, ext_raw, rr_bc_raw):
    lateral={}
    for b in blocks(ext_raw):
        if b["section"]!="lateral":continue
        name=one(b,"id")
        require(name not in lateral,"Duplicate FM lateral ID")
        lateral[name]={key:one(b,key) for key in ("type","locationtype","branchid","chainage","discharge")}
    boundary={}
    for b in blocks(rr_bc_raw):
        if b["section"]!="boundary":continue
        name=one(b,"name")
        require(name not in boundary,"Duplicate RR boundary condition ID")
        boundary[name]={key:one(b,key) for key in ("quantity","unit","function")}
    fm=next(n for n,c in contract["components"].items() if c["library"]=="dflowfm")
    rr=next(n for n,c in contract["components"].items() if c["library"]=="rr_dll")
    directions={}
    for name,c in contract["couplers"].items():
        if (c["source"],c["target"])==(fm,rr):mode="water_level"
        elif (c["source"],c["target"])==(rr,fm):mode="water_discharge"
        else:raise AssertionError("Unexpected RR/FM exchange direction")
        require(mode not in directions,"Ambiguous exchange-direction definitions")
        ids=[]
        for a,b in c["items"]:
            left,right=a.split("/"),b.split("/")
            require(len(left)==len(right)==3 and left[1]==right[1] and left[2]==right[2]==mode,"Scalar pair changes catchment identity/quantity")
            require((left[0],right[0])==(("laterals","catchments") if mode=="water_level" else ("catchments","laterals")),"Incorrect endpoint family")
            name_id=left[1]
            require(name_id in graph["boundaries"] and name_id in boundary and name_id in lateral,"Exchange ID absent from matching RR node/BC/FM lateral")
            require(lateral[name_id]["discharge"]=="REALTIME" and lateral[name_id]["type"]=="discharge" and lateral[name_id]["locationtype"].casefold()=="1d","FM lateral is not active realtime 1D discharge")
            require(boundary[name_id]["quantity"]=="water_level" and boundary[name_id]["unit"]=="m","RR boundary water input quantity/units differ")
            ids.append(name_id)
        require(len(ids)==len(set(ids)),"Duplicate scalar identity within direction")
        directions[mode]={"coupler":name,"ids":sorted(ids),"items":c["items"]}
    require(set(directions)=={"water_level","water_discharge"},"Need both actual f152 directions")
    require(directions["water_level"]["ids"]==directions["water_discharge"]["ids"]==graph["boundaries"],"Two-way IDs do not cover exactly the authoritative RR boundaries")
    sequence=contract["groups"][0]["sequence"]
    require(sequence==[("coupler",directions["water_level"]["coupler"]),("start",rr),("coupler",directions["water_discharge"]["coupler"])],"RR update must be bracketed by level input then discharge output")
    return {"directions":directions,"fm_laterals":lateral,"rr_boundary_conditions":boundary,"exchange_ids":graph["boundaries"]}


def rr_clock(raw):
    b=next(b for b in blocks(raw) if b["section"]=="timesettings")
    def date(k):return datetime.strptime(one(b,k).strip("'\""),"%Y/%m/%d;%H:%M:%S")
    step=float(one(b,"timestepsize"));start,stop=date("starttime"),date("endtime")
    require(math.isfinite(step) and step>0 and stop>start,"Invalid explicit RR clock")
    require((stop-start).total_seconds()%step==0,"RR interval is not an integer number of internal steps")
    return {"start":start.isoformat(),"stop":stop.isoformat(),"step_seconds":step,"duration_seconds":(stop-start).total_seconds(),
            "timezone":"not declared by RR INI; source FM has explicit UTC0, not inferred from current machine"}


def fm_clock(raw):
    rows=ini_rows(raw)
    def value(address):
        found=[r["value"] for r in rows if r["address"]==address]
        require(len(found)==1,"Missing/duplicate FM setting: "+address)
        return found[0]
    reference=datetime.strptime(value("time/refdate"),"%Y%m%d")
    unit=value("time/tunit").upper();require(unit in {"S","M","H","D"},"Unknown FM time unit")
    factor={"S":1,"M":60,"H":3600,"D":86400}[unit]
    zone=float(value("time/tzone"))
    dates=[reference+timedelta(seconds=float(value("time/"+k))*factor,hours=-zone) for k in ("tstart","tstop")]
    absolute=[r for r in rows if r["address"] in {"time/startdatetime","time/stopdatetime"} and r["value"]]
    require(not absolute,"Candidate clock parser requires explicit relative source clock, not hidden absolute overrides")
    patterns={address:[float(v) for v in value(address).split()] for address in ("output/hisinterval","output/mapinterval","output/rstinterval")}
    require(all(len(v) in {1,3} and all(map(math.isfinite,v)) and v[0]>0 for v in patterns.values()),"Invalid FM output interval vector")
    return {"reference":reference.isoformat(),"start":dates[0].isoformat(),"stop":dates[1].isoformat(),"duration_seconds":(dates[1]-dates[0]).total_seconds(),
            "dtuser_seconds":float(value("time/dtuser")),"tzone_hours":zone,"relative_unit":unit,"output_interval_vectors_seconds":patterns}


def rain_contract(raw):
    data=[line.strip() for line in raw.decode("utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("*")]
    require(data[0]=="1","Unsupported BUI format")
    count=int(data[1]);require(0<count<10000,"Invalid rain station count")
    names=[line.strip("'\"") for line in data[2:2+count]]
    require(len(names)==len(set(names))==count,"Duplicate/missing rain station identity")
    events,step=map(int,data[2+count].split());require(events==1 and step>0,"Require one bounded rain event")
    timing=list(map(int,data[3+count].split()));require(len(timing)==10,"Invalid rain event date/duration")
    start=datetime(*timing[:6]);duration=timedelta(days=timing[6],hours=timing[7],minutes=timing[8],seconds=timing[9]).total_seconds()
    values=[[float(v) for v in line.split()] for line in data[4+count:]]
    require(duration>0 and duration%step==0 and len(values)>=duration/step,"Rain event data do not cover declared interval")
    require(all(len(row)==count and all(math.isfinite(v) and v>=0 for v in row) for row in values),"Rain station columns missing/nonfinite/negative")
    return {"stations":names,"station_count":count,"start":start.isoformat(),"stop":(start+timedelta(seconds=duration)).isoformat(),
            "interval_seconds":step,"unit":"mm per rainfall-record interval, NOT mm/s or mm/hour","rows":len(values),
            "declared_interval_rows":int(duration/step),"trailing_rows":len(values)-int(duration/step),"first_interval_mm":values[0],
            "first_interval_rate_m_s":[v/1000/step for v in values[0]],"values_mm_per_interval":values}


def optional_classification(rr_dir, graph):
    """Node/config-selected read predicates; unresolved slots stay unresolved."""
    counts={int(k):v for k,v in graph["internal_type_counts"].items()}
    paved=token_records((rr_dir/"PAVED.3B").read_bytes(),"PAVE")
    unpaved=token_records((rr_dir/"UNPAVED.3B").read_bytes(),"UNPV")
    require({token(r,"id") for r in paved}=={n for n,v in graph["nodes"].items() if v["internal_type"]==1},"Paved parameter nodes differ from graph")
    require({token(r,"id") for r in unpaved}=={n for n,v in graph["nodes"].items() if v["internal_type"]==2},"Unpaved parameter nodes differ from graph")
    qc=[int(token(r,"qc")) for r in paved];ig=[int(token(r,"ig")) for r in unpaved];su=[int(token(r,"su")) for r in unpaved]
    # co4/5 seepage time tables live in Unpaved.SEP (reader infile5), NOT in .tbl.
    sep=(rr_dir/"UNPAVED.SEP").read_text()
    sep_ids=re.findall(r"(?m)^SEEP\s+id\s+'([^']+)'",sep)
    sep_refs=[token(r,"sp") for r in unpaved]
    require(set(sep_refs)<=set(sep_ids),"Active unpaved seepage definition missing")
    co=[int(v) for v in re.findall(r"(?m)^SEEP[^\n]*?\bco\s+(\d+)",sep)]
    require(len(sep_ids)==len(co),"Seepage option missing/ambiguous")
    inline_count=len(re.findall(r"(?m)^TBLE\s*$",sep))
    require(not any(v in (4,5) for v in co) or inline_count>=sum(v in (4,5) for v in co),"Active inline seepage time tables missing")
    all_inputs=fnm_inputs((rr_dir/"Sobek_3b.fnm").read_bytes(),rr_dir)
    classifications=[]
    inactive={10:(7,"NWRW .3b"),11:(7,"NWRW .alg"),106:(7,"NWRW table"),35:(3,"greenhouse"),36:(3,"greenhouse"),
              50:(4,"full openwater seepage; type21 rain-only does not read it"),51:(4,"full openwater tables"),
              52:(5,"structures"),53:(5,"structures"),54:(5,"structures"),55:(5,"structures"),59:(14,"WWTP"),60:(14,"WWTP"),
              61:(15,"industry"),77:(15,"industry"),44:(16,"Sacramento"),79:(19,"HBV temperature")}
    for item in all_inputs:
        if item["state"]=="present_nonempty":continue
        slot=item["slot"];classification="unresolved_optional_predicate";reason="Not inferred unused from file size; reader/option proof still required"
        if slot in inactive and counts.get(inactive[slot][0],0)==0:
            classification="inactive_node_family";reason=f"No internal node type {inactive[slot][0]}: {inactive[slot][1]}; BinFileModule guarded reads"
        elif slot in (4,9,117) and item["state"]=="empty":
            classification="required_open_empty_records_allowed";reason="Reader opens/scans the file; no NWRW/DWA/routing definitions activated in this graph"
        elif slot==8 and not any(qc) and item["state"]=="empty":
            classification="opened_empty_table_not_selected";reason="All active PAVE qc=0; QC_TTable remains false (PAVEDMODULE:362-385,705)"
        elif slot==34 and not any(ig) and not any(su) and all(v in (1,3,4) for v in co) and item["state"]=="empty":
            classification="opened_empty_table_not_selected";reason="UNPV ig=0/su=0; no H0/co2 or salt/co5 table; co4 TBLE is read from .SEP infile5 (UnpavedModule:1675-1708)"
        elif slot==57:
            classification="not_read_in_DLL_boundary_path";reason="rr_dll BMI sets dll_mode; BinFileModule:458-495 reads BoundaryConditions.bc instead of legacy Bound3B.tbl"
        elif slot in (38,92):
            classification="not_read_in_DIMR_DLL_path";reason="RRModule guards old controller initialization with not dimr_mode and old incoming HIS with not dll_mode"
        elif slot==78:
            settings=[b for b in blocks((rr_dir/"DELFT_3B.INI").read_bytes()) if b["section"]=="options"]
            if one(settings[0],"maalstopmodule")=="0":
                classification="inactive_explicit_option";reason="MaalstopModule=0; RRModule:2141 reads RTC HIS only if IMLSTP != 0"
        elif slot==41:
            settings=next(b for b in blocks((rr_dir/"DELFT_3B.INI").read_bytes()) if b["section"]=="options")
            if one(settings,"restartin")=="0":
                classification="inactive_explicit_option";reason="RestartIn=0; original continuation file is not an input for this case"
        elif slot==43:
            classification="obsolete_binary_input_not_read";reason="Pinned BinFileModule RDBINF: ASCII path only, SkipBinfile=false is fatal; file43 not read"
        classifications.append(item|{"classification":classification,"basis":reason})
    return {"empty_or_missing_inputs":classifications,"active_paved_qc":dict(Counter(qc)),"active_unpaved_ig":dict(Counter(ig)),
            "active_unpaved_su":dict(Counter(su)),"active_seepage_co":dict(Counter(co)),"inline_seepage_tables":inline_count,
            "limits":"Read-predicate classification for this graph/flags only, not a proof of successful engine initialization"}


def rr_bidirectional_oracle(case):
    require(set(case["fm_water_level"])==set(case["rr_received_level"])==set(case["rr_outflow"]),"Both exchange directions must use exactly the same f152 catchment IDs")
    start,step,stop=case["schedule_seconds"]
    expected=list(range(start,stop,step))
    for name,source in case["fm_water_level"].items():
        receiver=case["rr_received_level"][name]
        require(source["address"]==f"laterals/{name}/water_level" and receiver["address"]==f"catchments/{name}/water_level","Water-level pair addresses/IDs differ")
        left,right=series_contract(source,expected,"m"),series_contract(receiver,expected,"m")
        # Pinned rr_dll_bmi set_var stores sngl(value_to_rr) in BndPar.
        # This precision bound is declared before any native trial, not fit to it.
        require(all(abs(a-b)<=1e-7+abs(a)*2**-24 for a,b in zip(left,right)),"FM level differs from actual RR boundary received value")
    result=rr_oracle(case)
    result["water_level_direction"]="passed"
    result["discharge_direction"]="passed"
    return result


def branch_locations(path, mappings):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        raw=np.ma.asarray(ds["network1d_branch_id"][:])
        require(not np.ma.getmaskarray(raw).any(),"Masked FM branch identifiers")
        names=[str(v).strip().strip("\x00") for v in (nc.chartostring(raw) if raw.dtype.kind=="S" and raw.ndim==2 else raw)]
        require(len(names)==len(set(names)),"Duplicate FM network branch identifiers")
        length=np.ma.asarray(ds["network1d_edge_length"][:])
        require(ds["network1d_edge_length"].units=="m" and len(length)==len(names) and not np.ma.getmaskarray(length).any() and np.isfinite(length.data).all(),"Invalid authoritative FM branch length")
        lengths=dict(zip(names,length.data.tolist()))
        for name in mappings["exchange_ids"]:
            lat=mappings["fm_laterals"][name]
            branch=lat["branchid"];chain=float(lat["chainage"])
            require(branch in lengths and math.isfinite(chain) and 0<=chain<=lengths[branch],"FM lateral branch/chainage invalid")
        return {"branch_count":len(names),"verified_lateral_locations":len(mappings["exchange_ids"]),"coordinate_units":"m","branch_lengths_m":lengths,
                "mesh_counts":{key:len(value) for key,value in ds.dimensions.items() if key in {"mesh1d_nNodes","mesh2d_nFaces","nLink1D2D_edge"}}}


def engine_proofs(root,out):
    requested={
        "BinFileModule.f90":[(144,182),(247,302),(339,383),(391,444),(458,505),(532,562),(575,625),(1337,1418)],
        "PAVEDMODULE.f90":[(355,384),(700,711)],
        "UnpavedModule.F90":[(894,913),(1027,1045),(1581,1615),(1670,1710),(1780,1798),(1846,1860),(1921,1938),(1995,2008)],
        "RRModule.F90":[(466,479),(900,928),(1683,1694),(1765,1778),(2137,2143)],
        "MeteoModule.f90":[(344,360)],
        "LinkModule.f90":[(209,222),(259,269)],
        "BoundaryModule.f90":[(1205,1217)]}
    result={};folder=out/"pinned-reader-source";folder.mkdir()
    repo=root/"research/upstream/Delft3D"
    for file,ranges in requested.items():
        path=RR_ENGINE+file;raw=git_blob(repo,ENGINE_PIN,path)
        (folder/file).write_bytes(raw);lines=raw.decode().splitlines()
        result[file]={"source_commit":ENGINE_PIN,"path":path,"sha256":sha(folder/file),
                      "lines":[{"line":n,"text":lines[n-1]} for lo,hi in ranges for n in range(lo,hi+1)]}
    bmi="src/engines_gpl/rr/packages/rr_dll/src/rr_dll_bmi.f90"
    raw=git_blob(repo,ENGINE_PIN,bmi);(folder/"rr_dll_bmi.f90").write_bytes(raw)
    lines=raw.decode().splitlines()
    result["rr_dll_bmi.f90"]={"source_commit":ENGINE_PIN,"path":bmi,"sha256":sha(folder/"rr_dll_bmi.f90"),
                               "lines":[{"line":n,"text":lines[n-1]} for lo,hi in [(102,112),(237,281),(366,400),(477,501),(507,558)] for n in range(lo,hi+1)]}
    write(out/"reader-predicate-proofs.json",result)
    return {name:value["sha256"] for name,value in result.items()}


def pinned_tree(root, source, out):
    original=fingerprints(source)
    require(len(original)==62 and sum(p.stat().st_size for p in source.rglob("*") if p.is_file())==7593382,"Matching whole f152 source tree differs in file inventory/size")
    receipt=source.parent/"receipt.json"
    require(sha(receipt)==RECEIPT_SHA,"Coordinator source receipt identity changed")
    declared=json.loads(receipt.read_bytes())
    require(declared["revision"]==HELPER_PIN and declared["upstream_directory"]==F152,"Source receipt is not the locked f152 candidate")
    repository=root/"research/upstream/HYDROLIB-core"
    argv=["git","-C",str(repository),"ls-tree","-r","--name-only",HELPER_PIN,F152]
    names=subprocess.check_output(argv,stdin=subprocess.DEVNULL,timeout=15).decode().splitlines()
    require({str(Path(n).relative_to(F152)).replace("\\","/") for n in names}==set(original),"Actual candidate differs from complete pinned Git tree")
    for name,digest in original.items():
        raw=git_blob(repository,HELPER_PIN,F152+"/"+name)
        require(hashlib.sha256(raw).hexdigest()==digest==declared["files"][name]["sha256"],"Source byte identity differs from pinned Git blob: "+name)
    write(out/"source-tree-hashes.before.json",original)
    return original


def boundary_forcing_audit(source):
    """Resolve existing FM boundary names and physical/time units, no new IDs."""
    ext=blocks((source/"fm/moergestels_broek_new.ext").read_bytes())
    raw=(source/"fm/boundaries.bc").read_text()
    spans=list(re.finditer(r"(?mi)^\s*\[Forcing\]\s*$",raw))
    forcing={}
    for i,match in enumerate(spans):
        content=raw[match.start():spans[i+1].start() if i+1<len(spans) else len(raw)]
        b=blocks(content.encode())[0];name=one(b,"name")
        require(name not in forcing,"Duplicate active FM BC name")
        forcing[name]=(b,content)
    result=[]
    for b in ext:
        if b["section"]!="boundary":continue
        name=one(b,"nodeid");quantity=one(b,"quantity")
        require(one(b,"forcingfile")=="boundaries.bc" and name in forcing,"FM boundary reference cannot be resolved")
        f,content=forcing[name]
        units=[v for k,v in f["fields"] if k=="unit"]
        quantities=[v for k,v in f["fields"] if k=="quantity"]
        require(quantities==["time",quantity] and len(units)==2 and units[1]==("m" if quantity=="waterlevelbnd" else "m3/s"),"FM boundary quantity/units ambiguous")
        pairs=[]
        for line in content.splitlines():
            tokens=line.strip().split()
            if len(tokens)==2:
                try:pairs.append([float(v) for v in tokens])
                except ValueError:pass
        require(pairs and all(all(map(math.isfinite,v)) for v in pairs) and all(a[0]<b[0] for a,b in zip(pairs,pairs[1:])),"FM BC time sequence invalid")
        import netCDF4 as nc
        require(nc.date2num(datetime(2000,1,1),units[0])>=pairs[0][0] and nc.date2num(datetime(2000,1,1,0,10),units[0])<=pairs[-1][0],"FM BC does not cover proposed common clock")
        result.append({"node_id":name,"quantity":quantity,"time_unit":units[0],"physical_unit":units[1],"first_time":pairs[0][0],"last_time":pairs[-1][0],"initial_value":pairs[0][1]})
    return result


def audit(root, source, out):
    before=pinned_tree(root,source,out)
    graph=rr_topology((source/"rr/3B_NOD.TP").read_bytes(),(source/"rr/3B_LINK.TP").read_bytes())
    contract=config_contract((source/"dimr_config.xml").read_bytes())
    matched=matching_exchanges(contract,graph,(source/"fm/moergestels_broek_new.ext").read_bytes(),(source/"rr/BoundaryConditions.bc").read_bytes())
    locations=branch_locations(source/"fm/moergestels_broek_net.nc",matched)
    optionals=optional_classification(source/"rr",graph)
    clocks={"FM":fm_clock((source/"fm/moergestels_broek.mdu").read_bytes()),"RR":rr_clock((source/"rr/DELFT_3B.INI").read_bytes()),"DIMR_groups":contract["groups"]}
    rain=rain_contract((source/"rr/DEFAULT.BUI").read_bytes())
    named_stations=set()
    for name,key in (("PAVED.3B","PAVE"),("UNPAVED.3B","UNPV"),("OPENWATE.3B","OWRR")):
        named_stations.update(token(row,"ms") for row in token_records((source/"rr"/name).read_bytes(),key))
    require(named_stations<=set(rain["stations"]),"Active node meteorological station absent from candidate rain file")
    fm_forcing=boundary_forcing_audit(source)
    proof=engine_proofs(root,out)
    write(out/"topology-and-matching-exchanges.json",{"graph":graph,"matches":matched,"FM_locations":locations})
    write(out/"FNM-node-option-classification.json",optionals)
    write(out/"clocks-and-input-units.json",{"clocks":clocks,"rainfall":rain,"active_station_ids":sorted(named_stations),"FM_boundaries":fm_forcing})
    common={"start":clocks["FM"]["start"],"stop":clocks["FM"]["stop"],"seconds":[0,300,600],"rr_step_seconds":300,"fm_dtuser_seconds":60}
    write(out/"candidate-controls-and-clock-plan.json",{
        "state":"plan_only_no_inputs_edited","whole_source":str(source),"ids":matched["exchange_ids"],"common_clock":common,
        "common_preparation_required":["Fresh whole-tree copies; explicitly shorten RR EndTime to 2000/01/01;00:10:00; preserve first rain event/time origin", "Common FM/history/map instrumentation at exchange times, final restart600s, raw RR received levels and outflows, both DIMR coupler logs", "Freeze every linked file and executable hash before launches"],
        "rain_control":{"positive":"Original f152 rain", "control":"Zero only numerical rain matrix in an otherwise identical fresh copy", "preserve":"RR topology/parameters/IDs, evaporation, seepage, FM hydraulic inputs, clocks and schedules", "acceptance":"Actual RR runoff and FM lateral/source response must differ beyond declared tolerances; if 600s rain response is equal, report nondiscriminating, not success"},
        "hydraulic_control":{"candidate_boundary_ids":[b["node_id"] for b in fm_forcing if b["quantity"]=="waterlevelbnd"],"physical_unit":"m", "control":"An explicit bounded perturbation of an existing waterlevel boundary time series; preserve rain/RR settings/all other inputs", "acceptance":"Actual FM lateral water levels -> actual RR received boundary levels -> actual RR runoff response -> actual FM applied lateral; do not substitute commands/logged sends for receiver data"},
        "tolerances":TOLERANCES|{"RR_received_level_atol_m":1e-7,"RR_received_level_rtol":2**-24,"rounding_basis":"Pinned rr_dll_bmi set_var stores sngl(value_to_rr) in BndPar"},
        "native_launch_authorized":False})
    after=fingerprints(source);write(out/"source-tree-hashes.after.json",after)
    require(before==after,"Read-only audit changed source tree")
    unresolved=[i for i in optionals["empty_or_missing_inputs"] if i["classification"]=="unresolved_optional_predicate"]
    return {"state":"candidate_graph_ids_and_input_units_verified_native_pending","native_performed":False,"source_unchanged":True,
            "source_commit":HELPER_PIN,"source_receipt_sha256":RECEIPT_SHA,"source_files":len(before),"RR_nodes":len(graph["nodes"]),"RR_links":len(graph["links"]),
            "RR_internal_types":graph["internal_type_counts"],"matched_pairs_each_direction":len(matched["exchange_ids"]),"FM_lateral_locations":locations["verified_lateral_locations"],
            "boundary_nodes_without_links":graph["boundary_nodes_without_links"],
            "source_clocks":clocks,"common_clock_reconciliation":"required: RR86400s vs FM/DIMR600s; no silent truncation or completion claim",
            "unresolved_FNM_slots":[{"slot":i["slot"],"name":i["name"]} for i in unresolved],
            "reader_source_hashes":proof,"native_readiness":"not_yet: common clocks/instrumentation/public RR adapter, lease and real positive/control evidence required",
            "scientific_validation":"not_performed","rain_discrimination":"not established by static nonzero input; actual hydraulic response must be observed"}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True,help="Complete coordinator-materialized matching f152 tree, read-only")
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[3])
    a=p.parse_args(argv);source=a.source.resolve(strict=True);out=a.out.resolve()
    if out.is_relative_to(source):p.error("New output must be outside existing source")
    out.mkdir(parents=True,exist_ok=False)
    result={"state":"failed","native_performed":False}
    try:result=audit(a.root.resolve(strict=True),source,out)
    except Exception as exc:result["failure"]={"type":type(exc).__name__,"message":str(exc)}
    write(out/"verification.json",result)
    print(json.dumps({"state":result["state"],"native_performed":False,"evidence":str(out),"failure":result.get("failure")},indent=2))
    return 4 if result["state"]=="failed" else 0


if __name__=="__main__":
    raise SystemExit(main())
