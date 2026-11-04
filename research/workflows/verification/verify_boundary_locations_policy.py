"""Public-CLI old-policy consent contrast; no native/GUI and no installed edits.

An isolated copy of the retained old public package produces genuine consent and
actual commented BC output. On IDENTICAL inputs/argv/absolute output path, the
current public CLI must reject that consent and require its new physical plan.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

from .verify_boundary_locations import INTEGRATED_FILES, sources
from .verify_boundary_locations_fixture import (
    ROOT, Fixture, author_target_last, directories, fingerprints, require, require_raw_bc, save, sha,
)


def replay(out, legacy_run, legacy_sha256, producer_freeze, producer_sha256):
    out = Path(out).absolute()
    require(not out.exists(), "Fresh output directory required")
    legacy_run = Path(legacy_run).absolute()
    legacy_raw = (legacy_run / "verification.json").read_bytes()
    require(sha(legacy_raw) == legacy_sha256, "Legacy receipt external SHA mismatch")
    legacy = json.loads(legacy_raw)
    require(legacy["sources_before"] == legacy["sources_after"], "Legacy source capture was not stable")
    producer_raw = Path(producer_freeze).read_bytes()
    require(sha(producer_raw) == producer_sha256, "Current producer freeze external SHA mismatch")
    producer = json.loads(producer_raw)
    require(set(producer["product_files"]) == INTEGRATED_FILES, "Exact six-file integrated freeze required")
    before = sources()
    require(all(before.get(n) == d for n, d in producer["product_files"].items()), "Live producer differs from freeze")
    out.mkdir(parents=True, exist_ok=False)
    (out / "legacy-receipt.json").write_bytes(legacy_raw)
    (out / "producer-freeze.json").write_bytes(producer_raw)
    # Copy only into this fresh evidence directory; installation/repository and
    # historical evidence remain untouched. No interpreter settings are changed.
    package_root = out / "isolated-legacy-public-package"
    shutil.copytree(ROOT / "src/dfm_cli", package_root / "dfm_cli",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    captured = {}
    for name, digest in legacy["sources_after"].items():
        if not name.startswith("src/dfm_cli/"):
            continue
        relative = PurePosixPath(name).relative_to("src")
        require(".." not in relative.parts and relative.suffix == ".py", "Unrecognized frozen source path")
        raw = (legacy_run / "source-snapshot" / name).read_bytes()
        require(sha(raw) == digest, "Legacy frozen source mismatch: " + name)
        target = package_root.joinpath(*relative.parts)
        require(target.resolve().is_relative_to(package_root.resolve()), "Legacy overlay escaped evidence package")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        captured[name] = digest
    require(INTEGRATED_FILES <= set(captured), "Legacy public snapshot must bind all six old policy modules")
    fixture = Fixture(out / "fixture")
    signals, _, prefix, _ = author_target_last(fixture)
    expected_bc = prefix + b"".join(signals["west"])
    input_files = fingerprints(fixture.model)
    input_directories = directories(fixture.model)
    source_bytes = fixture.source.read_bytes()
    args = ["boundary", "location-import", str(fixture.mdu), "--source", str(fixture.source),
            "--out", str(fixture.out), "--coordinates", "as-is"]
    calls = []

    def call(cwd, extra=()):
        argv = [sys.executable, "-B", "-m", "dfm_cli", *args, *extra]
        process = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=30)
        number = len(calls) + 1
        (out / f"{number:02d}.stdout.json").write_bytes(process.stdout)
        (out / f"{number:02d}.stderr.txt").write_bytes(process.stderr)
        payload = json.loads(process.stdout)
        row = {"argv": argv, "cwd": str(cwd), "returncode": process.returncode, "response": payload}
        calls.append(row)
        save(out / "commands.json", calls)
        require(payload.get("protocol_version") == 2 and (process.returncode == 0) == payload["ok"], "Public protocol/exit mismatch")
        require(not process.stderr, "Unexpected public CLI traceback/stderr")
        return process.returncode, payload

    code, old_preview = call(package_root)
    require(code == 0 and not fixture.out.exists(), "Legacy preview wrote output or failed")
    old_hash = old_preview["result"]["input_sha256"]
    code, old_apply = call(package_root, ["--apply", "--expect-sha256", old_hash])
    require(code == 0, "Legacy public apply failed")
    legacy_bc = (fixture.out / "signals.bc").read_bytes()
    require(legacy_bc != expected_bc and b"boundary-location-import removed:" in legacy_bc,
            "Retained old producer does not exercise the commented-retirement policy")
    # Retain the actual old output, freeing the SAME absolute requested path.
    # Both resolved directory targets are checked inside this fresh evidence root
    # before the directory rename. No deletion or recursive cleanup occurs.
    old_output = out / "legacy-observed-output"
    require(fixture.out.resolve().is_relative_to(out.resolve()) and
            old_output.resolve().is_relative_to(out.resolve()) and not old_output.exists(),
            "Legacy output move escaped its owned evidence directory")
    fixture.out.rename(old_output)
    require(fingerprints(fixture.model) == input_files and directories(fixture.model) == input_directories and fixture.source.read_bytes() == source_bytes,
            "Legacy public operation edited source inputs")
    code, new_preview = call(ROOT)
    require(code == 0 and not fixture.out.exists(), "Current preview wrote output or failed")
    new_hash = new_preview["result"]["input_sha256"]
    require(new_hash != old_hash, "Changed physical output policy reused old consent fingerprint")
    code, stale = call(ROOT, ["--apply", "--expect-sha256", old_hash])
    require(code == 4 and stale["error"]["code"] == "boundary_locations_stale" and not fixture.out.exists(),
            "Legacy comment-policy consent authorized physical deletion or created output")
    require(fingerprints(fixture.model) == input_files and directories(fixture.model) == input_directories and fixture.source.read_bytes() == source_bytes,
            "Stale consent refusal edited original inputs")
    code, current = call(ROOT, ["--apply", "--expect-sha256", new_hash])
    require(code == 0, "Fresh physical-policy consent failed")
    require_raw_bc((fixture.out / "signals.bc").read_bytes(), expected_bc)
    require(fingerprints(fixture.model) == input_files and directories(fixture.model) == input_directories and fixture.source.read_bytes() == source_bytes,
            "Fresh public apply edited original inputs")
    after = sources()
    require(before == after, "Live sources changed during policy contrast")
    report = {"state": "passed_public_old_consent_refusal", "passed": True, "public_CLI_calls": len(calls),
              "identical_request_argv_and_absolute_paths": args, "identical_input_files": input_files,
              "identical_input_directories": input_directories,
              "legacy_input_sha256": old_hash, "current_input_sha256": new_hash,
              "old_policy_actual_BC_sha256": sha(legacy_bc), "physical_policy_actual_BC_sha256": sha(expected_bc),
              "legacy_consent_exit_code": 4, "legacy_consent_error": "boundary_locations_stale",
              "stale_consent_created_output": False, "original_inputs_unchanged": True,
              "legacy_source_hashes": captured, "legacy_receipt_sha256": legacy_sha256,
              "producer_freeze_sha256": producer_sha256, "sources_before": before, "sources_after": after,
              "native_GUI_console_VM_launches": 0, "installed_files_edited": False,
              "historical_evidence_modified": False, "scope": "As-is consent and exact BC bytes; no transform numerical or native compatibility claim"}
    save(out / "verification.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--legacy-run", type=Path, required=True)
    parser.add_argument("--legacy-receipt-sha256", required=True)
    parser.add_argument("--producer-freeze", type=Path, required=True)
    parser.add_argument("--expect-producer-freeze-sha256", required=True)
    args = parser.parse_args(argv)
    report = replay(args.out, args.legacy_run, args.legacy_receipt_sha256,
                    args.producer_freeze, args.expect_producer_freeze_sha256)
    print(json.dumps({"passed": report["passed"], "public_CLI_calls": report["public_CLI_calls"], "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
