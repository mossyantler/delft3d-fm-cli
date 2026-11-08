"""Read the JSON-compatible YAML policy in INTENT §6.8 (the only policy SSOT).

Runtime proofs are observations, never model policy or user approvals. The
coordinator records an exact installed-runtime probe; unknown settings refuse
dispatch. This is an operational control, not a security boundary.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from research.workflows.graph.protocol import Invalid, digest

FAILURE_CAUSES = ("implementation", "contract", "ownership", "verification", "native_uncertainty",
                  "session", "environment", "cli", "path", "permission", "approval", "revision")
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max", "ultra")  # ordering, not policy limits


def load(path: Path) -> dict:
    match = re.search(r"```yaml\s*\n(\{.*?\})\s*\n```", path.read_text(encoding="utf-8"), re.S)
    if not match:
        raise Invalid("model_policy", "INTENT §6.8 must contain JSON-compatible YAML")
    return json.loads(match[1])["model_policy"]


def check(policy: dict, proof_path: Path, *, kind: str, model: str, effort: str,
          task_id: str, task_class: str, approval: dict | None, attempts: list[dict],
          failure_cause: str | None) -> dict:
    try:
        raw = proof_path.read_bytes()
        proof = json.loads(raw)
        if not isinstance(proof, dict) or not isinstance(proof.get("expires_at"), str):
            raise ValueError("runtime proof must be an object with a textual expires_at")
        key = proof["model_key"]
        spec = policy["models"][key]
        named_keys = {k for k in policy["models"] if k in model.lower().replace("_", "-").split("-")}
        if named_keys and named_keys != {key}:
            raise ValueError("runtime proof misclassifies the model family")
        expires = datetime.fromisoformat(proof["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise ValueError("expired runtime observation")
        required = ("runner", "runner_version", "billing_mode", "auth_mode", "probe_ref")
        if not all(isinstance(proof.get(k), str) and proof[k].strip() and proof[k] != "unknown" for k in required):
            raise ValueError("runtime, billing/auth or probe evidence unknown")
        if (not isinstance(proof.get("supported_efforts"), list)
                or not isinstance(proof.get("task_classes_evaluated"), list)
                or proof.get("kind") != kind or proof.get("model_id") != model
                or proof.get("availability_verified") is not True
                or effort not in proof.get("supported_efforts", [])
                or proof.get("task_classes_evaluated") is None):
            raise ValueError("model/effort availability is not verified")
        if kind == "codex" and proof.get("prompt_delivery") not in ("interactive", "startup_argument"):
            raise ValueError("Codex runtime proof must verify interactive or startup_argument prompt delivery")
        # A logical model without a configured ID needs the exact runtime proof.
        if spec.get("model_id") is not None and spec["model_id"] != model:
            raise ValueError("runtime proof differs from policy model_id")
        if spec.get("model_id") is not None and spec.get("availability_verified") is not True:
            raise ValueError("configured model is marked unavailable in policy")
        if spec["provider"] != {"claude": "anthropic", "codex": "openai"}.get(kind):
            raise ValueError("provider does not match runtime")
        pool = policy["candidate_pools"][task_class]
        transitional = spec["class"] in ("general", "premium", "exceptional")
        exceptional_route = spec["class"] == "exceptional" and task_class == "approved_deep_review"
        if not transitional or (key not in pool and not exceptional_route):
            raise ValueError("model not in task pool (Phases 3–4 allow general/approved premium only)")
        if effort not in EFFORT_LEVELS:
            raise ValueError("unrecognized effort")
        limits = [policy["effort_policy"]["automatic_max_effort"],
                  policy["effort_policy"].get("hard_limits", {}).get(key), spec.get("hard_max_effort")]
        if any(limit and EFFORT_LEVELS.index(effort) > EFFORT_LEVELS.index(limit) for limit in limits):
            raise ValueError("policy effort limit exceeded")
        if "policy_allowed_efforts" in spec and effort not in spec["policy_allowed_efforts"]:
            raise ValueError("model hard effort limit")
        # New trials cannot silently sweep models or exceed two repairs per cause.
        if failure_cause is not None and failure_cause not in FAILURE_CAUSES:
            raise ValueError("unrecognized failure cause")
        if attempts and not failure_cause:
            raise ValueError("retry requires a classified failure_cause")
        same_cause = [a for a in attempts if a.get("failure_cause") == failure_cause]
        if len(same_cause) >= policy["routing"]["max_repairs_after_initial_attempt"]:
            raise ValueError("repair limit reached for this cause")
        if attempts and attempts[-1].get("model") != model:
            if failure_cause in ("environment", "cli", "path", "permission", "approval"):
                raise ValueError("environment failures cannot trigger a model switch")
            if not proof.get("switch_rationale"):
                raise ValueError("model switch needs a reproducible failure and rationale")
        restricted = spec["class"] in ("premium", "exceptional")
        if not restricted and task_class not in proof["task_classes_evaluated"]:
            # General pools are an explicit transitional exception to §6.7 evaluation.
            if not proof.get("transitional_general_pool"):
                raise ValueError("task class evaluation missing")
        if restricted:
            if not isinstance(approval, dict) or approval.get("status") != "closed":
                raise ValueError("no approved user decision")
            meta = approval.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta)
            grant = meta.get("model_approval")
            if (not isinstance(grant, dict) or grant.get("status") != "approved"
                    or any(not isinstance(grant.get(k), list) or not all(isinstance(x, str) for x in grant[k])
                           for k in ("task_ids", "efforts", "task_classes"))
                    or grant.get("model_id") != model or task_id not in grant.get("task_ids", [])
                    or effort not in grant.get("efforts", []) or task_class not in grant.get("task_classes", [])
                    or any(not isinstance(grant.get(k), str) or not grant[k].strip()
                           for k in ("question", "input_scope", "verification_method", "prior_limits"))):
                raise ValueError("approval does not cover this task/model/effort/scope")
            if grant.get("expires_at") is not None:
                if not isinstance(grant["expires_at"], str):
                    raise ValueError("approval expires_at must be textual")
                expiry = datetime.fromisoformat(grant["expires_at"].replace("Z", "+00:00"))
                if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                    raise ValueError("approval expired")
            if spec["class"] == "exceptional" and grant.get("separate_exceptional_approval") is not True:
                raise ValueError("Fable requires separate exceptional approval")
            max_calls, budget = grant.get("max_calls"), grant.get("usage_budget")
            if type(max_calls) is not int or max_calls < 1 or not isinstance(budget, dict):
                raise ValueError("approval needs call and usage limits")
            if any((a.get("policy") or {}).get("model_key") in policy["premium_policy"]["models"]
                   and (a.get("policy") or {}).get("model_key") != key for a in attempts):
                raise ValueError("sequential premium escalation is prohibited")
        return {"proof": proof, "proof_sha256": digest(raw), "model_key": key,
                "approval_id": approval.get("id") if approval else None}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Invalid("model_policy", str(exc)) from exc
