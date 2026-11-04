"""B13 three-case replay: nonnative prepare, leased installed-public execute.

Prepare generates the tracked vertical-cell specification with the installed
public CLI. A closed JSON hash/splice fixture supplies the expected bytes.
Execute invokes ONLY the installed dfm entry point,
including its existing run owner. It never launches an engine or manages a Job.
See ``prepare --help`` and ``execute --help``. Numerical acceptance belongs to
research.workflows.verification.verify_vertical_boundary_cases, not this producer.
"""
from __future__ import annotations

import argparse
import base64
import configparser
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import os
import stat
from urllib.parse import urlsplit
from urllib.request import url2pathname
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_SHA256 = "44adda3998f423735828d5ee53e6e984cf943a1a61c0e8e19b116c353ed197a2"

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
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "Duplicate JSON key: "+key)
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON: "+value)))


def save(path, data):
    path = unaliased(path, missing_leaf=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def unaliased(path, *, missing_leaf=False):
    """lstat each component BEFORE resolving; lexists includes dangling links."""
    path = Path(path).absolute()
    parts = list(reversed((path, *path.parents)))
    for index, part in enumerate(parts):
        try:
            observed = part.lstat()
        except FileNotFoundError:
            need(missing_leaf and index == len(parts)-1, "Missing path/parent: "+str(part))
            continue
        need(not stat.S_ISLNK(observed.st_mode) and not getattr(observed, "st_file_attributes", 0) & 0x400,
             "Aliased/reparse path: "+str(part))
    return path.resolve(strict=not missing_leaf)


def regular(path):
    path = unaliased(path)
    need(path.is_file(), "Not a regular file: "+str(path))
    return path


def record(path):
    path = regular(path)
    st = path.stat()
    return dict(path=str(path), sha256=sha(path), bytes=st.st_size,
                device=st.st_dev, inode=st.st_ino, mtime_ns=st.st_mtime_ns)


def checked(item):
    need(record(item["path"]) == item, "File changed/replaced: "+item["path"])


def inventory(root):
    root = unaliased(root)
    result = {}
    for parent, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            unaliased(Path(parent)/name)
        for name in names:
            path = Path(parent)/name
            result[path.relative_to(root).as_posix()] = record(path)
    return dict(sorted(result.items()))


def hashes(items):
    return {name: item["sha256"] for name, item in items.items()}


EVIDENCE_MARKERS = ("preparation.json", "execution.json", "manifest.json", "freeze.json",
                    "predeclared.json", "acceptance.json", "verification.json", "clean-checkout-proof.json")


def output_path(path, *, protected=()):
    path = unaliased(path, missing_leaf=True)
    need(not os.path.lexists(path), "Output already exists (including dangling paths): "+str(path))
    need(path.parent.is_dir(), "Output parent must exist")
    fixed = [ROOT/"examples", ROOT/"src", ROOT/"research/evidence", ROOT/"research/notes",
             ROOT/"research/catalog", *protected]
    for item in fixed:
        other = Path(item).absolute().resolve(strict=False)
        need(not path.is_relative_to(other) and not other.is_relative_to(path),
             "Output overlaps protected input/installation/evidence: "+str(other))
    for parent in path.parents:
        need(not any(os.path.lexists(parent/name) for name in EVIDENCE_MARKERS),
             "Output is inside recorded evidence: "+str(parent))
    return path


def fresh(path, *, protected=()):
    path = output_path(path, protected=protected)
    path.mkdir()
    return unaliased(path)


def installation_paths(identity):
    return [identity["prefix"], identity["site_packages"], identity["distribution"],
            Path(identity["wheel"]["path"]).parent]


def prepare(a):
    regular(__file__)
    spec = regular(a.spec)
    fixture = regular(ROOT/"examples/layers/vertical-cell.expected.json")
    need(sha(fixture) == EXPECTED_SHA256, "Portable expectation fixture pin differs")
    declaration = load(fixture)
    need(declaration["version"] == 1 and declaration["request"] == REQUEST,
         "Unsupported portable expectation contract")
    need(sha(spec) == declaration["spec_sha256"], "Tracked specification pin differs")
    spec_identity = record(spec)
    identity = installed(a.dfm, a.expect_launcher_sha256)
    if a.expect_wheel_sha256:
        need(identity["wheel"]["sha256"] == a.expect_wheel_sha256.lower(), "Installed wheel pin differs")
    out = fresh(a.out, protected=[spec.parent, fixture.parent, *installation_paths(identity)])
    commands = out/"commands"
    commands.mkdir()
    calls = Calls(regular(a.dfm), commands, a.expect_launcher_sha256)
    calls.call("create", ["layers", "create", spec, "--out", out/"source"])
    mdu = out/"source/model.mdu"
    graph = calls.call("layers-inspect", ["layers", "inspect", mdu])
    files = {item["relative_path"]: record(item["path"]) for item in graph["files"]}
    need(len(files) == 9 and hashes(files) == declaration["baseline_hashes"],
         "Generated nine-native-input hashes differ from portable expectation")
    need(all(Path(v["path"]) == mdu.parent/k for k, v in files.items()), "Generated graph escapes source root")
    bc = "boundaries.bc"
    before = (mdu.parent/bc).read_bytes()
    cell = declaration["single_cell"]
    need(before[cell["start"]:cell["end"]] == b"20", "Declared source token differs")
    expected = before[:cell["start"]]+b"22"+before[cell["end"]:]
    need(hashlib.sha256(expected).hexdigest() == declaration["manual_bc_sha256"], "Manual splice hash differs")
    clock = graph["layers"]["clock"]
    need(clock["duration_seconds"] == 20, "B13 clock must be exactly 20 seconds")
    (out/"independent").mkdir()
    shutil.copyfile(fixture, out/"independent/vertical-cell.expected.json")
    copied = {}
    for case in CASES:
        root = out/"cases"/case
        root.mkdir(parents=True)
        for name, item in files.items():
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(expected if case == "manual" and name == bc else Path(item["path"]).read_bytes())
        copied[case] = inventory(root)
    plan = dict(version=1, portable_version=3, node="B13-PORTABILITY-I", state="prepared_not_executed", prepared=str(out),
                producer=record(__file__), installed_cli=identity, sources=files, source_root=str(mdu.parent),
                source_directory=inventory(mdu.parent), mdu=mdu.name, bc=bc, cases=copied,
                independent={p.name: record(p) for p in (out/"independent").iterdir()},
                original_independent=[spec_identity, record(fixture)],
                request=REQUEST, boundary="west", value="22", cell=cell, requested_clock=clock,
                expected_public_hashes=hashes(copied["manual"]),
                native_input_count=9, excluded_from_engine_authority=sorted(set(inventory(mdu.parent))-set(files)),
                case_order=list(CASES), route="direct", profile="layers",
                limitations=["Only installed public layers create/inspect and schema/vertical edit commands during prepare",
                             "Closed data-only hash/splice expectation; no oracle code or archived experiment imports",
                             "JSON spec/provenance sidecars are not copied or interpreted as engine inputs",
                             "A single endpoint/time/vertical-knot edit; no full-profile perturbation",
                             "No inferred response threshold or scientific accuracy claim"])
    public_edit(calls, out, plan)
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


def installed(dfm, expected_launcher_sha256):
    """Require an external launcher trust pin; RECORD is consistency evidence."""
    need(isinstance(expected_launcher_sha256, str) and len(expected_launcher_sha256) == 64
         and all(c in "0123456789abcdefABCDEF" for c in expected_launcher_sha256),
         "An external trusted launcher SHA-256 is required")
    launcher_pin = expected_launcher_sha256.lower()
    dfm = regular(dfm)
    need(sha(dfm) == launcher_pin, "External trusted launcher SHA-256 differs")
    need(dfm.name == ("dfm.exe" if os.name == "nt" else "dfm")
         and dfm.parent.name == ("Scripts" if os.name == "nt" else "bin"), "Use exact installed dfm console launcher")
    prefix = dfm.parent.parent
    sites = [p for p in (prefix/"Lib/site-packages", *prefix.glob("lib/python*/site-packages")) if p.is_dir()]
    need(len(sites) == 1, "One isolated installed site-packages required")
    site, = sites
    infos = list(site.glob("delft3d_fm_cli-*.dist-info"))
    need(len(infos) == 1, "One installed distribution required")
    info, = infos
    unaliased(info)
    metadata_names = ("METADATA", "direct_url.json", "entry_points.txt", "RECORD")
    metadata = {name: record(info/name) for name in metadata_names}
    rows = list(csv.reader(io.StringIO((info/"RECORD").read_text(encoding="utf-8"))))
    need(all(len(row) == 3 for row in rows) and len({row[0] for row in rows}) == len(rows), "Malformed/duplicate RECORD rows")

    def receipt(path):
        path = regular(path)
        relative = os.path.relpath(path, site).replace("\\", "/")
        matches = [row for row in rows if os.path.normcase(os.path.abspath(site/row[0])) == os.path.normcase(str(path))]
        need(len(matches) == 1 and matches[0][0] == relative, "Missing/duplicate/noncanonical RECORD binding: "+relative)
        row, = matches
        digest = "sha256="+base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip("=")
        need(row[1] == digest and row[2] == str(path.stat().st_size), "Installed RECORD hash/size differs: "+relative)
        return dict(relative_path=row[0], digest=row[1], bytes=int(row[2]))

    receipts = {name: receipt(info/name) for name in metadata_names if name != "RECORD"}
    receipts["launcher"] = receipt(dfm)
    entry = configparser.ConfigParser(interpolation=None, strict=True)
    entry.read_string((info/"entry_points.txt").read_text(encoding="utf-8"))
    need(entry.get("console_scripts", "dfm", fallback=None) == "dfm_cli.cli:main", "Registered dfm entry point differs")
    direct = load(regular(info/"direct_url.json"))
    url = urlsplit(direct.get("url", ""))
    need(url.scheme == "file" and not url.netloc and not direct.get("dir_info", {}).get("editable"),
         "Noneditable local wheel installation required")
    wheel = regular(url2pathname(url.path))
    need(wheel.suffix == ".whl" and direct["archive_info"]["hashes"]["sha256"] == sha(wheel), "Wheel pin differs")
    with ZipFile(wheel) as archive:
        expected = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                    if name.startswith("dfm_cli/") and not name.endswith("/")}
        for name in ("METADATA", "entry_points.txt"):
            matches = [n for n in archive.namelist() if n.endswith(".dist-info/"+name)]
            need(len(matches) == 1 and archive.read(matches[0]) == (info/name).read_bytes(), "Installed/wheel metadata differs: "+name)
    need(expected and all(".." not in Path(n).parts for n in expected), "Invalid wheel module paths")
    modules = {name: record(site/name) for name in expected}
    need(all(modules[n]["sha256"] == digest for n, digest in expected.items()), "Installed module differs from wheel")
    actual = {p.relative_to(site).as_posix() for p in (site/"dfm_cli").rglob("*")
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    need(actual == set(expected), "Foreign installed package file")
    versions = [line.removeprefix("Version: ") for line in (info/"METADATA").read_text(encoding="utf-8").splitlines()
                if line.startswith("Version: ")]
    need(len(versions) == 1, "Missing/ambiguous installed version")
    return dict(dfm=record(dfm), python=record(dfm.parent/("python.exe" if os.name == "nt" else "python")),
                wheel=record(wheel), modules=modules, version=versions[0],
                metadata=metadata, record_receipts=receipts, registered_entry_point="dfm_cli.cli:main",
                launcher_anchor=dict(sha256=launcher_pin, authority="caller-supplied trusted installation receipt; not mutable RECORD"),
                prefix=str(unaliased(prefix)), site_packages=str(unaliased(site)), distribution=str(unaliased(info)),
                identity_method="external launcher SHA-256 + registered entry point + RECORD/wheel consistency")


class Calls:
    def __init__(self, dfm, out, expected_launcher_sha256):
        self.dfm, self.out, self.calls = str(regular(dfm)), unaliased(out), []
        self.launcher_pin = expected_launcher_sha256
        self.identity = installed(dfm, self.launcher_pin)

    def call(self, label, argv, *, allow_failure=False):
        need(installed(self.dfm, self.launcher_pin) == self.identity, "Installed launcher/distribution changed before public call")
        unaliased(self.out)
        args = [self.dfm, *map(str, argv)]
        prefix = self.out/f"{len(self.calls):02d}-{label}"
        item = dict(argv=args, cwd=str(self.out), started_utc=datetime.now(timezone.utc).isoformat(),
                    stdout=str(prefix)+".stdout", stderr=str(prefix)+".stderr")
        self.calls.append(item)
        env = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        try:
            # No wrapper timeout/kill: public run owner enforces --timeout and cleanup.
            for name in ("stdout", "stderr"):
                unaliased(item[name], missing_leaf=True)
                need(not os.path.lexists(item[name]), "Raw call output already exists")
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
    regular(__file__)
    grant = lease(a)  # Before directory creation or ANY public command.
    root = regular(Path(a.prepared)/"preparation.json").parent
    need(sha(root/"preparation.json") == a.expect_preparation_sha256.lower(), "Preparation pin differs")
    plan = load(root/"preparation.json")
    need(plan["node"] == "B13-PORTABILITY-I" and plan["prepared"] == str(root), "Wrong preparation binding")
    validate_sources(plan)
    validate_cases(root, plan, edited=True)
    identity = installed(a.dfm, a.expect_launcher_sha256)
    need(identity["wheel"]["sha256"] == a.expect_wheel_sha256.lower(), "Installed wheel pin differs")
    need(identity == plan["installed_cli"], "Execute must use the exact installed public CLI prepared/pinned")
    need(1 <= a.timeout <= 300, "Bounded public native timeout required")
    out = fresh(a.out, protected=[root, Path(plan["source_root"]), unaliased(a.install),
                                 Path(a.dispatch).absolute().parent, *installation_paths(identity),
                                 *[Path(item["path"]).parent for item in plan["original_independent"]]])
    calls = Calls(regular(a.dfm), out, a.expect_launcher_sha256)
    receipt = dict(version=1, state="in_progress", lease=grant, installed_cli=identity,
                   preparation=record(root/"preparation.json"), runs=[], output_clocks={})
    save(out/"execution.json", receipt)
    try:
        validate_cases(root, plan, edited=True)
        for case in CASES:
            validate_sources(plan)
            validate_cases(root, plan, edited=True)
            need(installed(a.dfm, a.expect_launcher_sha256) == identity, "Installed public CLI changed")
            receipt["lease"] = lease(a)
            run = out/("run-"+case)
            unaliased(run, missing_leaf=True)
            need(not os.path.lexists(run), "Native run destination already exists")
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
    for name in ("dfm", "out"):
        p.add_argument("--"+name, required=True, type=Path)
    p.add_argument("--spec", type=Path, default=ROOT/"examples/layers/vertical-cell.json")
    p.add_argument("--expect-wheel-sha256", help="Optional explicit consent pin; actual wheel is always verified/recorded")
    p.add_argument("--expect-launcher-sha256", required=True,
                   help="Required SHA-256 from a separately trusted installation receipt, never from mutable RECORD")
    e = sub.add_parser("execute", help="Coordinator only: explicit current lease, installed public CLI")
    for name in ("prepared", "dfm", "install", "dispatch", "out"):
        e.add_argument("--"+name, required=True, type=Path)
    for name in ("preparation", "wheel"):
        e.add_argument("--expect-"+name+"-sha256", required=True)
    e.add_argument("--expect-launcher-sha256", required=True,
                   help="Same externally trusted launcher pin used for preparation")
    e.add_argument("--lease-owner", required=True)
    e.add_argument("--native-slot-granted", required=True, type=int)
    e.add_argument("--timeout", type=float, default=60)
    a = parser.parse_args()
    print(json.dumps(prepare(a) if a.action == "prepare" else execute(a), indent=2))


if __name__ == "__main__":
    main()
