"""Generate deterministic large CLI inputs, then time independent Windows workers (no engine)."""
import argparse
from collections import defaultdict
import ctypes as ct
from ctypes import wintypes
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
from statistics import median
import subprocess
import sys
from time import perf_counter_ns, process_time_ns

MODULE = "research.workflows.verification.benchmark_scale"
PHASES = ("mdu", "outputs", "logs")
KEYS, STDOUT_LINES, DIA_LINES = 5000, 320_000, 240_000


def digest(path):
    with path.open("rb") as stream:
        from hashlib import file_digest
        return file_digest(stream, "sha256").hexdigest()


def fingerprint(folder):
    return {p.relative_to(folder).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(folder.rglob("*")) if p.is_file() and p != folder / "fixture.json"}


def prepare(folder, prepared):
    import netCDF4 as nc
    import numpy as np
    folder.mkdir(parents=True, exist_ok=False)
    inputs = folder / "inputs"
    shutil.copytree(prepared, inputs)
    with (inputs / "f34.mdu").open("ab") as mdu:
        mdu.write(b"\r\n[Bench]\r\n")
        for i in range(KEYS):
            mdu.write((f"Scalar{i:05d} = {i}.125 # " + "preserved metadata " * 12 + "\r\n").encode())
    model = folder / "run/model"
    model.mkdir(parents=True)
    shutil.copyfile(prepared / "f34.mdu", model / "f34.mdu")
    output = model / "output"
    output.mkdir()
    for name, ticks, width in (("his", range(0, 601, 60), 65536), ("map", range(0, 601, 60), 2500000),
                               ("19900805_000000_rst", [0], 2500000), ("19900805_001000_rst", [600], 2500000)):
        with nc.Dataset(output / f"f34_{name}.nc", "w", format="NETCDF3_64BIT_OFFSET") as ds:
            ds.createDimension("time", len(ticks))
            ds.createDimension("element", width)
            t = ds.createVariable("time", "f8", ("time",))
            t.standard_name, t.units = "time", "seconds since 1990-08-05 00:00:00 +00:00"
            t[:] = ticks
            values = ds.createVariable("level", "f4", ("time", "element"), fill_value=False)
            row = np.arange(width, dtype="f4")
            for i in range(len(ticks)):
                values[i, :] = row + i
    logs = folder / "failed"
    (logs / "model").mkdir(parents=True)
    for path, count in ((logs / "stdout.log", STDOUT_LINES), (logs / "model/f34.dia", DIA_LINES)):
        with path.open("wb") as f:
            f.write(b"* 1.2.184.Unknown\nModel initialization was successful\nMPI : no.\nOpenMP : yes. #threads max : 1\n")
            for i in range(count):
                line = f"** INFO   : step {i:08d} elapsed simulation time {i/10:.1f} s; writing computational diagnostics\r\n"
                f.write(line.encode())
                if i % 8192 == 0:
                    f.write(b"** WARNING : projection unresolved\r\n")
            f.write(b"before one\nbefore two\n** ERROR : failed to open benchmark mesh\nafter one\nafter two\n")
    (logs / "stderr.log").write_bytes(b"projection diagnostic\r\n"*65)
    info = fingerprint(folder)
    (folder / "fixture.json").write_text(json.dumps(info, indent=2), encoding="utf-8")


class Memory(ct.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ct.c_size_t) for name in ("peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged",
                                        "nonpaged", "pagefile", "peak_pagefile")]


def memory():
    # OS-maintained high-water mark includes transient native/HDF5 allocations between samples.
    dll = ct.WinDLL("kernel32", use_last_error=True)
    query = dll.K32GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ct.POINTER(Memory), wintypes.DWORD]
    query.restype = wintypes.BOOL
    m = Memory(cb=ct.sizeof(Memory))
    if not query(wintypes.HANDLE(-1), ct.byref(m), m.cb):
        raise ct.WinError(ct.get_last_error())
    return m


