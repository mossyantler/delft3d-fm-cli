"""Independent, read-only E015 source/clock/reference oracle. No product imports.

Pinned 03 is a single FM component with in-kernel processes, NOT an offline WAQ
postprocessor. 07 is standalone Waves. 08 groups FM/Waves without scalar couplers.
10 has actual FM/RTC scalar couplers plus a separate Waves update group. No RR
fixture exists in this receipt; no RR execution support is inferred from RTC.
All XML/INI checks are static, not XSD, initialize/update or numerical validation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import xml.etree.ElementTree as ET

REVISION = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
CASES = ("03_dflowfm_dwaq_sequential", "07_dwaves", "08_dflowfm_sequential_dwaves", "10_dflowfm_sequential_drtc_dwaves")
NS = {"d": "http://schemas.deltares.nl/dimr"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(root, base, value, *, directory=False, exists=True):
    require(isinstance(value, str) and bool(value.strip()), "Empty referenced path")
    win = PureWindowsPath(value)
    require(not (win.drive or win.root or Path(value).is_absolute()), "Absolute/drive-relative reference is outside the fixture")
    target = (Path(base) / value.replace("\\", "/")).resolve()
    require(target.is_relative_to(Path(root).resolve()), "Reference escapes the fixture root")
    if exists:
        require(target.is_dir() if directory else target.is_file(), f"Missing referenced {'directory' if directory else 'file'}: {target}")
    return target


def xml(path):
    raw = Path(path).read_bytes()
    require(len(raw) <= 2 * 1024 * 1024 and b"<!doctype" not in raw.lower(), "Oversized XML or unsupported document type")
    return ET.fromstring(raw)


def ini(path):
    """Preserve repeated sections/keys; a requested scalar must be unambiguous."""
    blocks = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        text = raw.split("#", 1)[0].strip()
        if not text or text.startswith(";"):
            continue
        if text.startswith("[") and text.endswith("]"):
            blocks.append({"section": text[1:-1].strip().casefold(), "fields": []})
        elif "=" in text and blocks:
            key, value = text.split("=", 1)
            blocks[-1]["fields"].append((key.strip().casefold(), value.strip()))
    return blocks


def scalar(blocks, section, key, default=None):
    values = [v for b in blocks if b["section"] == section.casefold() for k, v in b["fields"] if k == key.casefold()]
    if not values and default is not None:
        return default
    require(len(values) == 1, f"Missing/duplicate scalar [{section}] {key}")
    return values[0]


def finite(value, *, positive=False):
    number = float(value)
    require(math.isfinite(number) and (not positive or number > 0), "Nonfinite/invalid clock scalar")
    return number


def fm_clock(blocks):
    origin = datetime.strptime(scalar(blocks, "time", "refdate"), "%Y%m%d")
    unit = scalar(blocks, "time", "tunit").upper()
    require(unit in {"S", "M", "H", "D"}, "Unknown FM relative time unit")
    factor = {"S": 1, "M": 60, "H": 3600, "D": 86400}[unit]
    zone = finite(scalar(blocks, "time", "tzone"))
    dates = []
    overridden = []
    for absolute, relative_name in (("startdatetime", "tstart"), ("stopdatetime", "tstop")):
        value = scalar(blocks, "time", absolute, "")
        overridden.append(bool(value))
        date = datetime.strptime(value, "%Y%m%d%H%M%S") if value else origin + timedelta(seconds=factor * finite(scalar(blocks, "time", relative_name)))
        dates.append(date - timedelta(hours=zone))
    require(dates[1] > dates[0], "FM clock interval is empty/reversed")
    return {"reference_date": origin.date().isoformat(), "start": dates[0].isoformat(), "stop": dates[1].isoformat(),
            "duration_seconds": (dates[1] - dates[0]).total_seconds(), "relative_unit": unit,
            "absolute_overrides": overridden, "dt_user_seconds": finite(scalar(blocks, "time", "dtuser"), positive=True), "tzone_hours": zone}


def _text(node, name):
    value = node.findtext("d:" + name, namespaces=NS)
    require(value is not None and bool(value.strip()), "Missing DIMR " + name)
    return value.strip()


def inspect_config(config, *, fixture_root=None):
    config = Path(config).resolve()
    root = Path(fixture_root).resolve() if fixture_root is not None else config.parent
    require(config.is_relative_to(root), "Configuration escapes root")
    doc = xml(config)
    require(doc.tag == "{" + NS["d"] + "}dimrConfig", "Expected DIMR namespace/root")
    components, clocks, dependencies = {}, {}, []
    for component in doc.findall("d:component", NS):
        name = component.get("name")
        require(name and name not in components, "Duplicate/empty component identity")
        library = _text(component, "library")
        work = relative(root, config.parent, _text(component, "workingDir"), directory=True)
        input_name = _text(component, "inputFile")
        is_rtc = library.casefold() == "fbctools_bmi"
        target = relative(root, work, input_name, directory=is_rtc)
        components[name] = {"library": library, "working_directory": str(work), "input": str(target),
                            "process": component.findtext("d:process", namespaces=NS)}
        if library.casefold() == "dflowfm":
            settings = ini(target)
            clocks[name] = fm_clock(settings)
            substance = scalar(settings, "processes", "substancefile", "")
            if substance:
                path = relative(root, work, substance)
                processes = {"substance_file": str(path), "sha256": fingerprint(path),
                             "dt_processes_seconds": finite(scalar(settings, "processes", "dtprocesses"), positive=True)}
                declared = re.findall(r"(?mi)^substance\s+'([^']+)'\s+(active|inactive).*?concentration-unit\s+'([^']+)'", path.read_text())
                require(declared, "No explicit substances/units in process input")
                processes["substances"] = [{"name": n, "active": state == "active", "unit": u} for n, state, u in declared]
                components[name]["in_kernel_processes"] = processes
            for setting in component.findall("d:setting", NS):
                if setting.get("key", "").casefold() == "processlibrary":
                    dependencies.append({"kind": "process_library", "declaration": setting.get("value"), "native_resolution": "required"})
        elif library.casefold() == "wave":
            settings = ini(target)
            date = datetime.strptime(scalar(settings, "general", "referencedate"), "%Y-%m-%d")
            points = [finite(v) * 60 for b in settings if b["section"] == "timepoint" for k, v in b["fields"] if k == "time"]
            require(all(b > a for a, b in zip(points, points[1:])), "Wave time points must increase")
            clocks[name] = {"reference_date": date.date().isoformat(), "timepoint_seconds": points,
                            "timepoint_unit_source": "D-Waves manual MDW TimePoint minutes; SWAN input parser",
                            "mode": scalar(settings, "general", "simmode"), "clock_source": "explicit_timepoints" if points else "DIMR_master_group"}
            for b in settings:
                if b["section"] == "domain":
                    for key in ("grid", "bedlevel"):
                        values = [v for k, v in b["fields"] if k == key]
                        require(len(values) == 1, "Wave domain grid/depth reference missing or duplicate")
                        relative(root, work, values[0])
        elif is_rtc:
            runtime = xml(relative(root, work, "xml_dir/rtcRuntimeConfig.xml"))
            user = runtime.find(".//{*}userDefined")
            require(user is not None, "RTC explicit runtime period missing")
            start, stop = [datetime.fromisoformat(user.find("{*}" + name).get("date") + "T" + user.find("{*}" + name).get("time"))
                           for name in ("startDate", "endDate")]
            step = user.find("{*}timeStep")
            require(step is not None and step.get("unit") == "second", "RTC time-step unit must be explicit seconds")
            dt = finite(step.get("multiplier"), positive=True) / finite(step.get("divider"), positive=True)
            require(stop > start, "RTC clock interval empty/reversed")
            clocks[name] = {"start": start.isoformat(), "stop": stop.isoformat(), "dt_seconds": dt}
            data = xml(relative(root, work, "xml_dir/rtcDataConfig.xml"))
            variables = {v.get("id"): v.findtext(".//{*}unit") for v in data.findall(".//{*}timeSeries")}
            require(all(k and u for k, u in variables.items()), "RTC exchange units must be explicit")
            components[name]["variables"] = variables
            dependencies.append({"kind": "BMI_library", "declaration": "FBCTools_BMI.dll", "native_resolution": "required"})
        else:
            raise ValueError("No pinned clock/output contract for library " + library)
    require(components, "No components declared")
    couplers = {}
    for coupler in doc.findall("d:coupler", NS):
        name = coupler.get("name")
        require(name and name not in couplers, "Duplicate/empty coupler identity")
        source, target = _text(coupler, "sourceComponent"), _text(coupler, "targetComponent")
        require(source in components and target in components, "Unknown coupler component reference")
        items = [(_text(item, "sourceName"), _text(item, "targetName")) for item in coupler.findall("d:item", NS)]
        require(items, "Empty scalar coupler")
        couplers[name] = {"source": source, "target": target, "items": items}
    control = doc.find("d:control", NS)
    require(control is not None, "Missing DIMR control")
    references = []
    for node in control.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in {"start", "coupler"}:
            name = node.get("name")
            require(name in (components if tag == "start" else couplers), "Unknown control reference " + str(name))
            references.append({"kind": tag, "name": name})
    groups = []
    for parallel in control.findall("d:parallel", NS):
        masters = parallel.findall("d:start", NS)
        require(len(masters) == 1, "Parallel control needs exactly one direct master start")
        master = masters[0].get("name")
        for group in parallel.findall("d:startGroup", NS):
            time = [finite(v) for v in _text(group, "time").split()]
            require(len(time) == 3 and time[1] > 0 and time[2] >= time[0], "Invalid group clock window/period")
            sequence = [(n.tag.rsplit("}", 1)[-1], n.get("name")) for n in group if not n.tag.endswith("}time")]
            groups.append({"master": master, "seconds": time, "sequence": sequence})
            for kind, name in sequence:
                if kind == "start" and components[name]["library"].casefold() == "fbctools_bmi":
                    rtc, flow = clocks[name], clocks[master]
                    require(rtc["dt_seconds"] == time[1], "RTC step differs from DIMR update period")
                    require((rtc["start"], rtc["stop"]) == (flow["start"], flow["stop"]), "RTC/FM absolute windows differ")
                if kind == "start" and components[name]["library"].casefold() == "wave":
                    require(clocks[name]["reference_date"] == clocks[master]["reference_date"], "FM/Waves reference dates differ")
    for name, c in couplers.items():
        for source_name, target_name in c["items"]:
            for component, item in ((c["source"], source_name), (c["target"], target_name)):
                comp = components[component]
                if comp["library"].casefold() == "fbctools_bmi":
                    require(comp["variables"].get(item) == "m", "RTC address/unit mismatch")
                elif comp["library"].casefold() == "dflowfm":
                    require(item in {"observations/Upstream/water_level", "weirs/weir01/crestlevel"}, "Unknown pinned FM scalar address")
    libs = [c["library"].casefold() for c in components.values()]
    if libs == ["dflowfm"] and any("in_kernel_processes" in c for c in components.values()):
        kind = "fm_in_kernel_processes"
    elif libs == ["wave"]:
        kind = "waves_standalone"
    elif set(libs) == {"dflowfm", "wave"} and not couplers:
        kind = "fm_waves_grouped_no_scalar_couplers"
    elif set(libs) == {"dflowfm", "wave", "fbctools_bmi"} and set(couplers) == {"flow2rtc", "rtc2flow"}:
        kind = "fm_rtc_waves_scalar_control"
        rtc_name = next(n for n, c in components.items() if c["library"].casefold() == "fbctools_bmi")
        sequence = next((g["sequence"] for g in groups if ("start", rtc_name) in g["sequence"]), None)
        require(sequence == [("coupler", "flow2rtc"), ("start", rtc_name), ("coupler", "rtc2flow")], "RTC update exchange ordering differs")
    else:
        raise ValueError("No approved independent pinned scenario classification")
    return {"classification": kind, "components": components, "clocks": clocks, "couplers": couplers,
            "control_references_in_order": references, "groups": groups, "dependencies": dependencies,
            "offline_waq_run": False, "native_performed": False, "xsd_validation": "not_performed"}


def inspect_receipt(source):
    source = Path(source).resolve()
    receipt = json.loads((source / "receipt.json").read_text())
    require(receipt.get("repo") == "Deltares/Delft3D" and receipt.get("revision") == REVISION, "Unexpected source receipt revision")
    hashes = receipt.get("sha256")
    require(isinstance(hashes, dict) and len(hashes) == 149, "Expected the complete 149-file pinned receipt")
    for name, expected in hashes.items():
        path = relative(source, source, name)
        require(fingerprint(path) == expected, "Pinned file fingerprint mismatch: " + name)
    cases = {name: inspect_config(source / "examples/dflowfm" / name / "dimr_config.xml") for name in CASES}
    return {"source_commit": REVISION, "receipt_files_verified": len(hashes), "cases": cases,
            "rr": {"state": "missing_pinned_fixture", "native_performed": False},
            "offline_waq": {"state": "separate_case_required", "reason": "03 invokes only FM with in-kernel processes"},
            "native_performed": False, "scientific_validation": "not_performed"}
