"""Compare an installed CLI's static identity gate with the retained #153/#155 FM trials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def run(dfm, controls, out):
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    cases = {}
    for slot, folder, runs in [
        (153, controls / "native-controls-UNLAUNCHED-02", controls / "native-slot-153-01"),
        (155, controls / "native-slot-155-01/controls", controls / "native-slot-155-01"),
    ]:
        evidence = json.loads((runs / "verification.json").read_bytes())
        assert evidence["slot"] == slot and evidence["no_retry"]
        for case in evidence["cases"]:
            name = case["case"]
            mdu = folder / name / "model.mdu"
            before = hashlib.sha256(mdu.read_bytes()).hexdigest()
            # This test deliberately does not infer identity from a successful/failed native exit.
            invalid = name in {"missing", "empty", "wrong-case-value", "duplicate-identical",
                               "duplicate-conflicting", "legacy-wrong-general-good"}
            def call(label, *argv):
                proc = subprocess.run([dfm, *map(str, argv)], cwd=out, env=env, capture_output=True, timeout=30)
                (out / f"{name}-{label}.stdout.json").write_bytes(proc.stdout)
                (out / f"{name}-{label}.stderr").write_bytes(proc.stderr)
                payload = json.loads(proc.stdout)
                assert payload["protocol_version"] == 2 and payload["ok"] == (proc.returncode == 0)
                return proc.returncode, payload
            code, payload = call("validation", "model", "validate", mdu)
            assert code == (4 if invalid else 0), (name, code, payload)
            report = payload["error"]["details"] if invalid else payload["result"]
            identity = report.get("fm_model_identity", report)
            assert identity["static_launch_eligible"] == (not invalid), (name, identity)
            assert identity["engine_initialization"] == "not_performed"
            if name == "numeric-version-mismatch-9.99":
                assert case["native_returncode"] == 1 and identity["version"]["source_major_mismatch_diagnostic"]
            if invalid:
                for route in ("direct", "dimr"):
                    target = out / f"must-not-exist-{name}-{route}"
                    code, result = call(route, "run", "start", mdu, "--route", route, "--out", target,
                                        "--install", out / "nonexistent-installation")
                    assert code == 4 and result["error"]["code"] == "fm_model_identity_invalid" and not target.exists()
            assert hashlib.sha256(mdu.read_bytes()).hexdigest() == before
            cases[name] = {"identity": identity["state"], "section": identity["lookup_section"],
                           "expected_prelaunch_refusal_both_routes": invalid,
                           "source_mdu_sha256": before, "observed_native_result": case["state"]}
    assert len(cases) == 14
    (out / "verification.json").write_text(json.dumps({"state": "passed", "dfm": str(dfm), "cases": cases},
                                                       indent=2), encoding="utf-8")
    print(f"{len(cases)} identity cases passed; no native launch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("dfm", "controls", "out"):
        parser.add_argument("--" + key, type=lambda x: Path(x).resolve(), required=True)
    run(**vars(parser.parse_args()))
