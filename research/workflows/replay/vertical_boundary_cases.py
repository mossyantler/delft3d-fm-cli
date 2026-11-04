"""B13 three-case replay: nonnative prepare, leased installed-public execute.

Prepare takes a native model graph and independently authored manual/oracle files;
the installed public CLI inspects/previews/applies only the copied public case.
Execute invokes ONLY the installed dfm entry point,
including its existing run owner. It never launches an engine or manages a Job.
See ``prepare --help`` and ``execute --help``. Numerical acceptance belongs to
research.workflows.verification.verify_vertical_boundary_cases, not this producer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
from types import ModuleType

CASES = ("baseline", "manual", "public")
REQUEST = dict(point="west_0001", quantity="salinitybnd", time="20",
               time_unit="seconds since 2001-01-01 00:00:00 +00:00",
               position="0.4", position_type="percBed", unit="ppt")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_bytes())


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def regular(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        need(not part.is_symlink() and not (part.lstat().st_file_attributes & 0x400
             if hasattr(part.lstat(), "st_file_attributes") else False), "Aliased path: "+str(part))
    need(path.is_file(), "Not a regular file: "+str(path))
    return path.resolve(strict=True)


def record(path):
    path = regular(path)
    st = path.stat()
    return dict(path=str(path), sha256=sha(path), bytes=st.st_size,
                device=st.st_dev, inode=st.st_ino, mtime_ns=st.st_mtime_ns)


def checked(item):
    need(record(item["path"]) == item, "File changed/replaced: "+item["path"])


def inventory(root):
    return {p.relative_to(root).as_posix(): record(p)
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def hashes(items):
    return {name: item["sha256"] for name, item in items.items()}


def fresh(path):
    path = Path(path).absolute()
    need(not path.exists(), "Output already exists: "+str(path))
    need(path.parent.is_dir() and not path.parent.is_symlink(), "Output parent must exist")
    path.mkdir()
    return path.resolve()


def prepare(a):
    # Pure graph reader; no product editor is used as the expected-value oracle.
    from dfm_cli.layers import inspect
    mdu = regular(a.baseline_mdu)
    control, oracle, manual_bc = map(regular, (a.manual_control, a.oracle, a.manual_bc))
    need(sha(control) == a.expect_manual_sha256.lower(), "Independent manual-control pin differs")
    need(sha(oracle) == a.expect_oracle_sha256.lower(), "Independent oracle pin differs")
    independent = load(control)
    graph = inspect(mdu)
    files = {item["relative_path"]: record(item["path"]) for item in graph["files"]}
    need(len(files) == 9 and mdu.name in files, "This replay requires the complete nine-native-input graph")
    need(all(independent["base_hashes"].get(k) == v["sha256"] for k, v in files.items()),
         "Actual native graph differs from independent baseline")
    bc_names = [name for name in files if name.lower().endswith(".bc")]
    need(len(bc_names) == 1, "Exactly one native BC required")
    bc, = bc_names
    module = ModuleType("_b13_independent_oracle")
    # Compile pinned bytes directly: importing must not write into V's tree.
    exec(compile(oracle.read_bytes(), str(oracle), "exec"), module.__dict__)
    before = Path(files[bc]["path"]).read_bytes()
    expected, cell = module.manual(before, value="22", **REQUEST)
    need(cell == independent["single_cell"], "Independent target metadata differs")
    need(manual_bc.read_bytes() == expected and sha(manual_bc) == independent["manual_hashes"][bc],
         "Independent manual bytes/oracle/hash disagree")
    need(cell["before_raw"] == "20" and cell["after_raw"] == "22", "Wrong single-cell change")
    need(all(independent["manual_hashes"].get(k) == v["sha256"] for k, v in files.items() if k != bc),
         "Manual declaration changes another native input")
    clock = graph["layers"]["clock"] if "clock" in graph["layers"] else graph["clock"]
    need(clock["duration_seconds"] == 20, "B13 clock must be exactly 20 seconds")
    identity = installed(a.dfm)
    need(identity["wheel"]["sha256"] == a.expect_wheel_sha256.lower(), "Installed wheel pin differs")
    need(not Path(a.out).absolute().is_relative_to(mdu.parent), "Preparation must be outside ordinary source inputs")
    out = fresh(a.out)
    (out/"independent").mkdir()
    for source, name in ((control, "manual-control.json"), (oracle, "vertical_oracle.py"), (manual_bc, "manual.bc")):
        shutil.copyfile(source, out/"independent"/name)
    copied = {}
    for case in CASES:
        root = out/"cases"/case
        root.mkdir(parents=True)
        for name, item in files.items():
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(expected if case == "manual" and name == bc else Path(item["path"]).read_bytes())
        copied[case] = inventory(root)
    plan = dict(version=1, node="B13-RUN-I", state="prepared_not_executed", prepared=str(out),
                producer=record(__file__), installed_cli=identity, sources=files, source_root=str(mdu.parent),
                source_directory=inventory(mdu.parent), mdu=mdu.name, bc=bc, cases=copied,
                independent={p.name: record(p) for p in (out/"independent").iterdir()},
                original_independent=[record(p) for p in (control, oracle, manual_bc)],
                request=REQUEST, boundary="west", value="22", cell=cell, requested_clock=clock,
                expected_public_hashes=hashes(copied["manual"]),
                native_input_count=9, excluded_from_engine_authority=sorted(set(inventory(mdu.parent))-set(files)),
                case_order=list(CASES), route="direct", profile="layers",
                limitations=["Only public nonnative schema/vertical inspection/edit commands during prepare",
                             "JSON spec/provenance sidecars are not copied or interpreted as engine inputs",
                             "A single endpoint/time/vertical-knot edit; no full-profile perturbation",
                             "No inferred response threshold or scientific accuracy claim"])
    commands = out/"commands"
    commands.mkdir()
    public_edit(Calls(regular(a.dfm), commands), out, plan)
    plan["cases"]["public"] = inventory(out/"cases/public")
    plan["state"] = "public_edit_prepared_not_native_executed"
    validate_cases(out, plan, edited=True)
    validate_sources(plan)
    save(out/"preparation.json", plan)
    return dict(prepared=str(out), preparation_sha256=sha(out/"preparation.json"),
                cases={case: str(out/"cases"/case) for case in CASES}, native_execution="not_performed")


def validate_sources(plan):
    checked(plan["producer"])
    for item in [*plan["source_directory"].values(), *plan["original_independent"], *plan["independent"].values()]:
        checked(item)


def validate_cases(root, plan, *, edited=False):
    for case in CASES:
        actual = inventory(root/"cases"/case)
        wanted = plan["expected_public_hashes"] if case == "public" and edited else hashes(plan["cases"][case])
        need(hashes(actual) == wanted, "Unexpected case bytes/files: "+case)
        if case != "public" or not edited:
            need(actual == plan["cases"][case], "Case input identity changed: "+case)
    if edited:
        raw = (root/"cases/public"/plan["bc"]).read_bytes()
        need(raw == (root/"cases/manual"/plan["bc"]).read_bytes(), "Public/manual BC differ")
        source = Path(plan["sources"][plan["bc"]]["path"]).read_bytes()
        cell = plan["cell"]
        need(raw == source[:cell["start"]]+b"22"+source[cell["end"]:], "Other BC rows/tokens changed")


def lease(a):
    need(a.native_slot_granted and a.native_slot_granted > 0 and a.lease_owner,
         "Execute requires an explicitly granted coordinator slot and owner")
    path = regular(a.dispatch)
    slot = load(path)["native_slot"]
    need(type(slot.get("sequence")) is int and slot["sequence"] == a.native_slot_granted
         and slot.get("owner") == a.lease_owner, "Coordinator lease owner/sequence mismatch")
    return dict(path=str(path), sha256=sha(path), owner=slot["owner"], sequence=slot["sequence"])


def installed(dfm):
    # Reuse the shared executor's FILE-ONLY wheel identity check, never its launcher.
    from research.workflows.replay.research_serial_cases import helpers, _installed_files
    helper, _ = helpers()
    return _installed_files(helper, dfm)


class Calls:
    def __init__(self, dfm, out):
        self.dfm, self.out, self.calls = str(dfm), out, []

    def call(self, label, argv, *, allow_failure=False):
        args = [self.dfm, *map(str, argv)]
        prefix = self.out/f"{len(self.calls):02d}-{label}"
        item = dict(argv=args, cwd=str(self.out), started_utc=datetime.now(timezone.utc).isoformat(),
                    stdout=str(prefix)+".stdout", stderr=str(prefix)+".stderr")
        self.calls.append(item)
        env = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        try:
            # No wrapper timeout/kill: public run owner enforces --timeout and cleanup.
            with open(item["stdout"], "wb") as stdout, open(item["stderr"], "wb") as stderr:
                done = subprocess.run(args, cwd=self.out, env=env, stdout=stdout, stderr=stderr, check=False)
            item["returncode"] = done.returncode
        except BaseException as exc:
            item["exception"] = type(exc).__name__+": "+str(exc)
            raise
        finally:
            item["finished_utc"] = datetime.now(timezone.utc).isoformat()
            save(self.out/"calls.json", self.calls)
        if allow_failure:
            try:
                payload = load(item["stdout"])
            except (ValueError, OSError):
                payload = None
            return dict(returncode=done.returncode, payload=payload)
        need(done.returncode == 0, "Public command failed; retain raw diagnostics: "+label)
        data = load(item["stdout"])
        need(data.get("ok") is True, "Public command did not report success: "+label)
        return data["result"]


def output_clocks(run, clock):
    import netCDF4
    result = {}
    root = run/"model"/"output"
    files = sorted(root.glob("*.nc"))
    need(len(files) == 4, "Expected history/map/two restart datasets; see retained outputs")
    need(sum(p.name.endswith("_his.nc") for p in files) == 1
         and sum(p.name.endswith("_map.nc") for p in files) == 1
         and sum(p.name.endswith("_rst.nc") for p in files) == 2, "Unexpected output roles")
    for path in files:
        with netCDF4.Dataset(path) as ds:
            time = ds.variables["time"]
            values = time[:]
            need(not bool(getattr(values, "mask", False).any()) if hasattr(getattr(values, "mask", None), "any") else True,
                 "Masked output clock")
            dates = netCDF4.num2date(values, time.units, getattr(time, "calendar", "standard"))
            seconds = [float(x) for x in netCDF4.date2num(dates, "seconds since "+clock["start"].replace("T", " "),
                                                         getattr(time, "calendar", "standard"))]
            expected = [0., 10., 20.] if path.name.endswith(("_his.nc", "_map.nc")) else ([0.] if "000000_rst" in path.name else [20.])
            need(seconds == expected, "Unexpected actual CF times: "+str(path))
            result[path.name] = dict(file=record(path), units=time.units,
                                     calendar=getattr(time, "calendar", "standard"), seconds=seconds,
                                     actual_final_seconds=max(seconds))
    return dict(netCDF4_version=netCDF4.__version__, datasets=result)


def public_edit(calls, root, plan):
    public = root/"cases/public"/plan["mdu"]
    selector = ["--boundary", plan["boundary"], "--point", REQUEST["point"], "--quantity", REQUEST["quantity"]]
    calls.call("schema", ["schema", "inspect"])
    calls.call("inspect", ["boundary", "vertical-inspect", public, *selector])
    edit = ["boundary", "vertical-set", public, *selector]
    for key in ("time", "time_unit", "position", "position_type", "unit"):
        edit += ["--"+key.replace("_", "-"), REQUEST[key]]
    edit += ["--value", plan["value"]]
    preview = calls.call("preview", edit)
    validate_cases(root, plan)
    token = preview.get("input_sha256")
    need(isinstance(token, str) and len(token) == 64, "Edit preview consent hash missing")
    calls.call("apply", [*edit, "--apply", "--expect-sha256", token])
    validate_cases(root, plan, edited=True)


def execute(a):
    grant = lease(a)  # Before directory creation or ANY public command.
    root = regular(Path(a.prepared)/"preparation.json").parent
    need(sha(root/"preparation.json") == a.expect_preparation_sha256.lower(), "Preparation pin differs")
    plan = load(root/"preparation.json")
    need(plan["node"] == "B13-RUN-I" and plan["prepared"] == str(root), "Wrong preparation binding")
    validate_sources(plan)
    validate_cases(root, plan, edited=True)
    identity = installed(a.dfm)
    need(identity["wheel"]["sha256"] == a.expect_wheel_sha256.lower(), "Installed wheel pin differs")
    need(identity == plan["installed_cli"], "Execute must use the exact installed public CLI prepared/pinned")
    need(1 <= a.timeout <= 300, "Bounded public native timeout required")
    out = fresh(a.out)
    calls = Calls(regular(a.dfm), out)
    receipt = dict(version=1, state="in_progress", lease=grant, installed_cli=identity,
                   preparation=record(root/"preparation.json"), runs=[], output_clocks={})
    save(out/"execution.json", receipt)
    try:
        validate_cases(root, plan, edited=True)
        for case in CASES:
            validate_sources(plan)
            validate_cases(root, plan, edited=True)
            need(installed(a.dfm) == identity, "Installed public CLI changed")
            receipt["lease"] = lease(a)
            run = out/("run-"+case)
            receipt["runs"].append(dict(case_id=case, path=str(run)))
            save(out/"runs.json", dict(version=1, runs=receipt["runs"]))
            start = calls.call(case+"-start", ["run", "start", root/"cases"/case/plan["mdu"], "--profile", "layers",
                                      "--route", "direct", "--install", a.install, "--timeout", a.timeout, "--out", run], allow_failure=True)
            status = calls.call(case+"-status", ["run", "status", run], allow_failure=True)
            receipt.setdefault("observations", {})[case] = dict(start=start, status=status,
                manifest_path=str(run/"manifest.json"), output_path=str(run/"model/output"),
                output_files=inventory(run/"model/output"))
            try:
                receipt["output_clocks"][case] = output_clocks(run, plan["requested_clock"])
            except Exception as exc:
                receipt["output_clocks"][case] = {"unavailable_or_refused": str(exc)}
            save(out/"execution.json", receipt)
            need(start["returncode"] == 0 and (start["payload"] or {}).get("ok") is True,
                 "Public run failed; raw diagnostics/status/partial output paths retained")
            need(status["returncode"] == 0 and (status["payload"] or {}).get("ok") is True, "Public status failed")
            manifest = load(run/"manifest.json")
            need(manifest["state"] == "completed" and manifest["route"] == "direct"
                 and manifest["profile"]["selection"] == "layers", "Public owner did not complete requested route/profile")
            staged = inventory(run/"model")
            need(all(staged.get(k, {}).get("sha256") == v for k, v in
                     (plan["expected_public_hashes"] if case != "baseline" else hashes(plan["sources"])).items()),
                 "Staged native inputs differ from frozen case")
            need("datasets" in receipt["output_clocks"][case], "Missing/refused actual output clocks")
            receipt.setdefault("manifests", {})[case] = record(run/"manifest.json")
            save(out/"execution.json", receipt)
        receipt["state"] = "public_runs_completed_pending_independent_verification"
    except BaseException as exc:
        receipt["state"] = "stopped_with_diagnostics"
        receipt["error"] = type(exc).__name__+": "+str(exc)
        raise
    finally:
        try:
            validate_sources(plan)
            receipt["ordinary_source_unchanged"] = True
        except Exception as exc:
            receipt["ordinary_source_unchanged"] = False
            receipt["source_error"] = str(exc)
            receipt["state"] = "stopped_with_diagnostics"
        save(out/"execution.json", receipt)
    need(receipt["ordinary_source_unchanged"], "Ordinary source changed")
    return dict(out=str(out), state=receipt["state"], runs=str(out/"runs.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare", help="Input preparation and installed public edit; no native launch")
    for name in ("baseline-mdu", "manual-control", "manual-bc", "oracle", "dfm", "out"):
        p.add_argument("--"+name, required=True, type=Path)
    for name in ("manual", "oracle", "wheel"):
        p.add_argument("--expect-"+name+"-sha256", required=True)
    e = sub.add_parser("execute", help="Coordinator only: explicit current lease, installed public CLI")
    for name in ("prepared", "dfm", "install", "dispatch", "out"):
        e.add_argument("--"+name, required=True, type=Path)
    for name in ("preparation", "wheel"):
        e.add_argument("--expect-"+name+"-sha256", required=True)
    e.add_argument("--lease-owner", required=True)
    e.add_argument("--native-slot-granted", required=True, type=int)
    e.add_argument("--timeout", type=float, default=60)
    a = parser.parse_args()
    print(json.dumps(prepare(a) if a.action == "prepare" else execute(a), indent=2))


if __name__ == "__main__":
    main()
