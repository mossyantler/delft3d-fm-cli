"""Independent official10 FM/RTC pair replay through the PUBLIC coupling CLI.

Default mode prepares/reviews only. Native launches require --native and the
coordinator's currently assigned --native-slot; the flag does not acquire a slot.
No product module imports, DLL loading, model repair, generic CF relabelling,
best-fit lag, or synthetic native output. Both authored specs must be supplied.
RR authoring/replay stays in verify_rtc_exchange_rr*.py.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .verify_fields import expected_edit, occurrences, netcdf_differential
from .verify_rtc_exchange import (ENGINE_PIN, RTC_EXAMPLE, FBC_SOURCE, contained, fingerprints,
    git_blob, local, lookup, lookup_contract, read_nc_scalar, read_pi_scalar, require, sha, write, xml)
from .verify_rtc_exchange_ownership import bind_raw_member_trace
from .verify_rtc_exchange_checkpoint import CHECKPOINT_DECLARATION,hydraulic_checkpoint

DECLARATION={"schema":1,"origin":"official10 derivative, FM+RTC only, Waves explicitly disabled",
             "duration_seconds":600,"step_seconds":60,"rule_y_shift_m":0.25,
             "scalar_atol_m":1e-6,"relative_tolerance":0.,"minimum_crest_effect_m":0.1,
             "minimum_FM_level_effect_m":1e-6,"minimum_weir_discharge_effect_m3_s":1e-6,
             "time_identity":"exact; FM source/logger/RTC received input at t; RTC output at t+60; FM crest after update at t+60",
             "masks":"required scalar/time evidence fully unmasked; map differential masks reported explicitly",
             "control":"Only numeric lookup y attributes change by +0.25m; same x/LINEAR/BLOCK, initial states, model/forcing/units/clocks and non-target hashes",
             "CSV_terminal_input":"May be blank at600 because no inbound exchange at600; output at600 must be finite, never fabricated",
             "native_acceptance":"requires raw logger, receiver/controller streamed CSV, actual FM crest/hydraulic response, all final clocks and owned cleanup",
             "RTC_execution":"limitedMemory=true; EXPLICIT received input; pinned limited-memory PI writer disabled; no PI output expected"}

# Prospective observable correction, declared before any new native lease.
# Historical #53 and its original predeclared-oracle.json remain unchanged.
DECLARATION.update(hydraulic_observable="Signed sum of actual map q1 on topology-derived interior links crossing unchanged weir01.pli; all11 samples finite; raw missing weir history remains missing",
                   downstream_response="Actual Downstream waterlevel difference must exceed unchanged1e-6m threshold",
                   masks="Required level/crest/log/CSV/section values unmasked; actual weirgen_discharge masks retained diagnostically, never filled",
                   initial_hydraulic_identity="Both actual geometric section discharges start equal within unchanged1e-6m3/s; no masked initial history discharge used")
DECLARATION.update(live_exchange_causal_hydraulics_gate="All10 receiver/rule/actuator transactions for each arm, final hydraulic checkpoint projected to corresponding map cells/links, and paired signed section/downstream effects at unchanged thresholds",
                   hydraulic_checkpoint=CHECKPOINT_DECLARATION,
                   saved_actuator_restorability_gate="Separate not_established result when restart actuator state absent; live history crest is not saved restart state. No actual restore has been verified.")


def iso_start(spec):
    values=[datetime.fromisoformat(spec["clock"][k].replace("Z","+00:00")) for k in ("reference","start","stop")]
    require(all(v.utcoffset()==timedelta(0) for v in values),"Reference/start/stop must explicitly use UTC")
    require(values[0]==values[1] and (values[2]-values[1]).total_seconds()==600,"RTC pair must use the predeclared reference=start,600s clock")
    return values[1].replace(tzinfo=None)


def shifted_y_only(before,after,amount=Decimal("0.25")):
    """Byte-preserving numeric y-only difference, independent of author/parser."""
    pattern=rb"(<record\b[^>]*\by\s*=\s*['\"])([^'\"]+)(['\"][^>]*>)"
    left,right=list(re.finditer(pattern,before)),list(re.finditer(pattern,after))
    require(len(left)==len(right)==4,"Official10 must retain its four lookup records")
    for a,b in zip(left,right):
        require(Decimal(b[2].decode())-Decimal(a[2].decode())==amount,"Controller y shift differs from predeclared +0.25m")
    require(re.sub(pattern,rb"\1<Y>\3",before)==re.sub(pattern,rb"\1<Y>\3",after),"Changed rule alters bytes outside numeric y attributes")
    baseline,changed=lookup_contract(before),lookup_contract(after)
    require(baseline["knots"]==[(0.,0.),(2.,0.),(10.,5.),(20.,5.)],"Baseline lookup is not the actual official10 rule")
    require([x for x,y in baseline["knots"]]==[x for x,y in changed["knots"]],"Lookup x coordinates changed")
    return {"state":"passed","baseline_knots":baseline["knots"],"changed_knots":changed["knots"],"shift_m":float(amount)}


def source_inventory(path):
    path=Path(path).resolve(strict=True);spec=json.loads(path.read_bytes())
    require(spec["profile"]=="fm_rtc","Replay requires the explicit two-component fm_rtc profile")
    start=iso_start(spec)
    require(sorted(c["library"] for c in spec["components"])==["FBCTools_BMI","dflowfm"],"RTC derivative must contain exactly FM+RTC, without Waves")
    root=(path.parent/spec["source"]["root"]).resolve(strict=True)
    names=spec["source"]["files"]
    require(len(names)==len(set(names)),"Duplicate authored source file")
    files={name:sha(contained(root,root,name)) for name in names}
    for name in names:
        require(Path(name).suffix.lower() not in {".exe",".dll",".bat",".cmd",".ps1"},"Authored model inventory contains executable code")
    return {"path":path,"spec":spec,"root":root,"files":files,"start":start,"spec_sha256":sha(path)}


def expected_payload(info):
    result={name:(info["root"]/name).read_bytes() for name in info["files"]}
    for p in info["spec"]["patches"]:
        result[p["file"]]=expected_edit(result[p["file"]],p["section"]+"/"+p["key"],p["value"],p["occurrence"])
    return result


def compare_sources(positive,changed):
    a,b=positive["spec"],changed["spec"]
    for key in ("profile","clock","components","control","couplers","patches","observables"):
        require(a[key]==b[key],"Pair changes non-controller specification: "+key)
    require(set(positive["files"])==set(changed["files"]),"Pair changes source file set")
    differences=[name for name,value in positive["files"].items() if changed["files"][name]!=value]
    require(len(differences)==1 and differences[0].endswith("/rtcToolsConfig.xml"),"Exactly one controller configuration may differ")
    target=differences[0]
    result=shifted_y_only((positive["root"]/target).read_bytes(),(changed["root"]/target).read_bytes())
    return {"target":target,"source_rule_check":result,"all_other_source_files_identical":len(positive["files"])-1}


def component_paths(spec):
    fm=next(c for c in spec["components"] if c["library"]=="dflowfm")
    rtc=next(c for c in spec["components"] if c["library"]=="FBCTools_BMI")
    inbound=next(c for c in spec["couplers"] if c["source_component"]==fm["name"] and c["target_component"]==rtc["name"])
    outbound=next(c for c in spec["couplers"] if c["source_component"]==rtc["name"] and c["target_component"]==fm["name"])
    require(len(inbound["items"])==len(outbound["items"])==1,"One explicit level/crest exchange pair required")
    first,last=inbound["items"][0],outbound["items"][0]
    require(first["source"]=="observations/Upstream/water_level" and first["target"]=="input_ObservationPoint01_water_level" and
            last["source"]=="output_weir_crest_level" and last["target"]=="weirs/weir01/crestlevel","Endpoints differ from the declared official10 derivative")
    require(first["unit"]==last["unit"]=="m","Water-level/crest units must explicitly be metres")
    for c in (inbound,outbound):
        require(c["items"][0]["quantity"] in {"water_level","crest_level"},"Incorrect physical quantity")
    fm_observables=[o for o in spec["observables"] if o["component"]==fm["name"] and o["format"]=="netcdf"]
    observed={key:next((o["path"] for o in fm_observables if o["variable"]==key),None) for key in ("waterlevel","weirgen_crest_level","weirgen_discharge")}
    require(all(observed.values()) and len(set(observed.values()))==1,"Declare FM waterlevel, actual weir crest and discharge in one history dataset")
    outputs=[o for o in spec["observables"] if o["component"]==rtc["name"]]
    require(len(outputs)==1 and outputs[0]["format"]=="rtc_csv" and outputs[0]["variable"]=="output_weir_crest_level" and outputs[0]["unit"]=="m" and outputs[0]["time_variable"]=="date time","One explicit native streamed RTC CSV output is required")
    logs={}
    for name,c in (("inbound",inbound),("outbound",outbound)):
        obs=[o for o in spec["observables"] if o["component"]=="@"+c["name"]]
        require(len(obs)==1 and obs[0]["format"]=="dimr_logger" and obs[0]["variable"]=="item1_values" and obs[0]["time_variable"]=="time_offset" and
                obs[0]["sample_semantics"]=="exchange_before_master","Each actual scalar logger must have an explicit native offset observable")
        logs[name]={"path":obs[0]["path"],"source":c["items"][0]["source"],"target":c["items"][0]["target"]}
    return {"fm":fm,"rtc":rtc,"history":observed["waterlevel"],"csv_output":outputs[0]["path"],"logs":logs}


def read_dimr_logger(path,source,target,start,offsets):
    """Source-specific offset adapter; never changes generic CF interpretation."""
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        t,v=ds["time_offset"],ds["item1_values"]
        require(t.dimensions==("time_offset",) and v.ndim==2 and v.dimensions[0]=="time_offset" and v.shape[1]==1,"DIMR log must contain exactly one scalar per transaction")
        units=str(t.units).rstrip("\0");long_name=str(t.long_name).rstrip("\0")
        require(units=="seconds since 1980-01-01T00:00:00" and long_name=="seconds since simulation reference date, T00:00:00","Unreviewed native logger time metadata")
        require(getattr(v,"units",None) is None and str(v.long_name).rstrip("\0")==source+" -> "+target,"Native source/target identity or unit encoding differs")
        times,values=np.ma.asarray(t[:]),np.ma.asarray(v[:])
        require(not np.ma.getmaskarray(times).any() and not np.ma.getmaskarray(values).any() and np.isfinite(times.data).all() and np.isfinite(values.data).all(),"DIMR log has missing/nonfinite time/value")
        require(times.data.tolist()==list(offsets),"DIMR log actual offsets differ from [0,600)60s schedule")
        return {"path":str(path),"sha256":sha(path),"raw_units":units,"raw_long_name":long_name,"raw_offsets_seconds":times.data.tolist(),
                "iso":[(start+timedelta(seconds=n)).isoformat() for n in offsets],"values":values.data[:,0].astype(float).tolist(),"unit":"m",
                "interpretation":"Explicit FM reference offsets under pinned DIMR logger source; raw1980 label retained, not rewritten"}


def read_rtc_csv(path,start,step=60,duration=600):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.reader(f,delimiter=","))
    require(rows and rows[0][0]=="date time" and len(rows[0])==len(set(rows[0])),"RTC CSV has missing/duplicate scalar headers")
    columns={name:rows[0].index(name) for name in ("input_ObservationPoint01_water_level","output_weir_crest_level")}
    active="Control Group 1Lookup table_isActive"
    require(rows[0]==["date time","input_ObservationPoint01_water_level","output_weir_crest_level",active],"RTC CSV exact scalar/rule headers differ")
    require(len(rows)==duration//step+2,"RTC CSV actual row count does not include the exact final step")
    dates=[];values={name:[] for name in columns}
    for i,row in enumerate(rows[1:]):
        terminal=i==duration//step
        require(len(row)==(3 if terminal else 4),"RTC CSV scalar columns missing or unexpected terminal rule flag")
        if not terminal:
            require(float(row[3])==1.,"RTC lookup rule not active")
        date=datetime.strptime(row[0],"%Y-%m-%d %H:%M:%S")
        require(date==start+timedelta(seconds=i*step),"RTC CSV timestamps differ from declared native step")
        dates.append(date.isoformat())
        for name,index in columns.items():
            value=float(row[index]) if row[index] else None
            terminal_unset=(name.startswith("input_") and i==duration//step and value is None)
            require(terminal_unset or value is not None and math.isfinite(value),"RTC CSV required scalar is blank/nonfinite")
            values[name].append(value)
    return {"path":str(path),"sha256":sha(path),"iso":dates,"columns":values,
            "units_source":"Explicit RTC OpenMIExchangeItem m metadata; native CSV has scalar IDs and no units column",
            "terminal_input_value":values["input_ObservationPoint01_water_level"][-1]}


def scalar_near(left,right,message):
    require(len(left)==len(right) and all(abs(a-b)<=DECLARATION["scalar_atol_m"] for a,b in zip(left,right)),message)


def bootstrap_review(raw):
    root=xml(raw)
    require(local(root.tag)=="TimeSeries","PI bootstrap root differs")
    require([n.text for n in root if local(n.tag)=="timeZone"]==["0"],"PI bootstrap must explicitly use UTC0")
    series=[n for n in root if local(n.tag)=="series"]
    require(len(series)==1 and not [n for n in root.iter() if local(n.tag)=="event"],"PI bootstrap must have exactly one metadata-only, event-free unmapped series")
    headers=[n for n in series[0] if local(n.tag)=="header"]
    require(len(headers)==1,"PI bootstrap header missing/ambiguous")
    fields={local(n.tag):n.text for n in headers[0]}
    require(fields.get("locationId")=="interface_bootstrap" and fields.get("parameterId")=="unused","PI bootstrap may not provide a physical model input")
    return {"state":"metadata_only_unmapped_no_events","locationId":fields["locationId"],"parameterId":fields["parameterId"]}


def receipt_oracle(data,knots):
    """Five independent raw observation paths, with the fixed before-master phase."""
    inbound,outbound=data["inbound"],data["outbound"]
    received=data["csv"]["columns"]["input_ObservationPoint01_water_level"][:-1]
    computed=data["csv"]["columns"]["output_weir_crest_level"]
    level,crest=data["level"]["values"],data["crest"]["values"]
    require(len(level)==len(crest)==len(computed)==11 and len(received)==len(inbound["values"])==len(outbound["values"])==10,"Incomplete native transaction/final evidence")
    scalar_near(level[:-1],inbound["values"],"FM observed level differs from actual sent scalar")
    scalar_near(inbound["values"],received,"Logged FM level differs from actual RTC received state")
    expected=[lookup(knots,value) for value in received]
    scalar_near(expected,computed[1:],"RTC actual post-update output differs from independent controller")
    scalar_near(computed[1:],outbound["values"],"RTC computed output differs from actual sent crest")
    scalar_near(outbound["values"],crest[1:],"Actual FM applied crest differs from preceding RTC set value")
    scalar_near([crest[0],computed[0]],[0.,0.],"Initial FM/RTC states differ from explicit common0m")
    return {"state":"passed","transactions":10,"controller_expected_m":expected,"RTC_observed_final_seconds":600,
            "scope":"FM source -> actual DIMR send -> RTC CSV receiver -> independent rule -> streamed RTC CSV -> DIMR send -> actual FM next-step crest"}


class PublicCLI:
    def __init__(self,out):
        self.out=Path(out);self.commands=[]
        (self.out/"commands").mkdir()

    def argv(self,args):
        return [sys.executable,"-B","-m","dfm_cli",*map(str,args)]

    def record(self,label,argv,code):
        self.commands.append({"label":label,"argv":argv,"returncode":code})
        write(self.out/"commands.json",self.commands)

    def command(self,label,args,expected=0):
        argv=self.argv(args)
        r=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,timeout=40)
        (self.out/"commands"/(label+".stdout.json")).write_bytes(r.stdout)
        (self.out/"commands"/(label+".stderr.txt")).write_bytes(r.stderr)
        self.record(label,argv,r.returncode)
        payload=json.loads(r.stdout)
        require(r.returncode==expected and payload["ok"]==(expected==0) and payload["protocol_version"]==2,"Unexpected public CLI result: "+label+" "+str(payload.get("error")))
        return payload["result"] if expected==0 else payload["error"]

    def native(self,label,args,folder):
        """Only public coupling run may start native code, and only from main's lease branch."""
        argv=self.argv(args)
        handles=[];probe=None
        with (self.out/"commands"/(label+".stdout.json")).open("wb") as stdout,(self.out/"commands"/(label+".stderr.jsonl")).open("wb") as stderr:
            worker=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
            deadline=time.monotonic()+90
            try:
                while worker.poll() is None:
                    if probe is None:
                        try:
                            m=json.loads((Path(folder)/"manifest.json").read_bytes())
                            ident=m.get("ownership",{}).get("native_identity")
                            if ident:probe=NativeHandle(ident,m["argv"][0])
                        except (OSError,ValueError,KeyError):pass
                    if time.monotonic()>deadline:
                        self.command(label+"-bounded-cancel",["run","cancel",folder,"--wait","10"])
                        worker.wait(timeout=15)
                        raise AssertionError("Public native controller exceeded bounded90s; retained cancel evidence")
                    time.sleep(.01)
                code=worker.wait(timeout=5)
                self.record(label,argv,code)
                payload=json.loads((self.out/"commands"/(label+".stdout.json")).read_bytes())
                require(code==0 and payload["ok"] and payload["result"]["state"]=="completed","Native public command failed; preserve manifest/diagnostics: "+label)
                require(probe is not None,"Native identity was never independently retained; no exit inferred from PID disappearance")
                result={"public":payload["result"],"independent_root_handle":probe.confirm_exit()}
                write(self.out/"commands"/(label+"-independent-native-exit.json"),result["independent_root_handle"])
                return result
            finally:
                if worker.poll() is None:
                    try:self.command(label+"-exception-cancel",["run","cancel",folder,"--wait","10"])
                    finally:worker.wait(timeout=20)
                if probe is not None:probe.close()


