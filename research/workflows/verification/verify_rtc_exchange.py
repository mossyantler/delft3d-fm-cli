"""Independent E015 RTC/RR source/readiness and retained-data oracle.

Offline only: never loads a DLL, initializes a component or launches an engine.
Uses stdlib, netCDF4 and NumPy; no product parsers/comparators/controller imports.
Synthetic positive/control evidence exercises the oracle, never native acceptance.
Actual native adapters must bind raw observations to this explicit phase contract;
no best-fit lag, fabricated terminal sample, or repaired/masked result is accepted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import struct
import subprocess
import xml.etree.ElementTree as ET

ENGINE_PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
HELPER_PIN = "48993b1c85d6237ba55de08a4b4fbf8cb7965b80"
RTC_EXAMPLE = "examples/dflowfm/10_dflowfm_sequential_drtc_dwaves"
RR_EXAMPLE = "tests/data/input/e02/c11_korte-woerden-1d/dimr_model"
FBC_SOURCE = "src/engines_gpl/fbc/packages/FBCTools/src/rtcToolsBMI.cpp"
RR_SOURCE = "src/engines_gpl/rr/packages/rr_dll/src/rr_dll_bmi.f90"
TOLERANCES = {"exchange_atol": 1e-7, "exchange_rtol": 0., "volume_atol_m3": 1e-5, "volume_rtol": 1e-6,
              "time": "exact decoded timestamps; declared phases only", "masks": "none permitted in required scalar evidence"}
BMI_EXPORTS = {"initialize", "update", "finalize", "get_var", "set_var", "get_start_time", "get_end_time", "get_current_time", "get_time_step"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def xml(raw):
    require(len(raw) < 4 * 1024 * 1024 and b"<!doctype" not in raw.lower(), "Oversized XML/DTD refused")
    return ET.fromstring(raw)


def child(node, name):
    values = [item for item in node if local(item.tag) == name]
    require(len(values) == 1, "Missing/duplicate XML child: " + name)
    return values[0]


def text(node, name):
    value = child(node, name).text
    require(value is not None and bool(value.strip()), "Empty XML value: " + name)
    return value.strip()


def contained(root, base, value, exists=True):
    require(isinstance(value, str) and bool(value.strip()), "Empty path")
    win = PureWindowsPath(value)
    require(not win.drive and not win.root and not Path(value).is_absolute(), "Absolute/drive-relative input path refused")
    target = (Path(base) / value.replace("\\", "/")).resolve(strict=exists)
    require(target.is_relative_to(Path(root).resolve()), "Input path escapes case")
    return target


def git_blob(repository, revision, name):
    argv = ["git", "-C", str(repository), "show", revision + ":" + name]
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    require(result.returncode == 0, "Pinned Git object unavailable: " + name)
    return result.stdout


def config_contract(raw):
    root = xml(raw)
    require(local(root.tag) == "dimrConfig", "Not a DIMR configuration")
    components, couplers = {}, {}
    for node in root:
        tag = local(node.tag)
        if tag == "component":
            name = node.attrib["name"]
            require(name not in components, "Duplicate component")
            components[name] = {key: text(node, key) for key in ("library", "workingDir", "inputFile")}
        elif tag == "coupler":
            name = node.attrib["name"]
            require(name not in couplers, "Duplicate coupler")
            pairs = [(text(item, "sourceName"), text(item, "targetName")) for item in node if local(item.tag) == "item"]
            require(pairs and len(pairs) == len(set(pairs)), "Empty/duplicate scalar item")
            couplers[name] = {"source": text(node, "sourceComponent"), "target": text(node, "targetComponent"), "items": pairs}
    parallel = child(child(root, "control"), "parallel")
    masters = [node.attrib["name"] for node in parallel if local(node.tag) == "start"]
    require(len(masters) == 1 and masters[0] in components, "Expected one declared master")
    groups = []
    for node in parallel:
        if local(node.tag) != "startGroup":
            continue
        schedule = [float(item) for item in text(node, "time").split()]
        require(len(schedule) == 3 and all(map(math.isfinite, schedule)) and schedule[1] > 0 and schedule[2] > schedule[0], "Invalid group schedule")
        sequence = [(local(item.tag), item.attrib["name"]) for item in node if local(item.tag) in {"coupler", "start"}]
        for kind, name in sequence:
            require(name in (components if kind == "start" else couplers), "Unknown control reference")
        groups.append({"schedule_seconds": schedule, "sequence": sequence})
    for item in couplers.values():
        require(item["source"] in components and item["target"] in components, "Unknown scalar endpoint component")
    return {"components": components, "master": masters[0], "groups": groups, "couplers": couplers}


def lookup_contract(raw):
    root = xml(raw)
    tables = [item for item in root.iter() if local(item.tag) == "lookupTable"]
    require(len(tables) == 1, "Require one explicit lookup controller")
    table = tables[0]
    require(text(table, "interpolationOption") == "LINEAR" and text(table, "extrapolationOption") == "BLOCK", "Unsupported controller interpolation/extrapolation")
    knots = [(float(item.attrib["x"]), float(item.attrib["y"])) for item in child(table, "table")]
    require(len(knots) >= 2 and all(math.isfinite(x) and math.isfinite(y) for x, y in knots), "Invalid controller table")
    require(all(a[0] < b[0] for a, b in zip(knots, knots[1:])), "Controller x knots must strictly increase")
    return {"knots": knots, "input": text(child(table, "input"), "x"), "output": text(child(table, "output"), "y"),
            "input_reference": child(child(table, "input"), "x").get("ref"), "interpolation": "LINEAR", "extrapolation": "BLOCK"}


def lookup(knots, value):
    require(math.isfinite(value), "Controller input is not finite")
    require(len(knots) >= 2 and all(a[0] < b[0] for a, b in zip(knots, knots[1:])), "Invalid controller knots")
    if value <= knots[0][0]:
        return knots[0][1]
    if value >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= value <= x1:
            return y0 + (value - x0) * (y1 - y0) / (x1 - x0)
    raise AssertionError("Controller interval not found")


def series_contract(series, expected_seconds, unit):
    require(series["unit"] == unit, "Scalar physical units differ")
    times, values = series["seconds"], series["values"]
    require(times == list(expected_seconds), "Actual scalar times differ from predeclared schedule/phase")
    require(len(values) == len(times) and all(type(v) in (int, float) and math.isfinite(v) for v in values), "Missing/masked/nonfinite scalar values")
    return values


def near(left, right, message):
    require(len(left) == len(right), message + ": size")
    require(all(abs(a - b) <= TOLERANCES["exchange_atol"] for a, b in zip(left, right)), message)


def rtc_oracle(case):
    """Explicit transaction phases: source/set before RTC, output after one step.

    Raw adapters must establish these phases from actual logs/PI events. This is
    not permission to infer a lag from value agreement or label a PI export as
    a get/set event. Source ABI writes output before increment/execute.
    """
    start, step, stop = case["schedule_seconds"]
    require(type(step) is int and step > 0 and stop > start and (stop-start) % step == 0, "Unaligned RTC exchange clock")
    before = list(range(start, stop, step))
    after = [t + step for t in before]
    require(case["rtc_step_seconds"] == step, "RTC native update step differs from group invocation")
    source = series_contract(case["fm_observation"], before, "m")
    received = series_contract(case["rtc_received"], before, "m")
    computed = series_contract(case["rtc_output"], after, "m")
    applied = series_contract(case["fm_applied_crest"], before, "m")
    require(case["endpoints"] == {"fm_observation": "observations/Upstream/water_level", "rtc_received": "input_ObservationPoint01_water_level",
                                  "rtc_output": "output_weir_crest_level", "fm_applied_crest": "weirs/weir01/crestlevel"}, "RTC scalar endpoint identity mismatch")
    near(source, received, "FM source differs from actual RTC received input")
    expected = [lookup(case["knots"], value) for value in received]
    near(computed, expected, "RTC output differs from independent linear/block controller")
    near(computed, applied, "RTC output differs from actual FM applied crest")
    return {"state": "passed", "transactions": len(before), "expected_crest_m": expected,
            "phases": {"FM_source_set_and_apply": before, "RTC_output_after_update": after},
            "limits": "Scalar transfer/controller oracle only; final model axes, raw evidence phases and cleanup are separate"}


def rr_oracle(case):
    start, step, stop = case["schedule_seconds"]
    require(type(step) is int and step > 0 and stop > start and (stop-start) % step == 0, "Unaligned RR interval")
    before = list(range(start, stop, step))
    after = [t + step for t in before]
    require(case["rr_step_seconds"] == step, "RR internal step differs from exchange step")
    require(set(case["rr_outflow"]) == set(case["fm_lateral"]) and bool(case["rr_outflow"]), "RR/FM catchment/lateral IDs differ")
    expected_volume = 0.
    for catchment, source in case["rr_outflow"].items():
        require(source["address"] == f"catchments/{catchment}/water_discharge", "Wrong RR outflow address")
        target = case["fm_lateral"][catchment]
        require(target["address"] == f"laterals/{catchment}/water_discharge", "Wrong FM lateral address")
        q = series_contract(source, after, "m3 s-1")
        received = series_contract(target, before, "m3 s-1")
        near(q, received, "RR source differs from FM lateral value/sign")
        expected_volume += sum(q) * step
    volume = case["fm_integrated_lateral"]
    require(volume["unit"] == "m3" and volume["start_seconds"] == start and volume["stop_seconds"] == stop, "FM volume unit/window differs")
    require(math.isfinite(volume["value"]) and abs(volume["value"] - expected_volume) <= TOLERANCES["volume_atol_m3"] + abs(expected_volume) * TOLERANCES["volume_rtol"], "Signed RR volume does not match actual FM integrated lateral")
    return {"state": "passed", "catchments": sorted(case["rr_outflow"]), "expected_signed_volume_m3": expected_volume,
            "limits": "RR output-to-FM lateral transfer only; does not predict runoff or invent a reverse coupler"}


def positive_control(positive, control, kind):
    oracle = rtc_oracle if kind == "rtc" else rr_oracle
    a, b = oracle(positive), oracle(control)
    require(positive["schedule_seconds"] == control["schedule_seconds"], "Positive/control clocks differ")
    if kind == "rtc":
        require(positive["knots"] != control["knots"], "Controller control does not change the rule")
        require(a["expected_crest_m"] != b["expected_crest_m"], "Positive/control is not discriminating")
    else:
        require(a["catchments"] == b["catchments"], "Positive/control RR IDs differ")
        require(abs(a["expected_signed_volume_m3"]-b["expected_signed_volume_m3"]) > TOLERANCES["volume_atol_m3"], "Positive/control RR volumes are equal")
    return {"state": "passed", "positive": a, "control": b, "native_acceptance": "not_established_by_synthetic_or_normalized_values",
            "control_scope":"Each run uses its own measured input; hydraulic feedback may change FM observations across different control rules"}


def read_character_ids(ids):
    """Allow masked fixed-width suffix padding only; never fill identity bytes."""
    import numpy as np
    ids.set_auto_chartostring(False)
    raw=np.ma.asarray(ids[:]);mask=np.ma.getmaskarray(raw)
    if raw.dtype.kind=="S" and raw.ndim==2 and raw.dtype.itemsize==1:
        labels=[]
        for row,missing in zip(raw.data,mask):
            octets=row.tobytes();label=octets.rstrip(b"\x00 ")
            require(label and b"\x00" not in label,"Empty or embedded-NUL identity")
            require(not missing[:len(label)].any(),"Masked interior identity bytes")
            # A masked non-padding character is never recoverable as an ID.
            require(all(bytes(c) in {b"",b"\x00",b" "} for c,m in zip(row,missing) if m),"Masked non-padding identity bytes")
            labels.append(label.decode(getattr(ids,"_Encoding","utf-8")))
        return labels
    require(not mask.any(),"Masked identities")
    labels=[str(s).strip().strip("\x00") for s in raw]
    require(all(labels),"Empty identity")
    return labels


def read_nc_scalar(path, variable, identifier=None):
    """Read raw CF scalar per exact ID; never average/select the first station."""
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        t = ds["time"]
        tv = np.ma.asarray(t[:])
        require(tv.ndim == 1 and tv.size > 0 and not np.ma.getmaskarray(tv).any() and np.isfinite(tv.data).all() and np.all(np.diff(tv.data)>0), "Invalid actual CF time axis")
        var = ds[variable]
        require(var.dimensions and var.dimensions[0] == t.dimensions[0], "Scalar is not located on the decoded time axis")
        a = np.ma.asarray(var[:])
        if identifier is not None:
            id_var, wanted = identifier
            ids = ds[id_var]
            labels = read_character_ids(ids)
            matches = [i for i, value in enumerate(labels) if value == wanted]
            require(len(matches) == 1 and a.ndim == 2 and var.dimensions[1] == ids.dimensions[0], "Scalar ID missing/ambiguous or wrong location")
            a = a[:, matches[0]]
        require(a.ndim == 1 and a.shape == tv.shape and not np.ma.getmaskarray(a).any() and np.isfinite(a.data).all(), "Required scalar is masked/nonfinite or not scalar per time")
        dates = [value.isoformat() for value in nc.num2date(tv, t.units, calendar=getattr(t, "calendar", "standard"))]
        return {"path": str(path), "sha256": sha(path), "unit": var.units, "iso": dates, "values": a.data.astype(float).tolist(),
                "calendar": getattr(t,"calendar","standard"), "cf_units": t.units}


def read_pi_scalar(path, location, parameter, unit):
    root = xml(Path(path).read_bytes())
    zone = float(text(root, "timeZone"))
    require(math.isfinite(zone) and abs(zone) <= 14, "Invalid explicit PI time zone")
    found = []
    for node in root:
        if local(node.tag) != "series":
            continue
        h = child(node, "header")
        if text(h, "locationId") == location and text(h, "parameterId") == parameter:
            found.append((node, h))
    require(len(found) == 1, "PI series ID missing/ambiguous")
    node, header = found[0]
    require(text(header,"units") == unit, "PI physical units differ")
    missing = float(text(header,"missVal"))
    dates, values = [], []
    for event in node:
        if local(event.tag) != "event":
            continue
        date = datetime.fromisoformat(event.attrib["date"] + "T" + event.attrib["time"])
        require(date.tzinfo is None, "PI event timezone contradicts root timeZone")
        dates.append((date-timedelta(hours=zone)).isoformat())
        value = float(event.attrib["value"])
        require(math.isfinite(value) and value != missing, "PI event missing/nonfinite")
        values.append(value)
    require(dates and all(a < b for a,b in zip(dates,dates[1:])), "PI time axis empty/not increasing")
    return {"path":str(path),"sha256":sha(path),"unit":unit,"iso":dates,"values":values,"timeZone_hours":zone}


def lifecycle(record, stop, components):
    """No process lookup failure/PID disappearance substitutes for handle proof."""
    require(record["state"] == "completed" and record["returncode"] == 0, "Activity did not complete normally")
    for name in components:
        value = record["components"][name]
        require(value["final_model_seconds"] == stop and value["finalized"] is True, "Component final clock/finalization not established")
    own = record["ownership"]
    require(own["assigned_before_resume"] is True and own["job_empty"] is True, "Exact private Job completion not established")
    require(own["member_exit_confirmations"] and all(value is True for value in own["member_exit_confirmations"].values()), "Retained member handles did not confirm exit")
    return {"state":"passed","scope":"Explicit final clocks/finalize records and exact owned Job/member-handle evidence"}


def pe_exports(path):
    """Static PE export reader. Does not load libraries or claim ABI usability."""
    data = Path(path).read_bytes()
    require(data[:2] == b"MZ", "Not a PE image")
    pe = struct.unpack_from("<I", data, 0x3c)[0]
    require(data[pe:pe+4] == b"PE\0\0", "Invalid PE signature")
    machine, count = struct.unpack_from("<HH", data, pe+4)
    optional_size = struct.unpack_from("<H", data, pe+20)[0]
    optional = pe+24
    magic = struct.unpack_from("<H",data,optional)[0]
    require(magic in (0x10b,0x20b), "Unknown PE optional header")
    export_rva, size = struct.unpack_from("<II",data,optional+(112 if magic==0x20b else 96))
    sections=[]
    for index in range(count):
        offset=optional+optional_size+40*index
        virtual_size,rva,raw_size,raw=struct.unpack_from("<IIII",data,offset+8)
        sections.append((rva,max(virtual_size,raw_size),raw,raw_size))
    def locate(address):
        for rva,length,raw,raw_size in sections:
            if rva<=address<rva+length:
                require(address-rva<raw_size,"PE RVA has no retained bytes")
                return raw+address-rva
        raise AssertionError("PE RVA not in an image section")
    names=[]
    if export_rva and size:
        table=locate(export_rva)
        number=struct.unpack_from("<I",data,table+24)[0]
        addresses=struct.unpack_from("<I",data,table+32)[0]
        require(number<100000,"PE export bound exceeded")
        start=locate(addresses)
        for i in range(number):
            pos=locate(struct.unpack_from("<I",data,start+4*i)[0])
            end=data.find(b"\0",pos,pos+4096)
            require(end>=0,"Unterminated PE export")
            names.append(data[pos:end].decode("ascii"))
    return {"path":str(path),"sha256":sha(path),"machine":hex(machine),"exports":sorted(names),
            "required_BMI_exports_missing":sorted(BMI_EXPORTS-set(names)),"classification":"static PE export identities only; no DLL loaded/runtime ABI established"}


def synthetic_pairs():
    def series(values,unit="m",phase=0):
        return {"seconds":[t+phase for t in (0,60,120,180)],"values":list(values),"unit":unit}
    knots=[(0.,0.),(2.,0.),(10.,5.),(20.,5.)]
    source=[1.,2.,6.,10.]
    computed=[lookup(knots,v) for v in source]
    rtc={"schedule_seconds":[0,60,240],"rtc_step_seconds":60,"knots":knots,
         "endpoints":{"fm_observation":"observations/Upstream/water_level","rtc_received":"input_ObservationPoint01_water_level","rtc_output":"output_weir_crest_level","fm_applied_crest":"weirs/weir01/crestlevel"},
         "fm_observation":series(source),"rtc_received":series(source),"rtc_output":series(computed,phase=60),"fm_applied_crest":series(computed)}
    control=json.loads(json.dumps(rtc))
    control["knots"]=[(0.,0.),(20.,0.)]
    control["rtc_output"]["values"]=[0.]*4
    control["fm_applied_crest"]["values"]=[0.]*4
    rr={"schedule_seconds":[0,60,240],"rr_step_seconds":60,"rr_outflow":{"C1":series([0.,1.,2.,1.],"m3 s-1",60)|{"address":"catchments/C1/water_discharge"}},
        "fm_lateral":{"C1":series([0.,1.,2.,1.],"m3 s-1")|{"address":"laterals/C1/water_discharge"}},
        "fm_integrated_lateral":{"unit":"m3","start_seconds":0,"stop_seconds":240,"value":240.}}
    dry=json.loads(json.dumps(rr))
    dry["rr_outflow"]["C1"]["values"]=[0.]*4
    dry["fm_lateral"]["C1"]["values"]=[0.]*4
    dry["fm_integrated_lateral"]["value"]=0.
    return {"evidence_kind":"synthetic_portable_fixture","rtc":{"positive":rtc,"control":control},"rr":{"positive":rr,"control":dry}}


def fingerprints(root):
    root=Path(root)
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def ini_rows(raw):
    section,result="",[]
    for number,line in enumerate(raw.decode("utf-8-sig").splitlines(),1):
        line=line.split("#",1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section=line[1:-1].strip().casefold()
        elif "=" in line:
            key,value=line.split("=",1)
            result.append({"address":section+"/"+key.strip().casefold(),"value":value.strip(),"line":number})
    return result


def fm_input_clock(raw):
    rows=ini_rows(raw)
    def one(key):
        found=[r["value"] for r in rows if r["address"]==key]
        require(len(found)==1,"Missing/ambiguous explicit FM clock setting: "+key)
        return found[0]
    zone=float(one("time/tzone"))
    require(math.isfinite(zone),"Invalid explicit FM timezone")
    reference=datetime.strptime(one("time/refdate"),"%Y%m%d")
    unit=one("time/tunit").upper()
    require(unit in {"S","M","H","D"},"Unknown FM relative time unit")
    dates=[]
    for absolute,relative in (("startdatetime","tstart"),("stopdatetime","tstop")):
        candidates=[r["value"] for r in rows if r["address"]=="time/"+absolute]
        require(len(candidates)<=1,"Duplicate FM absolute clock setting")
        if candidates and candidates[0]:
            date=datetime.strptime(candidates[0],"%Y%m%d%H%M%S")
        else:
            value=float(one("time/"+relative))
            require(math.isfinite(value),"Nonfinite FM relative time")
            date=reference+timedelta(seconds=value*{"S":1,"M":60,"H":3600,"D":86400}[unit])
        dates.append(date-timedelta(hours=zone))
    require(dates[1]>dates[0],"FM model clock does not increase")
    intervals={}
    for address in ("time/dtuser","output/hisinterval","output/mapinterval"):
        v=float(one(address))
        require(math.isfinite(v) and v>0,"Invalid explicit FM step/output interval")
        intervals[address+"_seconds"]=v
    return {"reference":reference.isoformat(),"start_UTC":dates[0].isoformat(),"stop_UTC":dates[1].isoformat(),
            "duration_seconds":(dates[1]-dates[0]).total_seconds(),"tzone_hours":zone,"relative_time_unit":unit,
            "step_output_intervals_SI":intervals}


def rtc_paths(root, config):
    """Inspect actual prepared paths, not source defaults or CLI claims."""
    root, config=Path(root).resolve(),Path(config).resolve()
    contract=config_contract(config.read_bytes())
    result={"config":str(config),"config_sha256":sha(config),"contract":contract,"components":{}}
    for name, component in contract["components"].items():
        work=contained(root,config.parent,component["workingDir"])
        require(work.is_dir(),"Component workingDir missing")
        item={"working_path":str(work),"library":component["library"]}
        if component["library"]=="FBCTools_BMI":
            module=contained(root,work,component["inputFile"])
            settings=module/"settings.json"
            values=json.loads(settings.read_bytes())
            schema=contained(root,module,values["schemaDir"])
            directory=contained(root,module,values["xmlDir"])
            require(schema.is_dir() and directory.is_dir(),"RTC settings paths are not directories")
            runtime=xml((directory/"rtcRuntimeConfig.xml").read_bytes())
            period=next(n for n in runtime.iter() if local(n.tag)=="userDefined")
            def date(key):
                n=child(period,key)
                return datetime.fromisoformat(n.attrib["date"]+"T"+n.attrib["time"])
            step=child(period,"timeStep")
            require(step.attrib["unit"]=="second","RTC clock unit must be explicit seconds")
            seconds=float(step.get("multiplier","1"))/float(step.get("divider","1"))
            require(math.isfinite(seconds) and seconds>0 and date("endDate")>date("startDate"),"Invalid RTC period/step")
            data=xml((directory/"rtcDataConfig.xml").read_bytes())
            variables={}
            for section in data:
                for series in section:
                    if local(series.tag)=="timeSeries":
                        address=series.attrib["id"]
                        direction=local(section.tag)
                        unit=text(child(series,"OpenMIExchangeItem"),"unit")
                        if address in variables:
                            require(direction not in variables[address]["directions"] and unit==variables[address]["unit"],"Duplicate RTC data series role or contradictory units")
                            variables[address]["directions"].append(direction)
                        else:
                            variables[address]={"directions":[direction],"unit":unit}
            item.update(module=str(module),settings_sha256=sha(settings),schema_path=str(schema),xml_path=str(directory),
                        clock={"start":date("startDate").isoformat(),"stop":date("endDate").isoformat(),"step_seconds":seconds,"timezone":"undeclared in RTC runtime; must align to explicit case/FM timezone"},
                        lookup=lookup_contract((directory/"rtcToolsConfig.xml").read_bytes()),series=variables,
                        input_series_independently_exported=any("exportSeries" in v["directions"] and k.startswith("input_") for k,v in variables.items()))
        else:
            path=contained(root,work,component["inputFile"])
            require(path.is_file(),"Component inputFile missing")
            item.update(input_path=str(path),input_sha256=sha(path))
            if component["library"]=="dflowfm":
                item["clock"]=fm_input_clock(path.read_bytes())
            elif component["library"]=="wave":
                rows=ini_rows(path.read_bytes())
                item["clock"]={"reference_dates":[r["value"] for r in rows if r["address"]=="general/referencedate"],
                               "timepoints_minutes":[r["value"] for r in rows if r["address"].endswith("/timepoint")],
                               "native_start_stop":"not inferred from online MDW without explicit TimePoints; DIMR group and actual native clock required"}
        result["components"][name]=item
    return result


def fnm_inputs(raw, directory):
    """FNM input/output slots stay distinct; do not demand preexisting outputs."""
    result=[]
    for line in raw.decode("utf-8-sig").splitlines():
        match=re.match(r"\s*'([^']+)'\s*\*\s*(\d+)\.?(.*?)\s+([IO])\s*$",line)
        if not match:
            continue
        name,slot,description,direction=match.groups()
        if direction!="I":
            continue
        try:
            p=contained(directory,directory,name)
            state="empty" if p.stat().st_size==0 else "present_nonempty"
            result.append({"slot":int(slot),"name":name,"state":state,"sha256":sha(p),"bytes":p.stat().st_size})
        except (OSError,AssertionError) as exc:
            result.append({"slot":int(slot),"name":name,"state":"missing_or_unconfined","reason":str(exc)})
    require(result,"No authoritative FNM input slots parsed")
    return result


def source_preparation(root,out,install,prepared=None):
    repo=root/"research/upstream/Delft3D"
    helper=root/"research/upstream/HYDROLIB-core"
    lock=json.loads((root/"research/sources.lock.json").read_bytes())
    require(lock["repositories"]["Delft3D"]["commit"]==ENGINE_PIN and lock["repositories"]["HYDROLIB-core"]["commit"]==HELPER_PIN,"Source lock changed; independent contracts need review")
    (out/"pinned-rtc10").mkdir()
    argv=["git","-C",str(repo),"ls-tree","-r","--name-only",ENGINE_PIN,RTC_EXAMPLE]
    names=subprocess.check_output(argv,stdin=subprocess.DEVNULL,timeout=15).decode().splitlines()
    require(len(names)==39,"Pinned example10 file inventory changed")
    copies={}
    for name in names:
        relative=Path(name).relative_to(RTC_EXAMPLE)
        target=out/"pinned-rtc10"/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        raw=git_blob(repo,ENGINE_PIN,name)
        target.write_bytes(raw)
        copies[relative.as_posix()]={"sha256":sha(target),"bytes":len(raw)}
    write(out/"pinned-rtc10-file-hashes.json",copies)
    rtc=rtc_paths(out/"pinned-rtc10",out/"pinned-rtc10/dimr_config.xml")
    names=[r for r in ini_rows((out/"pinned-rtc10/fm/WaterLevel.bc").read_bytes()) if r["address"]=="forcing/name"]
    duplicates={name: [r["line"] for r in names if r["value"]==name] for name in {r["value"] for r in names} if sum(r["value"]==name for r in names)>1}
    rtc["forcing_duplicate_names"]=duplicates
    require(rtc["contract"]["groups"][0]["sequence"]==[("coupler","flow2rtc"),("start","myNameRTC"),("coupler","rtc2flow")],"Pinned RTC exchange order changed")
    require(rtc["contract"]["couplers"]["flow2rtc"]["items"]==[("observations/Upstream/water_level","input_ObservationPoint01_water_level")],"Pinned RTC input address changed")
    require(rtc["contract"]["couplers"]["rtc2flow"]["items"]==[("output_weir_crest_level","weirs/weir01/crestlevel")],"Pinned RTC output address changed")
    write(out/"official10-paths.json",rtc)
    source_records={}
    for key,path,needles in (
        ("rtc_bmi",FBC_SOURCE,["dt = runtime", "runtime->writeOutput", "step++;", "runtime->execute", "*current_time =", "target_step++", "setValue(0, target_step"]),
        ("rr_bmi",RR_SOURCE,["case('water_discharge')", "RSLMAP6_bnd_dp", "RSLMAP7_plv_dp", "case('water_level')", "BndPar(ibnd, 1)", "current_time =", "end_time =", "time_step ="])):
        raw=git_blob(repo,ENGINE_PIN,path)
        target=out/(key+Path(path).suffix)
        target.write_bytes(raw)
        lines=raw.decode().splitlines()
        source_records[key]={"commit":ENGINE_PIN,"path":path,"sha256":sha(target),
                             "lines":[{"line":number,"text":line} for number,line in enumerate(lines,1) if any(s in line for s in needles)]}
    rr_dir=helper/RR_EXAMPLE/"rr"
    rr_xml=git_blob(helper,HELPER_PIN,RR_EXAMPLE+"/dimr_config.xml")
    (out/"official-rr-dimr_config.xml").write_bytes(rr_xml)
    rr=config_contract(rr_xml)
    fnm=git_blob(helper,HELPER_PIN,RR_EXAMPLE+"/rr/Sobek_3b.fnm")
    (out/"official-Sobek_3b.fnm").write_bytes(fnm)
    fnm_work=rr_dir/"Sobek_3b.fnm"
    require(fnm_work.read_bytes().replace(b"\r\n",b"\n")==fnm,"Retained RR FNM differs from pinned blob")
    inputs=fnm_inputs(fnm,rr_dir)
    rr_bad=[item for item in inputs if item["state"]!="present_nonempty"]
    write(out/"rr-reference-audit.json",{"source_commit":HELPER_PIN,"contract":rr,"inputs":inputs,"unready_inputs":rr_bad,
                                          "direction":"72 RR outflow to FM lateral items; no reverse coupler in this official reference","runtime_readiness":"not_established"})
    write(out/"source-interfaces.json",source_records)
    binaries={}
    for name in ("FBCTools_BMI.dll","rr_dll.dll","dflowfm.dll","dimr.dll"):
        matches=list(Path(install).glob("plugins/DeltaShell.Dimr/kernels/*/lib/"+name))
        require(len(matches)==1,"Selected installation component binary missing/ambiguous: "+name)
        binaries[name]=pe_exports(matches[0])
    write(out/"installed-static-capabilities.json",binaries)
    prepared_report=None
    if prepared:
        p=Path(prepared).resolve(strict=True)
        before=fingerprints(p)
        prepared_report=rtc_paths(p,p/"dimr_config.xml")
        prepared_report["file_hashes"]=before
        prepared_report["source_file_diff"]={"added":sorted(set(before)-set(copies)),"removed":sorted(set(copies)-set(before)),
                                             "changed":sorted(name for name in set(before)&set(copies) if before[name]!=copies[name]["sha256"])}
        require(fingerprints(p)==before,"Prepared case changed during read-only audit")
        write(out/"prepared-paths-audit.json",prepared_report)
    pairs=synthetic_pairs()
    write(out/"synthetic-positive-control.json",pairs)
    portable={kind:positive_control(value["positive"],value["control"],kind) for kind,value in pairs.items() if kind in {"rtc","rr"}}
    write(out/"synthetic-oracle-results.json",portable)
    blockers={"rtc":["No native lease or initialize/update/finalize evidence", "Native raw series adapters and fixed transaction-phase receipt required",
                     "Original RTC data config exports control output only; independently retained received-input series required",
                     "Original third Waves component remains a separate observation/clock obligation", "Native positive/control and owned cleanup evidence pending",
                     "Original FM history600s/map21600s are too sparse for RTC60s exchange verification; common instrumentation required",
                     "Original WaterLevel.bc duplicates Boundary01_0001; resolve explicitly in prepared inputs, not inside oracle"],
              "rr":["No native lease", "Collected c11 FNM inputs include empty/missing authoritative model files", "Public fm_rr launcher remains gated pending actual RR clock/output adapter",
                    "RR output units, exact catchment/lateral identity, integration phase and receiver volume must be established from actual outputs", "Reference is one-way RR->FM; reverse water-level exchange requires its own authored case"]}
    write(out/"Faraday-exchange-contract.json",{
        "state":"independent_portable_contract_ready_native_adapter_pending","native_launch_authorized":False,
        "public_profiles_observed":{"rtc":"fm_rtc_waves includes Waves as a third component","rr":"fm_rr currently launch-disabled"},
        "required_RTC_channels":{"fm_observation":"raw FM Upstream/water_level, m, exact identity and CF dates",
                                 "rtc_received":"independent raw RTC input series; original config does not export it",
                                 "rtc_output":"raw PI or NetCDF output_weir_crest_level, m, exact header identity/timezone",
                                 "fm_applied_crest":"raw FM actual weir01 crest, not just requested command or coupler log"},
        "controller":"Independent LINEAR/BLOCK lookup against each run's own received signal; positive/control rule change only, other input hashes identical",
        "phase_gate":"Predeclare phases from BMI source and raw trace before native; never fit/shift/truncate/fabricate agreement. RTC PI writes before step increment/execute; star suffix changes the set target slot.",
        "RR_gate":"Complete authoritative RR model; exact catchment IDs, RR outflow vs FM received lateral, explicit m3/s and signed time-integrated m3. No invented reverse exchange.",
        "final_and_cleanup":"Actual FM CF final history/map/restart plus RTC/RR final model clock/finalize; exact Job and retained member-handle exit confirmation. Partial/forced/owner-lost outcomes never accepted.",
        "inputs":"Freeze prepared input and installation hashes; separate positive/control folders; source read-only; preserve failed attempts",
        "tolerances":TOLERANCES,"prepared_case_supplied":prepared is not None})
    for name,value in binaries.items():
        if value["required_BMI_exports_missing"]:
            blockers["rtc" if name=="FBCTools_BMI.dll" else "rr"].append(name+": missing static BMI exports "+str(value["required_BMI_exports_missing"]))
    return {"state":"portable_preparation_passed_native_pending","native_performed":False,"source_commits":{"engine":ENGINE_PIN,"helper":HELPER_PIN},
            "official10_files":len(copies),"rr_reference_exchange_items":sum(len(v["items"]) for v in rr["couplers"].values()),
            "rr_unready_input_count":len(rr_bad),"tolerances_declared_before_native":TOLERANCES,"portable_oracles":portable,
            "prepared_paths_audited":prepared_report is not None,"blockers":blockers,
            "scientific_validation":"not_performed","limits":"Portable/source/static PE checks are not native capability or numerical acceptance"}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--install",type=Path,required=True,help="Existing suite root; files inspected only")
    p.add_argument("--prepared",type=Path,help="Faraday's fresh prepared case root, audited read-only")
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[3])
    args=p.parse_args(argv)
    out=args.out.resolve()
    for source in (args.prepared,args.install):
        if source and out.is_relative_to(source.resolve()):
            p.error("Output must remain outside existing inputs/installation")
    out.mkdir(parents=True,exist_ok=False)
    result={"state":"failed","native_performed":False}
    try:
        result=source_preparation(args.root.resolve(strict=True),out,args.install.resolve(strict=True),args.prepared)
    except Exception as exc:
        result["failure"]={"type":type(exc).__name__,"message":str(exc)}
    write(out/"verification.json",result)
    print(json.dumps({"state":result["state"],"native_performed":False,"evidence":str(out),"failure":result.get("failure")},indent=2))
    return 4 if result["state"]=="failed" else 0


if __name__=="__main__":
    raise SystemExit(main())
