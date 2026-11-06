"""Independent GRAPH-OPS-BACKUP-V contract checks; writes only below this file.

Run: python -B verify_backup.py --candidate <frozen worktree> --bd <bd.exe>
                              --out <fresh child of this owned folder>
Cases were fixed in plan.json before reading candidate or author tests.
No external network, native runs, real graph access, or candidate modifications.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SHA = "040fc9f"
FULL_SHA = "040fc9f594eaf681d90dce368d92505a7965ee36"
FROZEN_HASH = "0e5894a55b0e2eff597d838b53cd6f88fc8d13d9a1bf1de5fe19c9c1e8487914"
BD_HASH = "ac5b60114e5e7ef9de8878b45fc35941937341d3447366c99bc91c81557be7a4"
REL = Path("research/notes/delivery/beads-state.jsonl")
FIELDS = ("id", "title", "status", "issue_type", "labels", "metadata", "close_reason", "description")


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Verify:
    def __init__(self, candidate, bd, out):
        self.candidate, self.bd, self.out = candidate, bd, out
        self.owned = Path(__file__).resolve().parent
        self.calls, self.cases, self.defects = [], [], []
        for name in ("temp", "profile", "safe-backup", "logs"):
            (out / name).mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("BD_", "BEADS_", "DFM_BD", "DFM_BEADS", "GIT_", "DOLT_", "OneDrive"))}
        self.env.update({"PYTHONPATH": str(candidate), "PYTHONDONTWRITEBYTECODE": "1",
                         "DFM_BD_EXE": str(bd), "DFM_BEADS_BACKUP": str(out / "safe-backup"),
                         "OneDrive": str(out / "fake-onedrive"),
                         "BEADS_DIR": str(out / "unused-db/.beads"),
                         "BD_DISABLE_METRICS": "1", "BD_NO_INSTALL_HOOKS": "1",
                         "BD_NO_REMOTE_ADOPT": "1", "BD_NON_INTERACTIVE": "1",
                         "NO_COLOR": "1", "GIT_CONFIG_NOSYSTEM": "1",
                         "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                         "GIT_OPTIONAL_LOCKS": "0", "GIT_CEILING_DIRECTORIES": str(out),
                         "USERPROFILE": str(out / "profile"),
                         "APPDATA": str(out / "profile/roaming"),
                         "LOCALAPPDATA": str(out / "profile/local"),
                         "XDG_CONFIG_HOME": str(out / "profile/config"),
                         "XDG_CACHE_HOME": str(out / "profile/cache"),
                         "TEMP": str(out / "temp"), "TMP": str(out / "temp")})
        self.report = {"task_code": "GRAPH-OPS-BACKUP-V", "candidate_sha": SHA,
                       "candidate_full_sha": FULL_SHA, "verdict": "fail",
                       "verifier_sha256": digest(__file__), "bd_sha256": digest(bd),
                       "cases": self.cases, "defects": self.defects,
                       "regression_64": "pending", "experiment_id": self.owned.name,
                       "evidence_kind": "observed behavior; source references are static analysis",
                       "calls": "calls.json", "plan": "../plan.json"}
        self.flush()

    def flush(self):
        (self.out / "calls.json").write_text(json.dumps(self.calls, ensure_ascii=False, indent=2), encoding="utf-8")
        text = json.dumps(self.report, ensure_ascii=False, indent=2) + "\n"
        (self.out / "verification.json").write_text(text, encoding="utf-8")
        # Packet requests an immediately discoverable receipt in the owned root.
        (self.owned / "verification.json").write_text(text, encoding="utf-8")

    def run(self, argv, cwd, overrides=None, timeout=120):
        cwd = Path(cwd).resolve()
        env = dict(self.env)
        for k, v in (overrides or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = str(v)
        assert Path(env["DFM_BEADS_BACKUP"]).resolve().is_relative_to(self.owned)
        assert cwd.is_relative_to(self.out) or (cwd == self.candidate and argv[0] == "git")
        if env.get("BEADS_DIR"):
            assert Path(env["BEADS_DIR"]).resolve().is_relative_to(self.out)
        start = time.monotonic()
        p = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        r = {"id": len(self.calls), "argv": list(map(str, argv)), "cwd": str(cwd),
             "environment_overrides": overrides or {}, "DFM_BEADS_BACKUP": env["DFM_BEADS_BACKUP"],
             "exit": p.returncode, "stdout": p.stdout, "stderr": p.stderr,
             "seconds": round(time.monotonic() - start, 3)}
        self.calls.append(r)
        (self.out / "logs" / f"{r['id']:04d}.txt").write_text(p.stdout + p.stderr, encoding="utf-8")
        self.flush()
        return r

    @staticmethod
    def ok(r):
        if r["exit"]:
            raise RuntimeError(f"call {r['id']} failed: {r}")
        return r["stdout"].strip()

    def git(self, cwd, *args):
        return self.ok(self.run(["git", "-c", "user.name=Independent backup verifier", "-c",
                                 "user.email=verifier@example.invalid", *args], cwd))

    def fixture(self, name, worktree=False):
        base = self.out / name
        base.mkdir()
        repo, origin = base / "project", base / "origin.git"
        self.git(base, "init", "--bare", "-q", "-b", "main", str(origin))
        self.git(base, "init", "-q", "-b", "main", str(repo))
        (repo / "README.md").write_bytes(b"owned throwaway baseline\n")
        (repo / "tracked.txt").write_bytes(b"tracked baseline\n")
        self.git(repo, "add", "README.md", "tracked.txt")
        self.git(repo, "commit", "-q", "-m", "owned verification fixture")
        self.git(repo, "remote", "add", "origin", str(origin))
        self.git(base, "--git-dir", str(origin), "fetch", "-q", str(repo), "main:main")
        head = self.git(repo, "rev-parse", "HEAD")
        # Nonempty local origin refs catch accidental deletion as well as creation.
        self.git(base, "--git-dir", str(origin), "update-ref", "refs/dolt/verifier-sentinel", head)
        (repo / ".git/hooks/pre-commit").write_bytes(b"#!/bin/sh\n# sentinel\nexit 0\n")
        if worktree:
            wt = base / "linked"
            self.git(repo, "worktree", "add", "-q", "--detach", str(wt))
            return repo, wt
        return repo

    def shared(self, repo):
        common = Path(self.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        assert common.name == ".git" and common.is_relative_to(self.out)
        path = common.parent.parent / (common.parent.name + "-beads") / ".beads"
        assert path.is_relative_to(self.out)
        return path

    def wrapper(self, cwd, args, role="coordinator", extra=None):
        self.shared(cwd)  # An independently created .git is mandatory.
        return self.run([sys.executable, "-B", "-m", "research.workflows.graph.bdw", *args], cwd,
                        {"DFM_BD_ROLE": role, "BEADS_DIR": None, **(extra or {})})

    def direct(self, cwd, db, *args):
        assert Path(db).resolve().is_relative_to(self.out)
        return self.run([self.bd, "--sandbox", *args], cwd, {"BEADS_DIR": str(db)})

    def case(self, contract, name, expected, passed, observed, polarity="positive", calls=()):
        self.cases.append({"contract": contract, "name": name, "polarity": polarity,
                           "expected": expected, "observed": observed, "pass": bool(passed),
                           "call_ids": [r["id"] for r in calls]})
        print(f"{'PASS' if passed else 'FAIL'} C{contract}: {name}", flush=True)
        if not passed:
            self.defects.append({"id": f"BACKUP-V-{len(self.defects)+1:03d}", "contract": contract,
                                 "summary": name, "expected": expected, "observed": observed,
                                 "evidence_call_ids": [r["id"] for r in calls],
                                 "reproducing_commands": [self.repro(r) for r in calls],
                                 "full_reproduction": self.full_repro(),
                                 "candidate_source": f"{SHA}:research/workflows/graph/bdw.py:263-329"})
        self.flush()

    def full_repro(self):
        return {"argv": [sys.executable, "-B", str(Path(__file__).resolve()), "--candidate", str(self.candidate),
                         "--bd", str(self.bd), "--out", str(self.owned / "reproduce-fresh")],
                "cwd": str(self.owned), "note": "Choose an unused output child; all environment safety settings are installed by verifier."}

    def repro(self, r):
        return {k: r[k] for k in ("argv", "cwd", "environment_overrides", "DFM_BEADS_BACKUP")}

    def snapshot(self, repo, wt=None):
        # Refresh before hashing; GIT_OPTIONAL_LOCKS=0 prevents read-time refresh writes.
        self.git(repo, "status", "--porcelain=v1", "-uall")
        origin = self.git(repo, "remote", "get-url", "origin")
        filemap = lambda root: {p.relative_to(root).as_posix(): digest(p) for p in root.rglob("*")
                                if p.is_file() and ".git" not in p.relative_to(root).parts}
        return {"head": self.git(repo, "rev-parse", "HEAD"),
                "index": digest(repo / ".git/index"), "config": digest(repo / ".git/config"),
                "hooks": {p.relative_to(repo / ".git/hooks").as_posix(): digest(p)
                          for p in (repo / ".git/hooks").rglob("*") if p.is_file()},
                "origin_refs": self.git(repo, "--git-dir", origin, "for-each-ref", "--format=%(refname) %(objectname)"),
                "files": filemap(repo), "linked_files": filemap(wt) if wt else {},
                "linked_index": digest(Path(self.git(wt, "rev-parse", "--path-format=absolute", "--git-path", "index"))) if wt else None,
                "linked_head": self.git(wt, "rev-parse", "HEAD") if wt else None}

    def save(self, name, value):
        (self.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def seed(self, repo):
        # Seed via public allowed commands, including closed records and two dependency kinds.
        ids = {}
        specs = [("epic", "epic", "Open epic"), ("ready", "task", "Ready task 한글"),
                 ("blocked", "bug", "Blocked bug"), ("active", "feature", "In-progress feature"),
                 ("closed", "chore", "Closed chore")]
        for key, typ, title in specs:
            metadata = json.dumps({"suite": "independent", "key": key, "nested": {"n": 3, "ok": True},
                                   "items": ["α", "β"]}, ensure_ascii=False)
            description = f"Contract fixture {key}\nSecond line 한글 α\nJSON-looking {{\"x\":1}}"
            r = self.wrapper(repo, ["create", title, "--type", typ, "--labels", "verify,backup",
                                    "--metadata", metadata, "--description", description, "--silent"])
            ids[key] = self.ok(r).splitlines()[-1]
        self.ok(self.wrapper(repo, ["update", ids["active"], "--status", "in_progress"]))
        self.ok(self.wrapper(repo, ["close", ids["closed"], "--reason", "Verified closure 한글\nsecond reason line"]))
        self.ok(self.wrapper(repo, ["dep", "add", ids["blocked"], ids["ready"]]))
        self.ok(self.wrapper(repo, ["dep", "add", ids["active"], ids["epic"], "--type", "parent-child"]))
        self.save("seed-ids.json", ids)
        return ids

    def semantics(self, repo, db):
        # Direct bd with BEADS_DIR, as required; no wrapper restore shortcuts.
        rows = json.loads(self.ok(self.direct(repo, db, "list", "--all", "--limit", "0", "--json")))
        issues = {}
        for row in rows:
            item = json.loads(self.ok(self.direct(repo, db, "show", row["id"], "--json")))
            if isinstance(item, list):
                item = item[0]
            record = {k: item.get(k, [] if k == "labels" else {} if k == "metadata" else "") for k in FIELDS}
            record["labels"] = sorted(record["labels"] or [])
            # Dependency list has volatile issue fields; edge endpoint and kind are semantic.
            deps = json.loads(self.ok(self.direct(repo, db, "dep", "list", row["id"], "--json")))
            if isinstance(deps, dict):
                deps = deps.get("dependencies", [])
            record["dependencies"] = sorted(deps, key=lambda d: json.dumps(d, sort_keys=True))
            issues[row["id"]] = record
        ready = json.loads(self.ok(self.direct(repo, db, "ready", "--exclude-type", "epic", "--limit", "0", "--json")))
        return {"issues": issues, "ready": sorted(r["id"] for r in ready)}

    def regression(self):
        frozen = self.candidate / "research/workflows/verification/verify_bdw.py"
        assert digest(frozen) == FROZEN_HASH
        copy = self.owned / "verify_bdw_frozen.py"
        if copy.exists():
            assert digest(copy) == FROZEN_HASH
        else:
            shutil.copyfile(frozen, copy)
        original = self.run([sys.executable, "-B", copy, "--candidate", self.candidate, "--bd", self.bd,
                             "--out", self.out / "regression-original-pin"], self.out)
        self.case(6, "unchanged-verifier-rejects-stale-commit-pin", "old aec83cb pin refuses 040fc9f before cases",
                  original["exit"] != 0 and "AssertionError" in original["stderr"],
                  {"exit": original["exit"], "stderr": original["stderr"]}, "negative", [original])
        launcher = self.owned / "run_frozen_regression.py"
        launcher.write_text('''"""Run the byte-identical frozen verifier against the requested newer candidate.
