"""Exercise the installed observation-transfer or directed-section CLI on copied manual controls."""
import argparse
import json
from pathlib import Path
import shutil

from .verify_observation_public import (
    Commands, DEFAULT_PREPARED, DEFAULT_RUNS, ROOT, dispatch, installed_identity,
    inventory, natural, need, save, sha,
)
from .verify_output_toggle_controls import compare_datasets


def invoke(commands, args, label, *argv):
    payload = json.loads(commands.raw(label, [args.dfm, *argv]))
    need(payload.get("protocol_version") == 2 and payload["ok"], label)
    return payload["result"]


def preview_apply(commands, args, label, model, *argv, output=None):
    before = inventory(model, mtimes=True)
    result = invoke(commands, args, label + "-preview", *argv)
    need(result.get("applied") is False and inventory(model, mtimes=True) == before, "Preview wrote model inputs")
    if output is not None:
        need(not output.exists(), "Preview created an export")
    token = result["input_sha256"]
    applied = invoke(commands, args, label + "-apply", *argv, "--apply", "--expect-sha256", token)
    need(applied.get("applied") is True and applied["input_sha256"] == token, "Apply differs from preview")
    return token


def case_inputs(args, commands, report):
    models = args.out / "inputs"
    models.mkdir()
    if args.node == "section":
        baseline = ROOT / "research/experiments/G12-ORI-I-native-159-02"
        cases = {}
        for name, steps, matching in [("reverse", 1, "reversed"), ("restore", 2, "control")]:
            model = models / name
            shutil.copytree(baseline / "cases/control", model)
            for i in range(steps):
                preview_apply(commands, args, f"{name}-{i}", model, "section", "reverse",
                              model / "f34.mdu", "--id", "Entrance")
                expected = baseline / "cases" / ("reversed" if i == 0 else "control")
                need(inventory(model) == inventory(expected), "Whole ten-file graph differs from manual input: " + name)
            cases[name] = model, "f34.mdu", baseline / "slot-159" / ("run-" + matching)
        return cases
    bases = DEFAULT_PREPARED / "cases"
    cases = {}
    for name, start, finish, mode in [
        ("append", "base", "add_east_probe", "append"),
        ("remove", "add_east_probe", "base", "replace-all"),
        ("move", "base", "move_centre", "replace-all"),
    ]:
        model = models / name
        shutil.copytree(bases / start, model)
        # Source comes from a real standalone export, apart from the deliberately
        # single-row append source which was authored by hand in the prior experiment.
        source = args.out / (name + ".xyn")
        if mode == "append":
            base = (bases / "base/observations.xyn").read_bytes()
            extended = (bases / "add_east_probe/observations.xyn").read_bytes()
            need(extended.startswith(base), "Manual append control changed")
            source.write_bytes(extended[len(base):])
        else:
            donor = models / ("donor-" + name)
            shutil.copytree(bases / finish, donor)
            before = inventory(donor, mtimes=True)
            preview_apply(commands, args, name + "-export", donor, "observation", "export",
                          donor / "model.mdu", "--out", source, output=source)
            need(inventory(donor, mtimes=True) == before and source.read_bytes() ==
                 (donor / "observations.xyn").read_bytes(), "Export was not an exact copy")
        incoming = sha(source)
        preview_apply(commands, args, name + "-import", model, "observation", "import", model / "model.mdu",
                      "--source", source, "--mode", mode, "--crs", "EPSG:32631", "--unit", "m")
        need(sha(source) == incoming and inventory(model) == inventory(bases / finish),
             "Import differs from the independent nine-file case: " + name)
        cases[name] = model, "model.mdu", DEFAULT_RUNS[finish]
    return cases


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.out)
    report = {"node": args.node, "state": "preparing", "cases": {}, "gui_parity": "not_verified"}
    try:
        identity = installed_identity(args, commands)
        report["wheel_sha256"] = identity["wheel_sha256"]
        cases = case_inputs(args, commands, report)
        for name, (model, mdu, expected_run) in cases.items():
            inputs = inventory(model, mtimes=True)
            row = report["cases"][name] = {"source": str(model), "expected_run": str(expected_run), "exact_inputs": inputs}
            if not args.execute:
                continue
            dispatch(args)
            run_dir = args.out / ("run-" + name)
            expected = natural(expected_run)
            commands.cli(args, name + "-native", "run", "start", model / mdu, "--route", "direct", "--install",
                         args.install, "--out", run_dir, "--timeout", "60", timeout=100)
            row["terminal"] = natural(run_dir, version=identity["version"], executable_sha=expected["executable_sha256"])
            m = json.loads((run_dir / "manifest.json").read_bytes())
            for f in m["inputs"]:
                p = Path(f["relative_path"])
                need((run_dir / "model" / p).read_bytes() == (model / p).read_bytes(), "Staged input changed")
            need(inventory(model, mtimes=True) == inputs, "Native run modified source")
            got, want = run_dir / "model/output", expected_run / "model/output"
            files = sorted(f.name for f in want.glob("*.nc"))
            need(len(files) == 4 and files == sorted(f.name for f in got.glob("*.nc")), "Wrong output inventory")
            row["datasets"] = {}
            for f in files:
                diff = compare_datasets(want / f, got / f)
                need(diff["shared_exact"], "Variable value, dimension, mask or attribute mismatch: " + f)
                row["datasets"][f] = len(diff["variables"])
            last = "1990-08-05T00:10:00" if args.node == "section" else "2001-01-01T00:02:00"
            samples = 11 if args.node == "section" else 13
            axes = m["verification"]["axes"]
            need(all(axes[k]["last"] == last and axes[k]["samples"] == samples for k in ("history", "map")),
                 "Unexpected history/map time axis")
            row.update(last=last, samples=samples)
            save(args.out / "verification.json", report)
        report["state"] = "passed_installed_matching_native_cases" if args.execute else "passed_installed_file_only"
    except Exception as exc:
        report.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        save(args.out / "verification.json", report)
    print(report["state"], args.node, len(report["cases"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("node", choices=("section", "observation"))
    for option in ("dfm", "out", "install"):
        ap.add_argument("--" + option, type=lambda s: Path(s).resolve(), required=True)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--native-slot-granted", type=int)
    ap.add_argument("--lease-owner")
    ap.add_argument("--dispatch", type=Path, default=ROOT / "research/experiments/roadmap-coordinator-20261104/dispatch.json")
    run(ap.parse_args())