class NativeHandle:
    """Read-only retained process handle, validated by creation identity and image."""
    def __init__(self,identity,expected_image):
        import ctypes as c
        from ctypes import wintypes as w
        self.c,self.w=c,w;self.k=c.WinDLL("kernel32",use_last_error=True)
        self.k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.k.OpenProcess.restype=w.HANDLE
        self.k.CloseHandle.argtypes=[w.HANDLE];self.k.CloseHandle.restype=w.BOOL
        self.k.GetProcessTimes.argtypes=[w.HANDLE,*([c.POINTER(w.FILETIME)]*4)];self.k.GetProcessTimes.restype=w.BOOL
        self.k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)];self.k.QueryFullProcessImageNameW.restype=w.BOOL
        self.k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];self.k.WaitForSingleObject.restype=w.DWORD
        self.k.GetExitCodeProcess.argtypes=[w.HANDLE,c.POINTER(w.DWORD)];self.k.GetExitCodeProcess.restype=w.BOOL
        self.handle=self.k.OpenProcess(0x100000|0x1000,False,identity["pid"])
        if not self.handle:raise OSError("Cannot independently retain native handle")
        try:
            dates=[w.FILETIME() for _ in range(4)]
            require(self.k.GetProcessTimes(self.handle,*[c.byref(t) for t in dates]),"Cannot validate native creation identity")
            birth=str((dates[0].dwHighDateTime<<32)|dates[0].dwLowDateTime)
            require(birth==identity["creation_time_100ns"],"Native PID was reused; retained handle identity differs")
            size=w.DWORD(32768);name=c.create_unicode_buffer(size.value)
            require(self.k.QueryFullProcessImageNameW(self.handle,0,name,c.byref(size)),"Native image unavailable")
            require(Path(name.value).resolve()==Path(expected_image).resolve(),"Native retained process executable differs")
            self.identity=dict(identity);self.image=name.value
        except BaseException:self.close();raise

    def confirm_exit(self):
        require(self.k.WaitForSingleObject(self.handle,0)==0,"Retained native handle has not signalled exit")
        code=self.w.DWORD()
        require(self.k.GetExitCodeProcess(self.handle,self.c.byref(code)),"Cannot read native retained-handle exit code")
        require(code.value==0,"Native retained handle exit code nonzero")
        return {"identity":self.identity,"image":self.image,"handle_signalled":True,"exit_code":code.value,"method":"retained native handle; no PID-absence inference"}

    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None


