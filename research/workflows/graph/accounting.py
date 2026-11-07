"""Offline comparison of accepted-task cost, without model calls or invented prices.

Input: metrics records with dispatch_id/session_id, role, outcome, interval_tokens,
session_usage, cost (null allowed), accepted_task, cohort and benchmark_case.
Use interval deltas once per dispatch. Session totals are diagnostic maxima only.
Both successful and failed attempts belong to accepted_task's total.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def summarize(records: list[dict]) -> dict:
    unique, sessions = {}, {}
    for record in records:
        identity = record["dispatch_id"]
        # A later collection for the same dispatch supersedes its earlier sample.
        unique[identity] = record
        usage = record.get("session_usage")
        if usage and record.get("session_id"):
            key = f"{record.get('kind')}:{record['session_id']}"
            previous = sessions.setdefault(key, {})
            for name, value in usage.get("tokens", {}).items():
                previous[name] = max(previous.get(name, 0), value)
    groups = {}
    overlaps = set()
    by_session = {}
    for record in unique.values():
        if record.get("session_id"):
            by_session.setdefault((record.get("kind"), record["session_id"]), []).append(record)
    for records_in_session in by_session.values():
        for index, left in enumerate(records_in_session):
            for right in records_in_session[index + 1:]:
                ls, le = left.get("interval_start"), left.get("interval_end")
                rs, re = right.get("interval_start"), right.get("interval_end")
                if not all(isinstance(v, dict) for v in (ls, le, rs, re)):
                    overlaps.update((left["dispatch_id"], right["dispatch_id"]))
                    continue
                common = set(ls) & set(le) & set(rs) & set(re)
                if not common or any(max(ls[k], rs[k]) < min(le[k], re[k]) for k in common):
                    overlaps.update((left["dispatch_id"], right["dispatch_id"]))
    for record in unique.values():
        key = json.dumps([record.get("cohort"), record.get("benchmark_case"), record.get("accepted_task")])
        group = groups.setdefault(key, {"cohort": record.get("cohort"), "benchmark_case": record.get("benchmark_case"),
            "accepted_task": record.get("accepted_task"), "attempts": 0, "failed_attempts": 0,
            "unknown_outcome_attempts": 0, "verification_attempts": 0, "measured_tokens": {}, "provider_tokens": {},
            "role_totals": {}, "unknown_usage_attempts": 0,
            "cost": 0, "currency": None, "mixed_currency": False, "unknown_cost_attempts": 0})
        group["attempts"] += 1
        group["failed_attempts"] += record.get("outcome") in ("failed", "blocked", "cancelled") or record.get("verdict") == "REJECT"
        group["unknown_outcome_attempts"] += record.get("outcome") not in ("completed", "failed", "blocked", "cancelled")
        group["verification_attempts"] += record.get("role") in ("V-Plan", "V-Run")
        raw_tokens = record.get("interval_tokens")
        tokens = record.get("normalized_interval_tokens")
        if tokens is None and raw_tokens is not None:
            tokens = {k: v for k, v in raw_tokens.items() if k != "input_tokens"}
            if record.get("kind") == "claude" and "input_tokens" in raw_tokens:
                tokens["uncached_input_tokens"] = raw_tokens["input_tokens"]
            elif all(k in raw_tokens for k in ("input_tokens", "cached_input_tokens")):
                tokens["uncached_input_tokens"] = raw_tokens["input_tokens"] - raw_tokens["cached_input_tokens"]
        if record["dispatch_id"] in overlaps:
            # Neither the task nor its role gets an ambiguous overlapping slice.
            # Session maxima remain diagnostic, not another amount to sum.
            tokens, raw_tokens = None, None
        if raw_tokens is not None:
            provider = group["provider_tokens"].setdefault(record.get("kind", "unknown"), {})
            for name, value in raw_tokens.items():
                provider[name] = provider.get(name, 0) + value
        if tokens is None:
            group["unknown_usage_attempts"] += 1
        else:
            for name, value in tokens.items():
                group["measured_tokens"][name] = group["measured_tokens"].get(name, 0) + value
        cost = record.get("cost")
        currency = record.get("currency")
        if (record.get("cost_scope") != "dispatch_interval" or not isinstance(currency, str) or not currency
                or not isinstance(cost, (int, float)) or isinstance(cost, bool) or not math.isfinite(cost) or cost < 0):
            cost = None
        if cost is not None:
            if group["currency"] is not None and group["currency"] != currency:
                group["mixed_currency"] = True
            group["currency"] = currency
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            group["unknown_cost_attempts"] += 1
        else:
            group["cost"] += cost
        role = group["role_totals"].setdefault(record.get("role") or "unknown", {"attempts": 0, "measured_tokens": {},
            "unknown_usage_attempts": 0, "cost": 0, "unknown_cost_attempts": 0})
        role["attempts"] += 1
        if tokens is None:
            role["unknown_usage_attempts"] += 1
        else:
            for name, value in tokens.items():
                role["measured_tokens"][name] = role["measured_tokens"].get(name, 0) + value
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            role["unknown_cost_attempts"] += 1
        else:
            role["cost"] += cost
    for group in groups.values():
        group["total_tokens"] = None if group["unknown_usage_attempts"] else group["measured_tokens"]
        if group["unknown_cost_attempts"] or group["mixed_currency"]:
            group["cost"] = None
        for role in group["role_totals"].values():
            role["total_tokens"] = None if role["unknown_usage_attempts"] else role["measured_tokens"]
            if role["unknown_cost_attempts"] or group["mixed_currency"]:
                role["cost"] = None
    return {"groups": list(groups.values()), "session_cumulative_diagnostics": sessions,
            "overlapping_or_unbounded_dispatches": sorted(overlaps),
            "savings_claim": None, "note": "Compare matching benchmark_case and measured cohorts; no model calls made"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", type=Path, help="JSON array of metrics records")
    args = parser.parse_args(argv)
    source = json.loads(args.metrics.read_text(encoding="utf-8"))
    result = summarize(source["records"] if isinstance(source, dict) else source)
    if isinstance(source, dict):
        result["legacy_metrics"] = source.get("legacy_metrics", [])
        result["legacy_usage_unquantified"] = bool(result["legacy_metrics"])
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