def signature(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def worker(folder, phase, source):
    from dfm_cli import __version__, model, runs
    assert Path(model.__file__).resolve().parent == (source / "dfm_cli").resolve()
    files = json.loads((folder / "fixture.json").read_text(encoding="utf-8"))
    clock = {"start": "1990-08-05T00:00:00", "stop": "1990-08-05T00:10:00"}
    run = folder / "run"
    mdu = run / "model/f34.mdu"
    record = {"staged_mdu": str(mdu), "inputs": [{"relative_path":"f34.mdu"}],
              "profile": {"clock": clock}, "validation":{"engine_initialization":"attempted"}}
    old = not hasattr(runs, "collect_outputs")
    if phase == "outputs":
        runs.reader()  # Exclude dependency import time, include resident library footprint.
    initial = memory()
    start, cpu = perf_counter_ns(), process_time_ns()
    if phase == "mdu":
        result = model.validate(folder / "inputs/f34.mdu")
    elif phase == "outputs":
        if old:
            result = runs.verify_outputs(mdu, clock)
            runs.collect_artifacts(run, record)
        else:
            result = runs.collect_outputs(run, record, verify=True)
    else:
        native = runs.collect_diagnostics(folder / "failed", record)
        if old:  # In 0.2 a nonzero code triggers another scan while native stdout is still referenced.
            runs.collect_diagnostics(folder / "failed", record)
    wall_ms, cpu_ms = (perf_counter_ns()-start)/1e6, (process_time_ns()-cpu)/1e6
    peak = memory().peak_ws
    if phase == "mdu":
        assert not result["issues"] and sum(x["setting"].startswith("bench/") for x in result["settings"]) == KEYS
        assert result["sha256"] == files["inputs/f34.mdu"]["sha256"]
        common = contract = result
    elif phase == "outputs":
        assert result["state"] == "passed" and all(x["samples"] == 11 for x in result["axes"].values())
        assert [x["requested_final_time_matches"] for x in result["restart_axes"]] == [False, True]
        assert len(record["outputs"]) == 4
        assert all(x["sha256"] == files["run/"+Path(x["path"]).as_posix()]["sha256"] for x in record["outputs"])
        common = contract = [result["axes"], result["restart_axes"], record["outputs"], record["output_snapshots"]]
    else:
        d = record["diagnostics"]
        primary = d["primary_error"]
        assert primary["context"] == ["before one","before two","** ERROR : failed to open benchmark mesh","after one","after two"]
        common = [primary, record["runtime_versions"], record["validation"]]
        contract = None if old else [d, common, {str(p): h for p,h in native.items()}]
        if not old:
            assert native[folder/"failed/model/f34.dia"] == files["failed/model/f34.dia"]["sha256"]
            assert d["omitted"]["stderr_lines"] == 33 and len(d["error_lines"]) == 2
    print(json.dumps({"version":__version__, "phase":phase, "ms":wall_ms, "cpu_ms":cpu_ms,
                      "start_ws":initial.ws,"peak_ws":peak,"start_peak_ws":initial.peak_ws,
                      "common":signature(common),"contract":signature(contract) if contract is not None else None}))


def measure(args):
    folder = args.folder.resolve(strict=True)
    files = json.loads((folder/"fixture.json").read_text(encoding="utf-8"))
    if files != fingerprint(folder):
        raise ValueError("fixture changed")
    sources = {label: Path(path).resolve(strict=True) for label,path in (v.split("=",1) for v in args.source)}
    rows = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        raise FileExistsError(args.out)
    for i in range(args.samples):
        labels = list(sources)
        for phase in PHASES:
            for label in labels[i%len(labels):]+labels[:i%len(labels)]:
                source = sources[label]
                proc = subprocess.run([sys.executable,"-m",MODULE,"worker",str(folder),phase,str(source)],
                                      env=os.environ | {"PYTHONPATH":str(source)},capture_output=True,timeout=180,check=False)
                if proc.returncode:
                    raise RuntimeError(proc.stderr.decode(errors="replace"))
                row = json.loads(proc.stdout) | {"label":label,"trial":i+1}
                rows.append(row)
                print(f"{label} {phase}: {row['ms']:.0f} ms, peak WS {row['peak_ws']/2**20:.1f} MiB", flush=True)
    assert files == fingerprint(folder)
    groups = defaultdict(list)
    for row in rows:
        groups[row["label"],row["phase"]].append(row)
    for phase in PHASES:
        selected = [r for r in rows if r["phase"] == phase]
        assert len({r["common"] for r in selected}) == 1
        assert len({r["contract"] for r in selected if r["contract"]}) <= 1
    report = {"python":sys.version,"platform":platform.platform(),"processor":platform.processor(),
              "method":"isolated fresh process per phase/sample, warm file cache, execution excludes startup, fixture creation and oracle; absolute OS peak working set",
              "fixture":files,"source_sha256":{k:{p.name:digest(p) for p in sorted((v/"dfm_cli").glob("*.py"))} for k,v in sources.items()},
              "samples":rows,"medians":{k:{phase:{metric:median(r[metric] for r in groups[k,phase])
                                     for metric in ("ms","peak_ws","start_ws","cpu_ms")} for phase in PHASES} for k in sources}}
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(report,f,indent=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    subs = ap.add_subparsers(dest="action", required=True)
    p = subs.add_parser("prepare")
    p.add_argument("folder",type=Path); p.add_argument("prepared",type=Path)
    p = subs.add_parser("worker")
    p.add_argument("folder",type=Path); p.add_argument("phase",choices=PHASES); p.add_argument("source",type=Path)
    p = subs.add_parser("measure")
    p.add_argument("folder",type=Path); p.add_argument("--source",action="append",required=True,metavar="LABEL=PACKAGE_PARENT")
    p.add_argument("--samples", type=int,default=5,choices=range(1,31)); p.add_argument("--out",type=Path,required=True)
    args = ap.parse_args()
    if args.action == "prepare":
        prepare(args.folder,args.prepared)
    elif args.action == "worker":
        worker(args.folder,args.phase,args.source)
    else:
        measure(args)


if __name__ == "__main__":
    main()
