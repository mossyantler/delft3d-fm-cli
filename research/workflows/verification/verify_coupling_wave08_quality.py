"""Passive08 SWAN convergence gate; preserve warnings and numerical limits.

D-Waves2026.02 sec4.9 printed29/PDF39 and sec5.4.8 printed59/PDF69
recommend40 rather than tutorial15 iterations. No accuracy threshold is lowered.
Passing a solver stopping criterion is not scientific validation.
"""
from pathlib import Path
import re

from .verify_coupling_sources import fingerprint, ini, require, scalar


def inspect_quality(run, *, expected_iterations=40):
    run = Path(run)
    path = run / "model/dwaves/swn-diag.f34"
    text = path.read_text(errors="replace")
    settings = ini(run / "model/dwaves/f34.mdw")
    require(int(scalar(settings, "Numerics", "MaxIter")) == expected_iterations and
            float(scalar(settings, "Numerics", "PercWet")) == 98, "Frozen convergence controls differ")
    parts = [part for part in text.split("Execution started at") if "accuracy OK" in part]
    require(len(parts) == 2, "Expected separate SWAN diagnostics for both actual0/3600 solves")
    solves = []
    for seconds, part in zip((0, 3600), parts):
        rows = re.findall(r"accuracy OK in\s+([\d.]+) % of wet grid points \(\s*([\d.]+) % required\)", part)
        actual, required = map(float, rows[-1])
        iterations = re.findall(r"iteration\s+(\d+);\s*sweep", part)
        require(iterations and required == 98, "Missing iteration count or changed native accuracy target")
        trace = [{"iteration": int(iteration), "wet_points_percent": float(value), "required_percent": float(target)}
                 for iteration, value, target in re.findall(r"iteration\s+(\d+);\s*sweep[^;]*?accuracy OK in\s+([\d.]+) % of wet grid points \(\s*([\d.]+) % required\)", part, re.S)]
        require(len(trace) == len(rows) and all(row["required_percent"] == 98 for row in trace), "Incomplete iteration trace or lowered target")
        tail = [r["wet_points_percent"] for r in trace[-20:]]
        solves.append({"seconds": seconds, "last_iteration": int(iterations[-1]), "last_wet_points_percent": actual,
                       "required_percent": required, "met_declared_target": actual >= required,
                       "trace": trace, "last20_wet_points_min_percent": min(tail), "last20_wet_points_max_percent": max(tail),
                       "last20_net_change_percentage_points": tail[-1] - tail[0]})
    lines = text.splitlines()
    warnings = [{"line": i + 1, "context": lines[i:i + 10]} for i, line in enumerate(lines) if re.search(r"\*\*\s*WARNING", line, re.I)]
    errors = [{"line": i + 1, "text": line} for i, line in enumerate(lines) if re.match(r"\s*\*\*\s*(Error|Severe)", line, re.I)]
    return {"state": "passed" if not errors and all(s["met_declared_target"] for s in solves) else "failed",
            "path": str(path.resolve()), "sha256": fingerprint(path), "max_iterations": expected_iterations,
            "solves": solves, "warnings": warnings, "errors": errors,
            "scientific_validation": "not_performed", "scope": "Only native declared98% iteration criterion; boundary warnings retained, no claim of grid/forcing/calibration correctness"}
