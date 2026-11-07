"""Versioned dispatch receipts. Deterministic checks; no tracker or runtime calls.

Evidence is copied by the coordinator into a content-addressed artifact store.
Gate rechecks the copies, not the mutable source files. Legacy data is display
only; interpreting it never claims validation under this protocol.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from research.workflows.graph import bdw

VERSION = 2
ROLES = ("I", "V-Plan", "V-Run", "G", "Contract")
TASK_KINDS = ("code", "documentation", "planning", "verification", "review")
OUTCOMES = ("completed", "failed", "blocked", "cancelled")
REQUIRED_EVIDENCE = {"I": {"implementation", "checks"}, "V-Plan": {"verification_plan"},
                     "V-Run": {"verification", "checks"}, "G": {"review"}, "Contract": {"contract"}}
BINDINGS = ("task_id", "task_code", "dispatch_id", "attempt", "packet_sha256", "base_sha", "role", "task_kind")
FIELDS = set(BINDINGS) | {"schema_version", "outcome", "explanation", "contract_sha", "candidate_sha",
    "verification_plan_sha256", "verdict", "evidence", "checks", "changed_paths", "approval_scope",
    "validation_refs", "extensions"}


class Invalid(bdw.Refused):
    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(f"{reason}: {message}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(raw: str) -> str:
    if not isinstance(raw, str):
        raise Invalid("bad_path", "path must be a string")
    value = raw.replace("\\", "/")
    if (PureWindowsPath(value).drive or PurePosixPath(value).is_absolute()
            or any(p in ("", ".", "..") for p in value.split("/")) or ":" in value):
        raise Invalid("bad_path", f"unsafe relative path {raw!r}")
    return value


def covers(owner: str, path: str) -> bool:
    # Respect the host filesystem convention. Never lowercase POSIX paths.
    owner = os.path.normcase(owner).replace("\\", "/")
    path = os.path.normcase(path).replace("\\", "/")
    return path == owner or path.startswith(owner + "/")


def require_text(obj: dict, key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Invalid("bad_receipt", f"{key} must be a nonempty string")
    return value


def require_hash(value, name: str, length: int = 64):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise Invalid("bad_receipt", f"{name} must be a full lowercase {length}-digit hash")


def validate(receipt: dict, rec: dict) -> None:
    """The single receipt schema; semantic Git/artifact checks are separate."""
    if not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt.get("schema_version") != VERSION:
        raise Invalid("receipt_version", "new collection requires schema_version 2; legacy is display only")
    unknown = set(receipt) - FIELDS
    if unknown:
        raise Invalid("bad_receipt", f"unknown fields {sorted(unknown)}; use extensions for optional annotations")
    if type(receipt.get("attempt")) is not int or receipt["attempt"] < 1:
        raise Invalid("bad_receipt", "attempt must be a positive integer")
    if type(rec.get("attempt")) is not int or rec["attempt"] < 1:
        raise Invalid("attempt_mismatch", "recorded attempt has an invalid type")
    for key in BINDINGS:
        if key != "attempt":
            require_text(receipt, key)
        if receipt.get(key) != rec.get(key):
            raise Invalid("attempt_mismatch", f"{key} does not match the frozen execution context")
    if receipt["role"] not in ROLES or receipt["task_kind"] not in TASK_KINDS:
        raise Invalid("bad_receipt", "unsupported role or task_kind")
    if receipt.get("outcome") not in OUTCOMES:
        raise Invalid("bad_receipt", f"outcome must be one of {OUTCOMES}; put narrative in explanation")
    require_text(receipt, "explanation")
    for key in ("base_sha", "contract_sha", "candidate_sha"):
        if key in receipt or key != "candidate_sha" or receipt["role"] in ("I", "V-Run", "G"):
            require_hash(receipt.get(key), key, 40)
    require_hash(receipt.get("packet_sha256"), "packet_sha256")
    for key in ("contract_sha", "candidate_sha", "verification_plan_sha256"):
        if rec.get(key) is not None and receipt.get(key) != rec[key]:
            raise Invalid("target_mismatch", f"{key} differs from this task's frozen target")
    if receipt["role"] in ("V-Plan", "V-Run") or (receipt["role"] == "G" and receipt["task_kind"] == "code"):
        require_hash(receipt.get("verification_plan_sha256"), "verification_plan_sha256")
    elif "verification_plan_sha256" in receipt:
        require_hash(receipt["verification_plan_sha256"], "verification_plan_sha256")
    if receipt["role"] in ("V-Run", "G") or "verdict" in receipt:
        if not isinstance(receipt.get("verdict"), str) or receipt["verdict"] not in ("PASS", "REJECT"):
            raise Invalid("bad_verdict", "verdict must be PASS or REJECT")
    if "extensions" in receipt and not isinstance(receipt["extensions"], dict):
        raise Invalid("bad_receipt", "extensions must be an object")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise Invalid("missing_evidence", "evidence must be a nonempty list of typed artifact references")
    ids, kinds = set(), set()
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"artifact_id", "path", "sha256", "kind", "source"}:
            raise Invalid("bad_evidence", "evidence needs artifact_id, relative path, sha256, kind and source")
        for key in ("artifact_id", "source", "kind"):
            require_text(item, key)
        if item["artifact_id"] in ids:
            raise Invalid("bad_evidence", "duplicate artifact_id")
        ids.add(item["artifact_id"])
        relative_path(item["path"])
        require_hash(item["sha256"], "evidence.sha256")
        if item["kind"] not in set().union(*REQUIRED_EVIDENCE.values()):
            raise Invalid("bad_evidence", "unsupported artifact kind")
        source = item["source"]
        if source != f"dispatch:{rec['dispatch_id']}":
            parts = source.split(":", 2)
            if len(parts) != 3 or parts[0] != "git" or parts[1] not in (receipt["contract_sha"], receipt.get("candidate_sha")):
                raise Invalid("bad_evidence", "source must identify this dispatch or git:<target-commit>:<repo-path>")
            relative_path(parts[2])
        kinds.add(item["kind"])
    if not REQUIRED_EVIDENCE[receipt["role"]] <= kinds:
        raise Invalid("missing_evidence", f"{receipt['role']} requires {sorted(REQUIRED_EVIDENCE[receipt['role']])}")
    if receipt["role"] == "V-Plan" and not any(e["kind"] == "verification_plan" and
            e["sha256"] == receipt["verification_plan_sha256"] for e in evidence):
        raise Invalid("target_mismatch", "verification plan digest must identify the frozen plan artifact")
    if receipt["role"] in ("I", "V-Run") or "checks" in receipt:
        checks = receipt.get("checks")
        if not isinstance(checks, list) or not checks:
            raise Invalid("bad_receipt", "checks must be nonempty")
        for check in checks:
            if not isinstance(check, dict) or set(check) != {"command", "result"}:
                raise Invalid("bad_receipt", "each check needs command and result")
            require_text(check, "command")
            if check["result"] not in ("pass", "fail", "skip"):
                raise Invalid("bad_receipt", "check result must be pass, fail or skip")
        if successful(receipt) and not any(c["result"] == "pass" for c in checks):
            raise Invalid("bad_receipt", "successful I/V-Run must include a passing check")
        if successful(receipt) and any(c["result"] == "fail" for c in checks):
            raise Invalid("bad_receipt", "successful receipt includes a failed required check")
    if receipt["role"] == "I" or "changed_paths" in receipt:
        changed = receipt.get("changed_paths")
        if not isinstance(changed, list) or not all(isinstance(p, str) for p in changed):
            raise Invalid("bad_receipt", "I must declare changed_paths (checked against Git)")
        for path in changed:
            relative_path(path)
    if receipt["role"] == "G" or "approval_scope" in receipt or "validation_refs" in receipt:
        require_text(receipt, "approval_scope")
        refs = receipt.get("validation_refs")
        if not isinstance(refs, list) or not refs:
            raise Invalid("bad_receipt", "G needs explicit validation_refs")
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"task_id", "dispatch_id", "receipt_sha256"}:
                raise Invalid("bad_receipt", "validation_refs need task_id, dispatch_id and receipt_sha256")
            require_text(ref, "task_id")
            require_text(ref, "dispatch_id")
            require_hash(ref["receipt_sha256"], "receipt_sha256")


def successful(receipt: dict) -> bool:
    return receipt.get("outcome") == "completed" and receipt.get("verdict", "PASS") == "PASS"


def legacy_interpretation(receipt: dict) -> dict:
    """Do not edit the input, infer missing identities, or grant a new gate."""
    verdict = receipt.get("verdict")
    outcome = receipt.get("outcome")
    known = {"completed": "completed", "failed": "failed", "failure": "failed", "rejected": "failed",
             "blocked": "blocked", "cancelled": "cancelled",
             "planning_and_wiring_complete_expected_base_failure_native_unrun": "completed"}
    return {"schema": "legacy", "new_gate_eligible": False,
            "verdict": verdict.upper() if isinstance(verdict, str) and verdict.upper() in ("PASS", "REJECT") else None,
            "outcome": known.get(outcome.lower()) if isinstance(outcome, str) else None,
            "explanation": outcome, "raw": receipt}


def archive(root: Path, data: bytes, name: str) -> dict:
    """Exclusive creation; identical content is idempotent. Existing corruption fails closed."""
    sha = digest(data)
    rel = f"{sha}/{name}"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if target.read_bytes() != data:
            raise Invalid("artifact_corrupt", f"immutable artifact {target} differs")
    return {"artifact_id": f"sha256:{sha}", "path": rel, "sha256": sha}


def read_artifact(root: Path, item: dict) -> bytes:
    path = (root / relative_path(item["path"])).resolve()
    if root.resolve() not in path.parents:
        raise Invalid("bad_evidence", "artifact escapes root")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Invalid("missing_evidence", f"artifact unavailable: {item.get('artifact_id')}") from exc
    if digest(data) != item.get("sha256"):
        raise Invalid("artifact_corrupt", f"hash mismatch: {item.get('artifact_id')}")
    return data
