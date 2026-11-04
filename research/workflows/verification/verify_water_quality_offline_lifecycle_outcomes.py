"""Classify natural completion races separately from unconfirmed stop evidence."""
import argparse
import json
from pathlib import Path

from .verify_water_quality import fingerprint, save
from .verify_water_quality_outputs import require, sha
from .verify_water_quality_offline_lifecycle_observe import confirmed_stop


def natural_exit_proved(record):
    if not isinstance(record, dict):
        return False
    evidence = record.get("ownership", {}).get("normal_exit", {})
    return (record.get("state") == "completed" and record.get("returncode") == 0 and
            not record.get("termination", {}).get("forced") and evidence.get("root_exit_confirmed") is True and
            evidence.get("all_owned_members_exit_confirmed") is True and evidence.get("job_empty") is True and
            evidence.get("root", {}).get("handle_source") == "original_subprocess.Popen._handle")


def classify_terminal(record, expected_state, request=None):
    """A completed race is an expected no-stop outcome, not a failed kill."""
    record = record or {}
    state = record.get("state", "unavailable")
    result = {"expected_stop": expected_state, "recorded_state": state, "stop_exercised": False,
              "isolation_gate": "not_proved", "retry": False}
    if state == "completed":
        proved = natural_exit_proved(record)
        result.update(classification="natural_completion_race" if proved else "natural_completion_record_unconfirmed",
                      native_finalization="confirmed_natural_exit" if proved else "unconfirmed",
                      isolation_gate="not_exercised", reason="Native completion won the request/deadline race; no stopped-job claim")
    elif state == expected_state:
        bound = (expected_state != "cancelled" or request is not None and
                 record.get("cancellation", {}).get("request") == request)
        proved = confirmed_stop(record, expected_state) and bound
        result.update(classification="confirmed_owned_stop" if proved else "unconfirmed_stopped_job",
                      stop_exercised=proved, native_finalization="confirmed_owned_member_exits" if proved else "unconfirmed",
                      reason="Positive Job membership at stop and retained member exits required; request/empty PID list alone is insufficient")
    elif state in ("cancelled", "timed_out", "interrupted", "cleanup_failed"):
        result.update(classification="unconfirmed_stopped_job" if state == "cleanup_failed" else "different_stop_reason",
                      native_finalization="unconfirmed", reason="Actual terminal state differs from requested lifecycle experiment")
    elif state == "failed":
        result.update(classification="unexpected_native_or_verification_failure", native_finalization="not_inferred",
                      reason="A native/input/output failure is not a cancellation or timeout race")
    else:
        result.update(classification="nonterminal_or_unavailable", native_finalization="unconfirmed",
                      reason="No terminal observation; a lookup failure is not exit proof")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--expected", choices=("cancelled", "timed_out"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    before = fingerprint(args.run)
    path = args.run / "manifest.json"
    request_path = args.run / "cancel.request.json"
    request = json.loads(request_path.read_text()) if request_path.exists() else None
    result = classify_terminal(json.loads(path.read_text()), args.expected, request)
    require(fingerprint(args.run) == before, "Read-only outcome review changed original run")
    save(out / "verification.json", {"native": "not_requested", "original_run": str(args.run.resolve()),
         "original_manifest_sha256": sha(path), "original_run_unchanged": True, "outcome": result})
    print(json.dumps({"classification": result["classification"], "report": str(out / "verification.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