Only the runtime commit pin changes. Supplemental author tests run from owned
output via PYTHONPATH; all 64 independent case bodies remain unchanged.
"""
import importlib.util
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("frozen_verifier", Path(__file__).with_name("verify_bdw_frozen.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SHA = "040fc9f"
original_run = module.Verifier.run
def owned_run(self, argv, cwd, overrides=None, timeout=90):
    if "unittest" in list(map(str, argv)):
        cwd = self.out
    backup = Path(self.env["DFM_BEADS_BACKUP"]).resolve()
    assert backup.is_relative_to(Path(__file__).resolve().parent)
    return original_run(self, argv, cwd, overrides, timeout)
module.Verifier.run = owned_run
sys.exit(module.main())
''', encoding="utf-8")
        r = self.run([sys.executable, "-B", launcher, "--candidate", self.candidate, "--bd", self.bd,
                      "--out", self.out / "regression-64"], self.out, timeout=900)
        report_path = self.out / "regression-64/verification.json"
        reg = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        counts = reg.get("counts", {})
        self.report["regression_64"] = f"{counts.get('passed', 0)}/{counts.get('total', 0)} passed; exit={r['exit']}; verdict={reg.get('verdict')}; runtime SHA={SHA}"
        self.report["regression_pin_adaptation"] = "Frozen file remains byte-identical; runtime module.SHA selects 040fc9f. Only supplemental author-tests cwd redirected to owned output. Original CLI stale-pin failure retained."
        self.report["frozen_verifier_sha256"] = digest(copy)
        self.case(6, "frozen-independent-64-case-regression", "64/64 earlier independent guarantees pass against 040fc9f",
                  r["exit"] == 0 and counts.get("total") == 64 and counts.get("passed") == 64
                  and digest(copy) == FROZEN_HASH,
                  {"counts": counts, "defects": reg.get("defects"), "harness_error": reg.get("harness_error"),
                   "author_tests": reg.get("author_tests"), "report": str(report_path)}, calls=[r])

    def execute(self):
        assert digest(self.bd) == BD_HASH
        assert self.git(self.candidate, "rev-parse", "HEAD") == FULL_SHA
        src = "research/workflows/graph/bdw.py"
        assert self.git(self.candidate, "hash-object", str(self.candidate / src)) == self.git(self.candidate, "rev-parse", f"{SHA}:{src}")
        repo, wt = self.fixture("primary", worktree=True)
        # init-workspace refuses nonempty origin refs/dolt; remove only for init,
        # then restore this independently owned sentinel for backup checks.
        origin = self.git(repo, "remote", "get-url", "origin")
        sentinel = self.git(repo, "rev-parse", "HEAD")
        self.git(repo, "--git-dir", origin, "update-ref", "-d", "refs/dolt/verifier-sentinel")
        self.ok(self.wrapper(wt, ["init-workspace"]))
        self.git(repo, "--git-dir", origin, "update-ref", "refs/dolt/verifier-sentinel", sentinel)
        db = self.shared(repo)
        ids = self.seed(repo)
        baseline = self.semantics(repo, db)
        self.save("source-semantics.json", baseline)
        self.case(4, "semantic-fixture-covers-required-values", "5 issues; nonempty metadata/labels/descriptions; closed reason; deps; ready excludes blocked and epic",
                  len(baseline["issues"]) == 5 and all(x["metadata"] and x["labels"] and x["description"] for x in baseline["issues"].values())
                  and baseline["issues"][ids["closed"]]["close_reason"] and baseline["issues"][ids["blocked"]]["dependencies"]
                  and ids["ready"] in baseline["ready"] and ids["blocked"] not in baseline["ready"] and ids["epic"] not in baseline["ready"], baseline)
        (repo / "README.md").write_bytes(b"dirty unstaged sentinel\r\n")
        (repo / "tracked.txt").write_bytes(b"staged sentinel\x00\xff\n")
        self.git(repo, "add", "tracked.txt")
        (repo / "untracked.txt").write_bytes(b"untracked sentinel\n")
        (wt / "linked-untracked.txt").write_bytes(b"linked sentinel\n")
        backup = self.out / "offsite-backup"
        before = self.snapshot(repo, wt)
        r = self.wrapper(wt, ["backup-sync"], extra={"DFM_BEADS_BACKUP": str(backup)})
        after = self.snapshot(repo, wt)
        self.save("successful-backup-git-state.json", {"before": before, "after": after})
        receipt = json.loads(r["stdout"]) if r["stdout"].lstrip().startswith("{") else {}
        self.case(1, "coordinator-no-argument-backup-succeeds", "exit 0 and ok receipt", r["exit"] == 0 and receipt.get("ok"), receipt, calls=[r])
        self.case(2, "explicit-external-owned-destination", "nonempty Dolt backup at explicit destination",
                  r["exit"] == 0 and (backup / "manifest").is_file() and Path(receipt.get("dolt_backup", ".")) == backup,
                  {"dest": str(backup), "manifest": (backup / "manifest").is_file()}, calls=[r])
        raw = (repo / REL).read_bytes() if (repo / REL).exists() else b""
        count_call = self.direct(repo, db, "count", "--json")
        count = json.loads(self.ok(count_call))["count"]
        self.case(3, "main-export-LF-all-issue-count", "main JSONL has LF-only records and line count equals bd count (5)",
                  raw and b"\r" not in raw and raw.endswith(b"\n") and len(raw.splitlines()) == count == 5
                  and Path(receipt.get("jsonl", ".")) == repo / REL,
                  {"line_count": len(raw.splitlines()), "bd_count": count, "CR_bytes": raw.count(b"\r"), "receipt": receipt}, calls=[r, count_call])
        self.case(3, "linked-export-absent", "no JSONL created in linked checkout", not (wt / REL).exists(),
                  {"linked_export_exists": (wt / REL).exists()}, "negative", [r])
        expected_after = dict(before, files={**before["files"], REL.as_posix(): digest(repo / REL)})
        self.case(5, "backup-only-JSONL-working-tree-change", "HEAD, exact index/config/hooks, all origin refs, dirty/staged/untracked/linked files preserved; sole new JSONL",
                  after == expected_after, {"snapshot": "successful-backup-git-state.json",
                                            "equal_except_export": after == expected_after}, calls=[r])
        self.dest_probe(repo, db)
        for role in (None, "worker", "verifier", "Coordinator", "coordinator "):
            self.refusal(repo, wt, 1, "non-coordinator-" + repr(role), ["backup-sync"], role)
        for args in (["backup-sync", "extra"], ["backup-sync", "--force"], ["backup-sync", "--help"]):
            self.refusal(repo, wt, 1, "backup-takes-no-args-" + args[-1], args)
        for role in (None, "coordinator"):
            for args in (["backup"], ["backup", "restore", str(backup), "--force"], ["import", str(repo / REL)]):
                self.refusal(repo, wt, 1, f"raw-{'-'.join(args[:2])}-role-{role}", args, role)
        for dest in (repo, repo / "inside", db.parent, db.parent / "nested", db):
            self.refusal(repo, wt, 2, "unsafe-destination-" + dest.relative_to(self.out).as_posix(), ["backup-sync"],
                         extra={"DFM_BEADS_BACKUP": str(dest)})
        before_reject = self.snapshot(repo, wt)
        denied = self.wrapper(wt, ["backup-sync"], role="worker")
        after_reject = self.snapshot(repo, wt)
        self.case(3, "refusal-preserves-existing-export", "worker refusal leaves JSONL bytes unchanged",
                  denied["exit"] == 2 and (repo / REL).read_bytes() == raw, {"exit": denied["exit"], "export_sha256": digest(repo / REL)}, "negative", [denied])
        self.case(5, "refused-backup-preserves-entire-Git-and-files", "exact full snapshots equal",
                  denied["exit"] == 2 and before_reject == after_reject,
                  {"snapshots_equal": before_reject == after_reject}, "negative", [denied])
        for mode in ("dolt", "jsonl"):
            restored = self.fixture("restore-" + mode)
            dest_db = restored / ".beads"
            self.ok(self.direct(restored, dest_db, "init", "--quiet", "--skip-agents", "--skip-hooks", "-p", "dfm"))
            empty = self.semantics(restored, dest_db)
            self.case(4, mode + "-fresh-empty-negative-control", "empty initialized workspace differs from source",
                      empty != baseline and not empty["issues"], empty, "negative")
            args = ["backup", "restore", str(backup), "--force"] if mode == "dolt" else ["import", str(repo / REL)]
            rr = self.direct(restored, dest_db, *args)
            state = self.semantics(restored, dest_db) if rr["exit"] == 0 else {"restore_failed": rr}
            self.save(f"restored-{mode}-semantics.json", state)
            self.case(4, mode + "-restore-all-fields-and-ready", "exact required semantic records/dependency edges/ready set match",
                      rr["exit"] == 0 and state == baseline,
                      {"equal": state == baseline, "restore_exit": rr["exit"], "snapshot": f"restored-{mode}-semantics.json"}, calls=[rr])
            if rr["exit"] == 0:
                mutation = self.direct(restored, dest_db, "update", ids["ready"], "--title", "deliberate negative-control mutation")
                changed = self.semantics(restored, dest_db)
                self.case(4, mode + "-comparator-detects-mutated-copy", "one title change is detected", mutation["exit"] == 0 and changed != baseline,
                          {"equal": changed == baseline}, "negative", [mutation])
        self.regression()
        self.report["coverage"] = {str(n): {p: sum(c["contract"] == n and c["polarity"] == p for c in self.cases)
                                           for p in ("positive", "negative")} for n in range(1, 7)}
        assert all(all(v.values()) for v in self.report["coverage"].values())
        self.report["counts"] = {"total": len(self.cases), "passed": sum(c["pass"] for c in self.cases),
                                 "failed": sum(not c["pass"] for c in self.cases)}
        self.report["verdict"] = "pass" if not self.defects else "fail"
        self.report["limitations"] = ["No real OneDrive/default backup execution: default resolver receives synthetic dictionaries while process DFM_BEADS_BACKUP stays explicitly inside owned folder.",
            "No native Delft3D, real workspace, external network, concurrency, interrupted backup, or scientific validation.",
            "Frozen old commit pin selected at runtime for new candidate; frozen source bytes unchanged. Supplemental author tests are not independent evidence."]
        self.flush()
        print(json.dumps({"verdict": self.report["verdict"], "counts": self.report["counts"], "regression_64": self.report["regression_64"]}), flush=True)

    def refusal(self, repo, wt, contract, name, args, role="coordinator", extra=None):
        before = self.snapshot(repo, wt)
        r = self.wrapper(wt, args, role, extra)
        after = self.snapshot(repo, wt)
        self.case(contract, name, "JSON refusal exit 2 and unchanged Git/files",
                  r["exit"] == 2 and '"refused"' in r["stderr"] and before == after,
                  {"exit": r["exit"], "stderr": r["stderr"], "snapshots_equal": before == after}, "negative", [r])

    def dest_probe(self, repo, db):
        probe = self.out / "destination_probe.py"
        probe.write_text('''import json, os
from pathlib import Path
from research.workflows.graph import bdw
main = Path(os.environ["PROBE_MAIN"])
paths = bdw.Paths(main, Path(os.environ["PROBE_DB"]), Path(os.environ["DFM_BD_EXE"]))
fake = Path(os.environ["OneDrive"])
results = {}
for key, env in [("default", {"OneDrive": str(fake)}), ("consumer", {"OneDriveConsumer": str(fake)}),
                 ("explicit", {"OneDrive": str(fake), "DFM_BEADS_BACKUP": os.environ["DFM_BEADS_BACKUP"]}),
                 ("missing", {})]:
    try:
        results[key] = str(bdw.backup_dest(paths, env))
    except bdw.Refused as exc:
        results[key] = {"refused": str(exc)}
print(json.dumps(results))
''', encoding="utf-8")
        r = self.run([sys.executable, "-B", probe], self.out, {"PROBE_MAIN": str(repo), "PROBE_DB": str(db)})
        data = json.loads(self.ok(r))
        target = str(self.out / "fake-onedrive" / (repo.name + "-beads-backup"))
        self.case(2, "synthetic-OneDrive-default-and-explicit-precedence", "default uses main-name backup; explicit destination wins",
                  data["default"] == target and data["consumer"] == target and data["explicit"] == self.env["DFM_BEADS_BACKUP"], data, calls=[r])
        self.case(2, "missing-default-location-refused-without-writes", "no OneDrive/explicit supplied to pure resolver causes refusal",
                  isinstance(data["missing"], dict) and "refused" in data["missing"] and not (self.out / "fake-onedrive").exists(),
                  data["missing"], "negative", [r])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--bd", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    a = parser.parse_args()
    owned = Path(__file__).resolve().parent
    out = a.out.resolve()
    if out == owned or not out.is_relative_to(owned) or out.exists():
        parser.error("--out must be a fresh child directory inside this script's owned folder")
    # Explicitly set before any subprocess, including Git and unchanged regression.
    os.environ["DFM_BEADS_BACKUP"] = str(out / "safe-backup")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    out.mkdir(parents=True)
    v = Verify(a.candidate.resolve(), a.bd.resolve(), out)
    try:
        v.execute()
    except Exception as exc:
        v.report["harness_error"] = repr(exc)
        v.flush()
        raise
    return 0 if v.report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