def source_and_input_review(info,prepared,out):
    expected=expected_payload(info)
    for name,raw in expected.items():
        require((prepared/name).read_bytes()==raw,"Public preparation changed bytes outside authored/previewed patches: "+name)
    paths=component_paths(info["spec"])
    fm=paths["fm"];mdu=prepared/fm["working_dir"]/fm["input_file"]
    settings={r["address"]:r["value"] for r in occurrences(mdu.read_bytes())}
    require(settings["geometry/kmx"]=="0" and settings["waves/wavemodelnr"]=="0","Derivative must explicitly disable Waves and3D")
    start=info["start"]
    require(settings["time/tzone"] in {"0","0."} and settings["time/tunit"].upper()=="S","FM clock/timezone must explicitly be UTC seconds")
    require(settings["time/startdatetime"]==start.strftime("%Y%m%d%H%M%S") and settings["time/stopdatetime"]==(start+timedelta(seconds=600)).strftime("%Y%m%d%H%M%S"),"Actual FM absolute clock differs from declaration")
    for address,value in (("time/dtuser",60),("output/hisinterval",60),("output/mapinterval",60),("output/rstinterval",600)):
        values=[float(v) for v in settings[address].split()]
        require(len(values) in {1,3} and values[0]==value,"Actual FM timestep/output schedule differs: "+address)
    rtc=paths["rtc"];work=prepared/rtc["working_dir"]
    dirs=json.loads((work/"settings.json").read_bytes())
    directory=contained(prepared,work,dirs["xmlDir"])
    runtime=xml((directory/"rtcRuntimeConfig.xml").read_bytes())
    for name,date in (("startDate",start),("endDate",start+timedelta(seconds=600))):
        nodes=[n for n in runtime.iter() if local(n.tag)==name]
        require(len(nodes)==1 and nodes[0].get("date")==date.date().isoformat() and nodes[0].get("time")==date.time().isoformat(),"Actual RTC period differs from case declaration")
    steps=[n for n in runtime.iter() if local(n.tag)=="timeStep"]
    require(len(steps)==1 and steps[0].get("unit")=="second" and float(steps[0].get("multiplier","1"))/float(steps[0].get("divider","1"))==60,"Actual RTC native step differs from60s group")
    memory=[n.text for n in runtime.iter() if local(n.tag)=="limitedMemory"]
    require(memory==["true"],"Live RTC BMI must use explicit limitedMemory=true under pinned implementation")
    config=xml((directory/"rtcDataConfig.xml").read_bytes())
    series={}
    for n in config.iter():
        if local(n.tag)!="timeSeries":continue
        require(n.get("id") not in series,"Duplicate RTC scalar identity")
        unit=[v.text for item in n if local(item.tag)=="OpenMIExchangeItem" for v in item if local(v.tag)=="unit"]
        require(unit==["m"],"Actual RTC scalar units differ from metre declaration")
        series[n.get("id")]=unit[0]
    require(set(series)=={"input_ObservationPoint01_water_level","output_weir_crest_level"},"Actual RTC scalar identity set differs")
    state=xml((directory/"state_import.xml").read_bytes());initial={}
    for n in state.iter():
        if local(n.tag)!="treeVectorLeaf":continue
        values=[float(v.text) for v in n if local(v.tag)=="vector"]
        require(len(values)==1 and math.isfinite(values[0]) and n.get("id") not in initial,"Initial RTC value missing/ambiguous/nonfinite")
        initial[n.get("id")]=values[0]
    require(initial=={key:0. for key in series},"Common initial RTC input/output must explicitly be finite0")
    structure=prepared/fm["working_dir"]/settings["geometry/structurefile"]
    fields={r["address"]:r["value"] for r in occurrences(structure.read_bytes())}
    require(fields.get("structure/id")=="weir01" and fields.get("structure/type","").casefold()=="weir" and fields.get("structure/crestlevel")=="0" and
            "structure/locationfile" in fields and "structure/polylinefile" not in fields,"Actual modern weir/initial0m differs from declaration")
    imports=[n for n in config if local(n.tag)=="importSeries"]
    require(len(imports)==1,"RTC import series block missing/duplicate")
    require(not [n for n in config.iter() if local(n.tag) in {"PITimeSeriesFile","PITimeSeries"}],"Limited-memory live BMI must not stage disabled PI writer/bootstrap")
    rule=xml((directory/"rtcToolsConfig.xml").read_bytes())
    refs=[n for n in rule.iter() if local(n.tag)=="x" and n.text=="input_ObservationPoint01_water_level"]
    require(len(refs)==1 and refs[0].get("ref")=="EXPLICIT","Lookup must consume received current-slot input, not future IMPLICIT state")
    csv_config=[n for n in config.iter() if local(n.tag)=="CSVTimeSeriesFile"]
    require(len(csv_config)==1 and csv_config[0].get("delimiter")=="," and csv_config[0].get("decimalSeparator")==".","Require exact native full CSV scalar writer")
    history=contained(prepared,prepared,paths["history"],exists=False)
    require(not history.exists(),"Prepared source already contains native history output")
    paths["csv_path"]=(directory/"timeseries_0000.csv").relative_to(prepared).as_posix()
    require(paths["csv_path"]==paths["csv_output"],"Declared RTC CSV observable differs from native writer path")
    paths["state_meta_path"]=(directory/"statePI.xml").relative_to(prepared).as_posix()
    paths["lookup_path"]=(directory/"rtcToolsConfig.xml").relative_to(prepared).as_posix()
    for name in (paths["csv_path"],paths["state_meta_path"],*(v["path"] for v in paths["logs"].values())):
        require(not (prepared/name).exists(),"Native output may not be staged as input: "+name)
    # Record all common deviations from actual official10 Git bytes, including
    # modern weir key, repaired duplicate support-point name and live BMI/CSV mode.
    repository=Path(__file__).resolve().parents[3]/"research/upstream/Delft3D"
    names=subprocess.check_output(["git","-C",str(repository),"ls-tree","-r","--name-only",ENGINE_PIN,RTC_EXAMPLE],stdin=subprocess.DEVNULL,timeout=15).decode().splitlines()
    official={Path(name).relative_to(RTC_EXAMPLE).as_posix():name for name in names}
    differences=[]
    for name,raw in expected.items():
        if name in official:
            old=git_blob(repository,ENGINE_PIN,official[name])
            if old!=raw:differences.append({"file":name,"pinned_sha256":hashlib.sha256(old).hexdigest(),"authored_sha256":hashlib.sha256(raw).hexdigest(),"classification":"explicit common authoring difference; not a controller effect"})
        else:differences.append({"file":name,"authored_sha256":hashlib.sha256(raw).hexdigest(),"classification":"explicit added authoring input"})
    return {"state":"passed","paths":paths,"RTC_writer":"streamed CSV; limited-memory PI writer disabled", "physical_input_files":{name:hashlib.sha256(raw).hexdigest() for name,raw in expected.items()},
            "official_source_commit":ENGINE_PIN,"official10_common_deviations":differences,
            "prepared_metadata_files":[name for name in fingerprints(prepared) if name not in expected]}


