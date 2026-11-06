"""Apply a GRAPH-OPS seed spec to the shared Beads workspace, or report the graph.

    $env:DFM_BD_ROLE = "coordinator"
    python -m research.workflows.graph.seed apply research/workflows/graph/seed-20261106.json --receipt <out.json>
    python -m research.workflows.graph.seed report          # Markdown snapshot from Beads (any role)

``apply`` refuses a workspace that already holds issues, so it runs once. All
access goes through bdw. ``apply`` checks the ready set against the spec's
``expected_ready`` and runs graph integrity checks before reporting success.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def bdw(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run([sys.executable, "-m", "research.workflows.graph.bdw", *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and p.returncode:
        raise SystemExit(f"bdw {args} failed ({p.returncode}): {p.stderr.strip() or p.stdout.strip()}")
    return p


def bdw_json(args: list[str]):
    out = bdw([*args, "--json"]).stdout
    return json.loads(out) if out.strip() else []


def code_of(issue: dict) -> str | None:
    meta = issue.get("metadata")
    meta = json.loads(meta) if isinstance(meta, str) and meta else (meta or {})
    return meta.get("task_code")


def ready_codes() -> list[str]:
    return sorted(c for c in (code_of(i) for i in bdw_json(["ready", "--exclude-type", "epic", "-n", "0"])) if c)


def apply(spec_path: Path, receipt_path: Path) -> int:
    if os.environ.get("DFM_BD_ROLE") != "coordinator":
        raise SystemExit("apply requires DFM_BD_ROLE=coordinator")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if bdw_json(["list", "--all"]):
        raise SystemExit("workspace already holds issues; apply runs once")
    ids: dict[str, str] = {}

    def create(title: str, code: str, extra: list[str], meta: dict) -> str:
        p = bdw(["create", title, "--silent", "--metadata", json.dumps({"task_code": code, **meta}, ensure_ascii=False),
                 *extra])
        ids[code] = p.stdout.strip().splitlines()[-1]
        return ids[code]

    tasks = []
    for epic in spec["epics"]:
        eid = create(epic["title"], epic["code"], ["-t", "epic"], {})
        for t in epic["tasks"]:
            labels = [f"role:{t['role']}"] + (["needs-lease"] if t.get("lease") else [])
            desc = "\n".join([f"Code: {t['code']}", *(f"Evidence: {e}" for e in t.get("evidence", [])),
                              *(["Native run: needs the coordinator's exclusive lease and plan/package/reader review."]
                                if t.get("lease") else [])])
            create(f"{t['code']}: {t['title']}", t["code"], ["--parent", eid, "-l", ",".join(labels), "-d", desc],
                   {"evidence": t.get("evidence", []), "lease": bool(t.get("lease"))})
            tasks.append(t)
    for t in tasks:
        for dep in t.get("deps", []):
            bdw(["dep", "add", ids[t["code"]], ids[dep]])
    for t in tasks:
        if t["status"] == "closed":
            bdw(["close", ids[t["code"]], "--reason", "accepted before cutover: " + "; ".join(t.get("evidence", []))])
    for epic in spec["epics"]:
        if epic["status"] == "closed":
            bdw(["close", ids[epic["code"]], "--reason", "all tasks accepted before cutover"])
    got = ready_codes()
    want = sorted(spec["expected_ready"])
    cycles = bdw(["dep", "cycles", "--json"], check=False)
    graph = bdw(["graph", "check"], check=False)
    receipt = {"spec": str(spec_path), "ids": ids, "ready": got, "expected_ready": want,
               "ready_matches": got == want, "dep_cycles": cycles.stdout.strip(), "graph_check_exit": graph.returncode,
               "graph_check": (graph.stdout + graph.stderr).strip()}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = got == want and graph.returncode == 0 and cycles.returncode == 0
    print(json.dumps({"ok": ok, "ready": got, "missing": sorted(set(want) - set(got)),
                      "unexpected": sorted(set(got) - set(want)), "receipt": str(receipt_path)}, ensure_ascii=False))
    return 0 if ok else 1


def report() -> int:
    issues = bdw_json(["list", "--all", "-n", "0"])
    ready = set(ready_codes())
    by_parent: dict[str, list[dict]] = {}
    epics = [i for i in issues if i.get("issue_type") == "epic"]
    for i in issues:
        if i.get("parent"):
            by_parent.setdefault(i["parent"], []).append(i)
    lines = ["| Epic | Task | 상태 | Beads ID |", "| --- | --- | --- | --- |"]
    for e in sorted(epics, key=lambda x: x["title"]):
        for t in sorted(by_parent.get(e["id"], []), key=lambda x: x["id"]):
            code = code_of(t) or t["title"]
            state = "Ready" if code in ready else ("✓" if t["status"] == "closed" else
                                                   "Blocked" if t["status"] == "open" else t["status"])
            lease = " (임대)" if "needs-lease" in (t.get("labels") or []) else ""
            lines.append(f"| {code_of(e) or e['title']} | {t['title']}{lease} | {state} | `{t['id']}` |")
    print("\n".join(lines))
    return 0


def main() -> int:
    a = sys.argv[1:]
    if a[:1] == ["apply"] and len(a) == 4 and a[2] == "--receipt":
        return apply(Path(a[1]), Path(a[3]))
    if a == ["report"]:
        return report()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
