"""Replay the accepted G11 positive and negative controls against an installed wheel.

Read-only: reuses the independent verifier's real/synthetic retained run folders.
No GUI, engine, or source-tree CLI is invoked. Use a fresh --out directory.
"""
import argparse
import json
from pathlib import Path
import subprocess

from .verify_observation_public import Commands, ROOT, installed_identity, inventory, need, save, sha


def replay(args):
    receipt = args.reference / "verification.json"
    need(sha(receipt) == args.expect_sha256, "Independent receipt fingerprint differs")
    frozen = json.loads(receipt.read_bytes())
    cases = frozen["cases"]
    need(frozen["failed_cases"] == 0 and len(cases) == len({c["case"] for c in cases}) == 29,
         "Expected the complete second-candidate independent review")
    args.out.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.out)
    package = installed_identity(args, commands)
    report = {"state": "running", "wheel_sha256": package["wheel_sha256"],
              "reference_sha256": args.expect_sha256, "extras": package["extras"], "cases": {}}
    try:
        for case in cases:
            name = case["case"]
            ref = args.reference / name
            # Only reuse the fixture path, never execute a command from the receipt.
            run = Path(json.loads((ref / "command.json").read_bytes())["argv"][-1]).resolve(strict=True)
            need(run.is_relative_to(ROOT / "research/experiments"), "Not a retained experiment")
            expected = json.loads((ref / "stdout.json").read_bytes())
            before = inventory(run, mtimes=True)
            argv = list(map(str, (args.dfm, "results", "stations", run)))
            proc = subprocess.run(argv, cwd=args.out, env=commands.env, capture_output=True, timeout=60)
            (args.out / "commands" / (name + ".stdout")).write_bytes(proc.stdout)
            (args.out / "commands" / (name + ".stderr")).write_bytes(proc.stderr)
            result = json.loads(proc.stdout)
            need(not case["failures"] and case["run_bytes_unchanged"], name + ": independent case failed")
            need(proc.returncode == case["returncode"] and result == expected, name + ": package differs from independent reply")
            need(inventory(run, mtimes=True) == before, name + ": run files changed")
            if proc.returncode == 0:
                assignments = {s["station_id"]: s["assignment"] for s in result["result"]["stations"]}
                need(assignments == case["assignments"], name + ": assignments differ from pinned receipt")
            report["cases"][name] = {"argv": argv, "exit_code": proc.returncode,
                                     "reply_matched": True, "files_unchanged": len(before)}
        report["state"] = "passed_installed_station_replay"
    except Exception as exc:
        report.update(state="failed", error=str(exc))
        raise
    finally:
        save(args.out / "verification.json", report)
    print(report["state"], len(report["cases"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("dfm", "reference", "out"):
        parser.add_argument("--" + key, type=lambda v: Path(v).resolve(), required=True)
    parser.add_argument("--expect-sha256", required=True)
    replay(parser.parse_args())