def prepare_pair(cli,positive,changed,out):
    comparison=compare_sources(positive,changed)
    reviews={}
    for label,info in (("positive",positive),("changed",changed)):
        folder=out/"cases"/label
        preview=cli.command(label+"-preview",["coupling","prepare",info["path"],"--out",folder])
        require(not folder.exists(),"Public preview wrote the prepared destination")
        require(source_inventory(info["path"])["files"]==info["files"],"Public preview changed authored inputs")
        cli.command(label+"-apply",["coupling","prepare",info["path"],"--out",folder,"--apply","--expect-sha256",preview["input_sha256"]])
        cli.command(label+"-validate",["coupling","validate",folder/"dimr_config.xml"])
        reviews[label]=source_and_input_review(info,folder,out)
        reviews[label]["prepared_folder"]=str(folder)
        reviews[label]["prepared_hashes"]=fingerprints(folder)
        require(source_inventory(info["path"])["files"]==info["files"],"Public apply changed original authored source")
    a,b=reviews["positive"]["physical_input_files"],reviews["changed"]["physical_input_files"]
    require([name for name in a if a[name]!=b[name]]==[comparison["target"]],"Public prepared pair changes more than the declared RTC rule")
    require((out/"cases/positive/dimr_config.xml").read_bytes()==(out/"cases/changed/dimr_config.xml").read_bytes(),"Controller pair changes the actual DIMR control/exchange configuration")
    write(out/"independent-input-reviews.json",reviews)
    return {"source_comparison":comparison,"cases":reviews}


