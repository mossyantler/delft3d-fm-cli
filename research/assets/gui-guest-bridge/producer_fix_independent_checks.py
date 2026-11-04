"""Replay repair negatives through Raman's unchanged verifier, never launch code.

The portable suite uses synthetic executable bytes. This separate local audit
anchors its copied TEST collections to a real retained Phase A and read-only suite
identity, so an earlier synthetic-suite mismatch cannot mask the target rejection.
It manufactures no live guest proof; positive control means offline structure only.
"""
from __future__ import annotations

import argparse
import copy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from research.workflows.replay import gui_guest_bridge as producer
from research.workflows.verification import verify_gui_guest as independent


def seal(root):
    bundle_sha = producer.sha(root / "bundle/bundle.json")
    receipt = producer.read_json(root / "evidence/guest-check.json")
    receipt["bundle_sha256"] = bundle_sha
    (root / "evidence/guest-check.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    manifest = producer.read_json(root / "collection.json")
    manifest["bundle_sha256"] = bundle_sha
    manifest["files"] = producer.inventory(root, exclude=("collection.json",))
    (root / "collection.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return producer.sha(root / "collection.json")


def check(args):
    source = producer.no_links(args.collection).resolve(strict=True)
    if producer.sha(source / "collection.json") != args.collection_sha256:
        raise ValueError("Source collection fingerprint differs")
    reference = producer.no_links(args.phase_a).resolve(strict=True)
    anchor = independent.phase_a(reference, args.phase_a_sha256)
    original = producer.read_json(reference)
    # Read-only seven-file hash/length inspection, no native version/API probe.
    selected = producer.suite_identity(original["installation"]["root"], producer.PAYLOAD)
    if {name: entry["sha256"] for name, entry in selected["files"].items()} != anchor["suite_files"]:
        raise ValueError("Read-only suite differs from the independent external Phase A")
    out = producer.fresh(args.out, source, reference.parent, original["installation"]["root"])
    control = out / "test-control"
    producer.copy_checked(source, control)
    bundle = producer.read_json(control / "bundle/bundle.json")
    bundle["suite_identity"] = selected
    (control / "bundle/bundle.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    receipt = producer.read_json(control / "evidence/guest-check.json")
    receipt["suite_identity"] = selected
    (control / "evidence/guest-check.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    control_sha = seal(control)
    control_result = independent.verify_collection(control, control_sha, reference, args.phase_a_sha256,
        expected_nonce=bundle["nonce"], expected_host=bundle["host_identity"])
    if control_result["state"] != "prepared" or control_result["runtime_acceptance"] != "unknown":
        raise AssertionError("Independent offline control did not reach the receipt checks")
    prepared = producer.wall_time(bundle["created_at_utc"])
    cases = [
        ("preparation_after_receipt", {"at_utc": (prepared - timedelta(seconds=1)).isoformat()}, "phase_inversion"),
        ("unc_suite", {"guest_install_root": r"\\uncontacted-test-server\share\suite"}, "escaped_guest_path"),
        ("suite_equals_bundle", {"guest_install_root": receipt["guest_bundle_root"]}, "escaped_guest_path"),
        ("suite_inside_bundle", {"guest_install_root": receipt["guest_bundle_root"] + "/suite"}, "escaped_guest_path"),
        ("suite_equals_evidence", {"guest_install_root": receipt["guest_evidence_root"]}, "escaped_guest_path"),
        ("bundle_equals_evidence", {"guest_bundle_root": receipt["guest_evidence_root"]}, "escaped_guest_path"),
        ("runtime_adapter_still_required", {}, "runtime_evidence_refused"),
    ]
    results = []
    for name, changes, expected_code in cases:
        target = out / name
        producer.copy_checked(control, target)
        changed = copy.deepcopy(receipt) | changes
        (target / "evidence/guest-check.json").write_text(json.dumps(changed, indent=2), encoding="utf-8")
        if name == "runtime_adapter_still_required":
            producer.write_new(target / "evidence/normalized.json", {"evidence_kind": "observed_runtime"})
        digest = seal(target)
        before = producer.inventory(target)
        try:
            independent.verify_collection(target, digest, reference, args.phase_a_sha256,
                expected_nonce=bundle["nonce"], expected_host=bundle["host_identity"])
        except independent.Refusal as exc:
            if exc.code != expected_code:
                raise AssertionError(f"{name}: masked rejection {exc.code}, expected {expected_code}") from exc
            results.append({"case": name, "state": "refused", "code": exc.code, "message": str(exc),
                            "collection_sha256": digest})
        else:
            raise AssertionError("Independent verifier accepted negative: " + name)
        if producer.inventory(target) != before:
            raise AssertionError("Verifier modified source evidence")
    report = {"scope": "offline TEST collections; no observed guest or GUI evidence", "passed": True,
              "phase_a_sha256": args.phase_a_sha256, "control_sha256": control_sha,
              "control_state": control_result["state"], "runtime_acceptance": "unknown", "negatives": results,
              "independent_verifier_modified": False, "native_processes_launched": False}
    producer.write_new(out / "result.json", report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--collection-sha256", required=True)
    parser.add_argument("--phase-a", type=Path, required=True)
    parser.add_argument("--phase-a-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with patch.object(subprocess, "Popen", side_effect=AssertionError("No launch")), \
            patch.object(subprocess, "run", side_effect=AssertionError("No subprocess")), \
            patch.object(subprocess, "check_output", side_effect=AssertionError("No external probes")), \
            patch.object(producer.identity, "probe", side_effect=AssertionError("No identity/profile probes")), \
            patch.object(producer.identity.c, "WinDLL", side_effect=AssertionError("No live Windows APIs")):
        check(args)


if __name__ == "__main__":
    main()