def cf_axis(path):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        t=ds["time"];a=np.ma.asarray(t[:])
        require(a.ndim==1 and a.size and not np.ma.getmaskarray(a).any() and np.isfinite(a.data).all() and np.all(np.diff(a.data)>0),"Actual CF axis missing, masked, nonfinite or not increasing")
        return {"path":str(path),"sha256":sha(path),"units":t.units,"calendar":getattr(t,"calendar","standard"),
                "iso":[v.isoformat() for v in nc.num2date(a,t.units,calendar=getattr(t,"calendar","standard"))]}


def exact_schedule(actual,start,offsets,label):
    expected=[(start+timedelta(seconds=n)).isoformat() for n in offsets]
    require(actual["iso"]==expected,"Actual "+label+" time axis differs from predeclared schedule; no trimming or shifted timestamps")


def section_discharge(map_path,polyline_path,observation_path=None):
    """Independent geometric section; not a replacement for masked weir history."""
    import netCDF4 as nc
    import numpy as np
    lines=Path(polyline_path).read_text().splitlines()
    require([int(n) for n in lines[1].split()]==[2,2],"Require the actual two-point weir polyline")
    a,b=[np.array([float(n) for n in row.split()]) for row in lines[2:4]]
    tangent=b-a
    def cross(x,y):return float(x[0]*y[1]-x[1]*y[0])
    require(np.isfinite(a).all() and np.isfinite(b).all() and float(tangent@tangent)>0,"Invalid section geometry")
    observations=None
    if observation_path is not None:
        observations={}
        for line in Path(observation_path).read_text().splitlines():
            fields=line.split()
            if len(fields)==3 and fields[2] in {'Upstream','Downstream'}:
                require(fields[2] not in observations,'Duplicate section-side observation')
                observations[fields[2]]=[float(v) for v in fields[:2]]
        require(set(observations)=={'Upstream','Downstream'},'Actual section-side observations missing')
        require(all(np.isfinite(v).all() for v in observations.values()),'Invalid section-side coordinates')
        require(cross(tangent,np.array(observations['Upstream'])-a)<0<cross(tangent,np.array(observations['Downstream'])-a),'Section signed orientation is not actual Upstream to Downstream')
    with nc.Dataset(map_path) as ds:
        faces=np.ma.asarray(ds['mesh2d_edge_faces'][:]);offset=int(ds['mesh2d_edge_faces'].start_index)
        x,y=ds['mesh2d_face_x'],ds['mesh2d_face_y']
        require(x.units==y.units=='m',"Section requires explicit planar metre coordinates")
        require(not np.ma.getmaskarray(x[:]).any() and not np.ma.getmaskarray(y[:]).any(),"Missing face coordinates")
        centers=np.column_stack((x[:],y[:]))
        require(not np.ma.getmaskarray(centers).any() and np.isfinite(centers).all(),"Missing face coordinates")
        topology_sha256=hashlib.sha256(json.dumps({'face_xy':centers.tolist(),'edge_faces':faces.filled(-999).tolist(),'start_index':offset},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        edges=[];signs=[];locations=[]
        for i,row in enumerate(faces):
            if np.ma.getmaskarray(row).any():continue
            ids=row.data.astype(int)-offset
            require((ids>=0).all() and (ids<len(centers)).all(),"Edge face index outside actual mesh")
            p,q=centers[ids];delta=q-p;den=cross(delta,tangent)
            if abs(den)<=1e-10:continue
            u=cross(a-p,tangent)/den;v=cross(a-p,delta)/den
            if 0<u<1 and 0<v<1:
                edges.append(i);signs.append(1. if cross(tangent,q-a)>cross(tangent,p-a) else -1.);locations.append((p+u*delta).tolist())
        require(edges,"No interior flow links cross actual weir polyline")
        var=ds['mesh2d_q1'];values=np.ma.asarray(var[:,edges])
        require(var.units=='m3 s-1' and var.dimensions==('time','mesh2d_nEdges') and var.location=='edge',"Incorrect map flow location/units")
        require(var.comment=='Positive direction is from first to second neighbouring face (flow element).',"Unreviewed native flow orientation")
        require(not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(),"Section physical discharge masked/nonfinite")
        total=(values.data*np.array(signs)).sum(axis=1).tolist()
    return {"state":"finite_observation_only_not_acceptance","map_path":str(map_path),"polyline_path":str(polyline_path),
            "map_sha256":sha(map_path),"polyline_sha256":sha(polyline_path),"topology_sha256":topology_sha256,"edge_indices_zero_based":edges,"signed_orientation":signs,
            "intersection_xy_m":locations,"values":total,"unit":"m3 s-1","axis":cf_axis(map_path),"iso":cf_axis(map_path)["iso"],
            "positive_direction":"negative to positive cross(polyline tangent, face minus first polyline vertex)",
            "physical_orientation":"Upstream to Downstream" if observations else "geometry only; observation side identity not provided",
            "observation_xy_m":observations,"observation_sha256":sha(observation_path) if observation_path else None,
            "scope":"Actual finite geometric section; no missing physical weir discharge filled; future paired control response still required"}


def audit_recorded(evidence,out):
    """Offline replay of immutable retained evidence, explicitly never acceptance."""
    evidence=Path(evidence).resolve(strict=True);out=Path(out).resolve()
    require(not out.is_relative_to(evidence),"Offline report must be outside historical evidence")
    before=fingerprints(evidence);out.mkdir(parents=True,exist_ok=False)
    previous=json.loads((evidence/'verification.json').read_bytes())
    review=previous['pair']['cases']['positive'];model=evidence/'runs/positive/model';paths=review['paths']
    # The recorded authored specification, not the logger's hardcoded1980 label,
    # supplies the clock. Refuse any reviewed prepared clock disagreement.
    runtime=xml((model/paths['lookup_path']).with_name('rtcRuntimeConfig.xml').read_bytes())
    periods=[n for n in runtime.iter() if local(n.tag)=='startDate']
    require(len(periods)==1,"Recorded RTC start missing/ambiguous")
    start=datetime.fromisoformat(periods[0].get('date')+'T'+periods[0].get('time'))
    fm=paths['fm'];settings={r['address']:r['value'] for r in occurrences((model/fm['working_dir']/fm['input_file']).read_bytes())}
    require(settings['time/tzone'] in {'0','0.'} and settings['time/tunit'].upper()=='S' and settings['time/startdatetime']==start.strftime('%Y%m%d%H%M%S') and settings['time/stopdatetime']==(start+timedelta(seconds=600)).strftime('%Y%m%d%H%M%S'),"Actual FM/RTC clocks disagree")
    report={'state':'offline_partial_not_acceptance','historical_evidence':str(evidence),'historical_state':previous['state'],
            'native_performed':False,'original_report_sha256':sha(evidence/'verification.json'),'original_predeclared_oracle':json.loads((evidence/'predeclared-oracle.json').read_bytes()),'prospective_plan':DECLARATION,'raw':{},'checks':{}}
    raw=report['raw'];history=model/paths['history']
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(history) as ds:station='station_id' if 'station_id' in ds.variables else 'station_name'
    for key,var,identifier in [('level','waterlevel',(station,'Upstream')),('downstream','waterlevel',(station,'Downstream')),('crest','weirgen_crest_level',('weirgen_name','weir01')),('discharge','weirgen_discharge',('weirgen_name','weir01'))]:
        try:
            raw[key]=read_nc_scalar(history,var,identifier);exact_schedule(raw[key],start,range(0,601,60),key)
            report['checks'][key]={'state':'passed'}
        except Exception as exc:report['checks'][key]={'state':'failed','message':str(exc)}
    with nc.Dataset(history) as ds:
        q=np.ma.asarray(ds['weirgen_discharge'][:]);mask=np.ma.getmaskarray(q)
        report['physical_discharge']={'raw_values':[[None if m else float(v) for v,m in zip(row,mrow)] for row,mrow in zip(q.data,mask)],'mask':mask.tolist(),'unit':ds['weirgen_discharge'].units,'masked_count':int(mask.sum()),'policy':'never filled or equated to zero'}
    for name,log in paths['logs'].items():raw[name]=read_dimr_logger(model/log['path'],log['source'],log['target'],start,range(0,600,60))
    raw['csv']=read_rtc_csv(model/paths['csv_path'],start)
    report['checks']['exchange_chain']=receipt_oracle(raw,lookup_contract((model/paths['lookup_path']).read_bytes())['knots'])
    maps=list((model/'fm').rglob('*_map.nc'));require(len(maps)==1,"Ambiguous recorded map")
    report['section_plan_observation']=section_discharge(maps[0],model/'fm/weir01.pli',model/'fm/obs.xyn')
    report['causal_pair']='not_performed; changed arm unlaunched'
    report['acceptance']='not_established; historical gate outcome retained; missing history values remain missing'
    report['historical_files_unchanged']=fingerprints(evidence)==before
    require(report['historical_files_unchanged'],"Offline reader altered historical evidence")
    write(out/'offline-audit.json',report)
    return report


def terminal_receipt(manifest,independent_root=None):
    require(manifest["state"]=="completed" and type(manifest["returncode"]) is int and manifest["returncode"]==0 and manifest["verification"]["state"]=="passed","Public run did not complete with component output verification")
    own=manifest["ownership"]
    require(own["method"]=="windows_job_object" and own["assigned_before_resume"] is True,"Native ownership was not established before resume")
    normal=own.get("normal_exit")
    if normal is not None:
        require(normal.get('method')=='windows_job_object_normal_exit' and normal.get('state')=='captured' and normal.get('termination_attempted') is False,"Natural exit capture unavailable or forced")
        root=normal.get('root',{});account=normal.get('job_accounting',{});members=normal.get('job_members',{})
        def integers(obj,keys):
            require(all(type(obj.get(key)) is int for key in keys),'Native proof numeric fields must be JSON integers, never Boolean/float/null')
        integers(root,('pid','wait_result','wait_timeout_ms','exit_code'))
        integers(account,('information_class','buffer_bytes','returned_bytes'))
        integers(normal,('retained_member_handle_count','confirmed_member_exit_count','unobserved_member_count','total_processes','active_processes'))
        if independent_root:
            integers(independent_root,('exit_code',))
            integers(independent_root.get('identity',{}),('pid',))
        identity=own.get('native_identity',{});pid=identity.get('pid')
        require(type(pid) is int and pid>0 and identity.get('creation_time_100ns'),"Launch identity absent")
        require(independent_root and independent_root.get('identity')==identity and independent_root.get('handle_signalled') is True and independent_root.get('exit_code')==0 and Path(independent_root['image']).resolve()==Path(manifest['argv'][0]).resolve(),"Independent retained root identity/image/exit differs from launch capture")
        require(root.get('pid')==pid and root.get('handle_source')=='original_subprocess.Popen._handle' and root.get('state')=='signalled' and root.get('wait_result')==0 and root.get('wait_timeout_ms')==0 and root.get('exit_confirmed') is True and root.get('exit_code')==0 and root.get('exit_code_query',{}).get('state')=='captured',"Original retained launch handle did not prove successful natural exit")
        if normal.get('member_trace') is not None:
            trace=normal['member_trace'];proof=bind_raw_member_trace(trace,independent_root)
            require(account==trace['accounting'] and members==trace['job_members'],'Outer natural capture and per-member Job snapshots differ')
            total=trace['accounting']['values']['TotalProcesses']
            require(normal['total_processes']==total and normal['active_processes']==0 and normal.get('sole_ever_member') is (total==1),'Outer natural accounting summaries differ')
            confirmations={str(m['identity']['pid']):True for m in trace['members']}
            require(normal.get('member_exit_confirmations')==confirmations and all(type(v) is bool for v in normal['member_exit_confirmations'].values()),'Outer per-member exit confirmations incomplete')
            require(normal['retained_member_handle_count']==normal['confirmed_member_exit_count']==total and normal['unobserved_member_count']==0 and normal.get('all_owned_members_exit_confirmed') is True and normal.get('root_exit_confirmed') is True,'Outer retained member-handle coverage incomplete')
            require(normal.get('job_empty') is True and normal.get('job_pids_after')==[] and own.get('final_job_pids')==[] and own.get('kill_on_owner_handle_close') is True,'Exact final private Job confinement/empty proof absent')
            require(not any(obj.get('error') for obj in (normal,root,account,members)),'Natural capture contains query errors')
            return {'state':'passed','ownership':own,'normal_exit':normal,'independent_root_handle':independent_root,'member_proof':proof,'scope':'Every real Job member retained and independently source-bound raw lifecycle proof; independent original root identity/image/exit also matches. No forced termination required.'}
        require(account.get('state')=='captured' and account.get('handle_source')=='retained_OwnedJob.handle' and account.get('information_class')==1 and account.get('structure')=='JOBOBJECT_BASIC_ACCOUNTING_INFORMATION' and account.get('buffer_bytes')==account.get('returned_bytes')==48,"Genuine retained Job accounting not captured")
        counts=account.get('values',{})
        integers(counts,('TotalProcesses','ActiveProcesses','TotalTerminatedProcesses'))
        integers(counts,tuple(counts))
        require(counts.get('TotalProcesses')==1 and counts.get('ActiveProcesses')==0 and counts.get('TotalTerminatedProcesses')==0,"Single-root proof cannot cover historical descendants, active members or limit violations")
        require(normal['total_processes']==counts['TotalProcesses'] and normal['active_processes']==counts['ActiveProcesses'],'Job accounting count summaries disagree')
        require(members.get('state')=='captured' and members.get('pids')==[] and normal.get('job_pids_after')==[] and own.get('final_job_pids')==[] and own.get('kill_on_owner_handle_close') is True,"Exact retained Job empty check absent")
        require(normal.get('member_exit_confirmations')=={str(pid):True} and normal.get('retained_member_handle_count')==normal.get('confirmed_member_exit_count')==1 and normal.get('unobserved_member_count')==0 and normal.get('sole_ever_member') is True and normal.get('all_owned_members_exit_confirmed') is True and normal.get('root_exit_confirmed') is True and normal.get('job_empty') is True,"Sole-ever member retained handle coverage incomplete")
        require(not any(obj.get('error') for obj in (normal,root,account,members)),"Normal capture contains query errors")
        return {'state':'passed','ownership':own,'normal_exit':normal,'independent_root_handle':independent_root,'scope':'Original launch root handle plus independently retained matching identity; genuine sole-ever-member Job accounting and empty exact Job; no forced termination required'}
    term=manifest.get("termination") or {}
    require(term.get("tree_terminated") is True and term.get("job_pids_after")==[] and term.get("owned_process_exited") is True,"Exact owned Job/root exit not confirmed")
    exits=term.get("member_exit_confirmations")
    require(exits and all(value is True for value in exits.values()),"Retained owned member handles did not all signal exit")
    return {"state":"passed","ownership":own,"termination":term,
            "scope":"Common owned runner retained member-handle exits plus empty exact Job; root disappearance is not used"}


def verify_outputs(folder,spec,review,start,independent_root=None):
    import netCDF4 as nc
    import numpy as np
    folder=Path(folder);model=folder/"model";paths=review["paths"]
    manifest=json.loads((folder/"manifest.json").read_bytes())
    cleanup=terminal_receipt(manifest,independent_root)
    for name,digest in review["physical_input_files"].items():
        require(sha(model/name)==digest,"Actual native input changed: "+name)
    history=contained(model,model,paths["history"])
    with nc.Dataset(history) as ds:
        station_id="station_id" if "station_id" in ds.variables else "station_name"
        require(station_id in ds.variables,"FM station identity absent")
        require("weirgen_name" in ds.variables,"Pinned actual weir identity absent")
    data={"level":read_nc_scalar(history,"waterlevel",(station_id,"Upstream")),
          "downstream":read_nc_scalar(history,"waterlevel",(station_id,"Downstream")),
          "crest":read_nc_scalar(history,"weirgen_crest_level",("weirgen_name","weir01"))}
    for key,series in data.items():
        require(series["unit"]==("m3 s-1" if key=="discharge" else "m"),"Actual FM scalar units differ: "+key)
        exact_schedule(series,start,range(0,601,60),"FM "+key)
    for name,log in paths["logs"].items():
        data[name]=read_dimr_logger(contained(model,model,log["path"]),log["source"],log["target"],start,range(0,600,60))
    data["csv"]=read_rtc_csv(contained(model,model,paths["csv_path"]),start)
    knots=lookup_contract((model/paths["lookup_path"]).read_bytes())["knots"]
    chain=receipt_oracle(data,knots)
    require(max(data["level"]["values"][:-1])>2.+DECLARATION["scalar_atol_m"],"Actual RTC input never reached the original nonflat lookup region; forcing alone is not proof")
    require(max(chain["controller_expected_m"])-min(chain["controller_expected_m"])>DECLARATION["scalar_atol_m"],"Actual controller response was constant; cannot establish input-dependent control")
    # StatePI's source always labels configured endTime, so do not use it alone
    # to prove current time. Require actual inclusive streamed CSV plus completed chain.
    state=xml(contained(model,model,paths["state_meta_path"]).read_bytes())
    stamp=[n for n in state if local(n.tag)=="dateTime"]
    require(len(stamp)==1 and stamp[0].get("date")+"T"+stamp[0].get("time")== (start+timedelta(seconds=600)).isoformat(),"RTC final state metadata differs from requested stop")
    fm_work=contained(model,model,paths["fm"]["working_dir"])
    maps=[p for p in fm_work.rglob("*_map.nc") if p.is_file()]
    require(len(maps)==1,"Expected exactly one actual FM map dataset")
    map_axis=cf_axis(maps[0]);exact_schedule(map_axis,start,range(0,601,60),"FM map")
    data['section_discharge']=section_discharge(maps[0],model/'fm/weir01.pli',model/'fm/obs.xyn')
    exact_schedule(data['section_discharge'],start,range(0,601,60),'actual signed through-weir section')
    with nc.Dataset(history) as ds:
        q=np.ma.asarray(ds['weirgen_discharge'][:]);mask=np.ma.getmaskarray(q)
        require(q.shape==(11,1) and ds['weirgen_discharge'].units=='m3 s-1',"Unexpected raw physical weir discharge layout/units")
        require(np.isfinite(q.data[~mask]).all(),"Unmasked history discharge nonfinite")
        data['discharge_history']={'path':str(history),'sha256':sha(history),'unit':ds['weirgen_discharge'].units,'iso':map_axis['iso'],
             'values':[None if m else float(v) for v,m in zip(q.data[:,0],mask[:,0])],'mask':mask[:,0].tolist(),'scope':'Native missing samples retained; never substituted by section values'}
    restarts=[p for p in fm_work.rglob("*_rst.nc") if p.is_file()]
    final=[p for p in restarts if cf_axis(p)["iso"]==[(start+timedelta(seconds=600)).isoformat()]]
    require(len(final)==1,"Expected exactly one observed final600s restart")
    restart_axis=cf_axis(final[0])
    checkpoint=hydraulic_checkpoint(final[0],maps[0],history,official10_identity=True)
    return {"state":"passed","chain":chain,"raw":data,"FM_map_axis":map_axis,"FM_final_restart_axis":restart_axis,
            "hydraulic_checkpoint_gate":checkpoint,"saved_actuator_restorability_gate":checkpoint['saved_actuator_restorability_gate'],
            "cleanup":cleanup,"diagnostics":manifest.get("diagnostics"),"executable_sha256":manifest["executable_sha256"],"native_argv":manifest["argv"],
            "final_RTC_proof":"Actual streamed CSV terminal scalar plus10 source-backed update/receiver/output transactions, not metadata or zero exit alone"}


def causal_comparison(positive,changed):
    def delta(key):
        a,b=positive["raw"][key],changed["raw"][key]
        require(a["iso"]==b["iso"] and a["unit"]==b["unit"],"Pair time/units differ: "+key)
        return [y-x for x,y in zip(a["values"],b["values"])]
    a,b=positive['raw']['section_discharge'],changed['raw']['section_discharge']
    for key in ('edge_indices_zero_based','signed_orientation','intersection_xy_m','polyline_sha256','topology_sha256','observation_sha256','observation_xy_m','physical_orientation'):
        require(a[key]==b[key],'Pair geometric through-weir section changed: '+key)
    crest,flow,level,down=delta("crest"),delta("section_discharge"),delta("level"),delta("downstream")
    require(abs(crest[0])<=DECLARATION["scalar_atol_m"] and abs(flow[0])<=DECLARATION["minimum_weir_discharge_effect_m3_s"] and abs(level[0])<=DECLARATION["scalar_atol_m"],"Pair already differs before the declared control intervention")
    require(max(map(abs,crest[1:]))>DECLARATION["minimum_crest_effect_m"],"No discriminating actual FM actuator response")
    require(max(map(abs,flow[1:]))>DECLARATION["minimum_weir_discharge_effect_m3_s"],"No actual weir hydraulic discharge effect")
    require(max(map(abs,down[1:]))>DECLARATION["minimum_FM_level_effect_m"],"No actual downstream FM water-level hydraulic effect")
    require(positive["executable_sha256"]==changed["executable_sha256"],"Pair used different native DIMR executables")
    differences={"history":netcdf_differential(positive["raw"]["level"]["path"],changed["raw"]["level"]["path"]),
                 "map":netcdf_differential(positive["FM_map_axis"]["path"],changed["FM_map_axis"]["path"])}
    return {"state":"passed","difference":"changed_minus_positive","crest_difference_m":crest,"signed_through_weir_section_difference_m3_s":flow,
            "Upstream_difference_m":level,"Downstream_difference_m":down,"raw_dataset_differences":differences,
            "scientific_validation":"not_performed","causal_scope":"Matched frozen inputs with only lookup y changes; actual receipt/control/actuator and hydraulic responses observed separately"}


def binary_inventory(install):
    result={}
    for name in ("bin/dimr.exe","lib/dimr.dll","lib/dflowfm.dll","lib/FBCTools_BMI.dll"):
        paths=list(Path(install).glob("plugins/DeltaShell.Dimr/kernels/*/"+name))
        require(len(paths)==1,"Selected component binary missing/ambiguous: "+name)
        result[name]={"path":str(paths[0]),"sha256":sha(paths[0])}
    return result


def product_inventory(root):
    paths=set((root/"src/dfm_cli").glob("coupling*.py"))
    paths.update((root/"src/dfm_cli").glob("windows_job_trace*.py"))
    paths.update(root/"src/dfm_cli"/name for name in ("cli.py","common.py","runs.py","run_control.py","windows_job.py","windows_exit_evidence.py","outputs.py","installation.py","diagnostics.py"))
    return {str(p.relative_to(root)):sha(p) for p in sorted(paths) if p.is_file()}


def run_pair(cli,pair,infos,out,install,root):
    frozen=product_inventory(root);binaries=binary_inventory(install)
    write(out/"frozen-product-hashes.json",frozen);write(out/"selected-native-binaries.json",binaries)
    result={}
    for label in ("positive","changed"):
        require(product_inventory(root)==frozen,"Product changed before/during trial; preserve evidence and stop")
        require(binary_inventory(install)==binaries,"Selected installed binaries changed")
        review=pair["cases"][label];case=Path(review["prepared_folder"]);folder=out/"runs"/label
        require(fingerprints(case)==review["prepared_hashes"],"Prepared model changed before native launch")
        launch=cli.native(label+"-native",["coupling","run",case,"--out",folder,"--install",install,"--timeout","60","--progress"],folder)
        result[label]=verify_outputs(folder,infos[label]["spec"],review,infos[label]["start"],launch['independent_root_handle'])
        result[label]["public_launch"]=launch
        cli.command(label+"-status",["run","status",folder])
        write(out/"native-progress.json",result)
        require(fingerprints(case)==review["prepared_hashes"],"Native execution modified original prepared input case")
    require(product_inventory(root)==frozen,"Product changed during trial; don't attribute results to frozen version")
    causal=causal_comparison(result["positive"],result["changed"])
    return {"runs":result,"causal_comparison":causal,
            "live_exchange_causal_hydraulics_gate":{"state":"passed","transactions_per_case":10,"causal_comparison":causal,"hydraulic_checkpoints":{label:run['hydraulic_checkpoint_gate']['state'] for label,run in result.items()}},
            "saved_actuator_restorability_gate":{"state":"not_established","cases":{label:run['saved_actuator_restorability_gate'] for label,run in result.items()},"reason":"Live control and final hydraulics are separate from saved-actuator/restored-state proof; no restore executed."}}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--positive-spec",type=Path)
    p.add_argument("--changed-spec",type=Path)
    p.add_argument("--replay-evidence",type=Path,help="Offline read-only audit of retained trial into new --out; never acceptance or native launch")
    p.add_argument("--out",type=Path,required=True,help="New independent evidence/case/run root")
    p.add_argument("--install",type=Path)
    p.add_argument("--native",action="store_true",help="Actually execute the two public coupling runs; requires explicit coordinator lease")
    p.add_argument("--native-slot",type=int,help="Records the currently assigned exclusive slot; does not acquire one")
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[3])
    args=p.parse_args(argv)
    if args.replay_evidence:
        if args.native or args.native_slot or args.positive_spec or args.changed_spec or args.install:p.error("Offline replay accepts only retained evidence and new output, never native or authoring arguments")
        report=audit_recorded(args.replay_evidence,args.out)
        print(json.dumps({k:report[k] for k in ('state','native_performed','historical_files_unchanged','acceptance')},indent=2))
        return 0
    if not (args.positive_spec and args.changed_spec and args.install):p.error("Preparation/native pair requires --positive-spec, --changed-spec and --install")
    if args.native and (not args.native_slot or args.native_slot<1):p.error("Native replay requires an explicitly assigned --native-slot")
    if args.native_slot and not args.native:p.error("A slot record does not by itself authorize/enable --native")
    root=args.root.resolve(strict=True);out=args.out.resolve()
    infos={"positive":source_inventory(args.positive_spec),"changed":source_inventory(args.changed_spec)}
    for info in infos.values():
        if out.is_relative_to(info["root"]):p.error("Fresh verification output must be outside authored source inputs")
    if out.is_relative_to(args.install.resolve()):p.error("Output must be outside the installation")
    out.mkdir(parents=True,exist_ok=False)
    write(out/"predeclared-oracle.json",DECLARATION)
    cli=PublicCLI(out)
    result={"state":"failed","native_performed":False,"native_slot":args.native_slot if args.native else None,"scientific_validation":"not_performed"}
    try:
        result["pair"]=prepare_pair(cli,infos["positive"],infos["changed"],out)
        native_plan={label:cli.argv(["coupling","run",out/"cases"/label,"--out",out/"runs"/label,"--install",args.install.resolve(),"--timeout","60","--progress"]) for label in infos}
        write(out/"native-command-plan.json",{"state":"predeclared_not_executed" if not args.native else "authorized_explicit_native_flag","argv":native_plan,"slot":args.native_slot})
        result["selected_binaries"]=binary_inventory(args.install.resolve(strict=True))
        if args.native:
            result["native_performed"]=True
            result["native"]=run_pair(cli,result["pair"],infos,out,args.install.resolve(strict=True),root)
            result["state"]="partial"
            result["acceptance"]="live_exchange_causal_hydraulics_passed; saved_actuator_restorability_not_established"
        else:result["state"]="prepared_for_assigned_native_slot"
    except Exception as exc:
        result.update(state="failed",failure={"type":type(exc).__name__,"message":str(exc)})
    finally:
        result["authored_sources_unchanged"]=all(source_inventory(info["path"])["files"]==info["files"] for info in infos.values())
        require(result["authored_sources_unchanged"],"Verifier altered authored source inputs")
        write(out/"verification.json",result)
    print(json.dumps({"state":result["state"],"native_performed":result["native_performed"],"evidence":str(out),"failure":result.get("failure")},indent=2))
    return 4 if result["state"]=="failed" else 0


if __name__=="__main__":
    raise SystemExit(main())
