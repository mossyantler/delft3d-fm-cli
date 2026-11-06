"""Rev2 verification: immutable case bodies, runtime pins, owned subprocesses only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

OWNED = Path(__file__).resolve().parent
CANDIDATE = Path(r"C:\Users\minyeop\project\delft3d-fm-cli-wt\GRAPH-OPS-BACKUP-V2")
BD = Path(r"C:\Users\minyeop\project\delft3d-fm-cli\research\tools\beads\1.3.1\bd.exe")
SHA = "842438c"
FULL_SHA = "842438c3d2ce263988eca60acccec43ced127709"
BACKUP_HASH = "658df7d8df5aa77d9c16f87a4c86b6bbd3615f96986513e85c2d7b405ea965de"
BDW_HASH = "0e5894a55b0e2eff597d838b53cd6f88fc8d13d9a1bf1de5fe19c9c1e8487914"
OUT = OWNED / "run-02-complete"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name, path, expected):
    assert digest(path) == expected, path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def within(path):
    return Path(path).resolve().is_relative_to(OWNED)


def check_env(env):
    backup = env.get("DFM_BEADS_BACKUP")
    if backup:
        assert within(backup), ("unsafe explicit backup", backup)
    for key, value in env.items():
        if key.upper().startswith("ONEDRIVE") and value:
            assert within(value), ("unsafe OneDrive", key, value)
    if env.get("BEADS_DIR"):
        assert within(env["BEADS_DIR"]), "real workspace forbidden"


def audit(event, args):
    if event == "subprocess.Popen":
        executable, argv, cwd, env = args
        argv = shlex.split(argv, posix=False) if isinstance(argv, str) else argv
        check_env(env if env is not None else os.environ)
        actual_cwd = Path(cwd or os.getcwd()).resolve()
        if not within(actual_cwd):
            assert actual_cwd == CANDIDATE and Path(str(argv[0])).stem.lower() == "git", argv
            assert any(x in argv for x in ("rev-parse", "hash-object", "status", "diff")), argv


def sanitize():
    for key in list(os.environ):
        if key.upper().startswith(("ONEDRIVE", "BEADS_", "BD_", "DFM_BD", "GIT_", "DOLT_")):
            del os.environ[key]
    os.environ["DFM_BEADS_BACKUP"] = str(OUT / "safe-backup")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    sys.addaudithook(audit)


def regression_worker():
    module = load("bdw_frozen_02", OWNED / "verify_bdw_frozen.py", BDW_HASH)
    module.SHA = SHA
    original = module.Verifier.run

    def owned_run(self, argv, cwd, overrides=None, timeout=90):
        if "unittest" in list(map(str, argv)):
            cwd = self.out
        return original(self, argv, cwd, overrides, timeout)

    module.Verifier.run = owned_run
    sys.argv = [sys.argv[0], "--candidate", str(CANDIDATE), "--bd", str(BD),
                "--out", str(OUT / "regression-64")]
    return module.main()


def main():
    sanitize()
    if "--regression-worker" in sys.argv:
        return regression_worker()
    assert not OUT.exists(), "use a fresh output directory"
    module = load("backup_frozen_02", OWNED / "verify_backup.py", BACKUP_HASH)
    module.SHA, module.FULL_SHA = SHA, FULL_SHA
    assert digest(OWNED / "verify_bdw_frozen.py") == BDW_HASH
    assert digest(CANDIDATE / "research/workflows/verification/verify_bdw.py") == BDW_HASH
    plan = {
        "task_code": "GRAPH-OPS-BACKUP-V", "candidate_sha": SHA,
        "source": "TASK-02.md Contract 2, derived before executing new cases",
        "frozen_backup_sha256": BACKUP_HASH, "frozen_bdw_sha256": BDW_HASH,
        "new_cases": ["OneDrive process default", "ONEDRIVE process default",
                      "OneDriveConsumer process default", "ONEDRIVE beats consumer",
                      "explicit backup beats process defaults", "all variables absent",
                      "default inside main refused", "default inside shared workspace refused"],
        "safety": "Remove every inherited OneDrive variable; only owned replacement values. All new bdw invocations are real subprocesses in throwaway repositories. No real workspace access.",
        "adaptations": "Runtime commit pins; output receipt redirection; safety checks; supplemental author-test cwd relocation. Frozen independent case bodies remain unchanged."
    }
    (OWNED / "plan-02.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    OUT.mkdir()

    class Verify02(module.Verify):
        def flush(self):
            (self.out / "calls.json").write_text(json.dumps(self.calls, ensure_ascii=False, indent=2), encoding="utf-8")
            text = json.dumps(self.report, ensure_ascii=False, indent=2) + "\n"
            (self.out / "verification.json").write_text(text, encoding="utf-8")
            (self.owned / "verification-02.json").write_text(text, encoding="utf-8")

        def regression(self):
            original = self.run([sys.executable, "-B", self.owned / "verify_bdw_frozen.py",
                                 "--candidate", self.candidate, "--bd", self.bd,
                                 "--out", self.out / "regression-original-pin"], self.out)
            self.case(6, "unchanged-verifier-rejects-stale-commit-pin",
                      "old aec83cb pin refuses candidate before cases",
                      original["exit"] != 0 and "AssertionError" in original["stderr"],
                      {"exit": original["exit"], "stderr": original["stderr"]}, "negative", [original])
            result = self.run([sys.executable, "-B", Path(__file__), "--regression-worker"],
                              self.out, timeout=1200)
            report_path = self.out / "regression-64/verification.json"
            reg = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
            counts = reg.get("counts", {})
            self.report["regression_64"] = f"{counts.get('passed', 0)}/{counts.get('total', 0)} passed; exit={result['exit']}; verdict={reg.get('verdict')}; runtime SHA={SHA}"
            self.report["regression_pin_adaptation"] = "Frozen file bytes unchanged; runtime SHA=842438c; supplemental author-test cwd redirected to owned output. Original stale-pin failure retained."
            self.report["frozen_verifier_sha256"] = BDW_HASH
            self.case(6, "frozen-independent-64-case-regression", "64/64 earlier independent guarantees pass against 842438c",
                      result["exit"] == 0 and counts.get("total") == counts.get("passed") == 64,
                      {"counts": counts, "defects": reg.get("defects"), "harness_error": reg.get("harness_error"),
                       "author_tests": reg.get("author_tests"), "report": str(report_path)}, calls=[result])

        def process_run(self, argv, cwd, overrides):
            env = {k: v for k, v in self.env.items()
                   if not k.upper().startswith("ONEDRIVE") and k.upper() != "DFM_BEADS_BACKUP"}
            env.update({"DFM_BD_ROLE": "coordinator"})
            env.pop("BEADS_DIR", None)
            for key, value in overrides.items():
                if value is not None:
                    env[key] = str(value)
            assert Path(cwd).resolve().is_relative_to(self.out)
            check_env(env)
            start = time.monotonic()
            p = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=180)
            r = {"id": len(self.calls), "argv": list(map(str, argv)), "cwd": str(cwd),
                 "environment_overrides": overrides, "DFM_BEADS_BACKUP": env.get("DFM_BEADS_BACKUP"),
                 "onedrive_environment": {k: v for k, v in env.items() if k.upper().startswith("ONEDRIVE")},
                 "inherited_onedrive_removed": True, "exit": p.returncode,
                 "stdout": p.stdout, "stderr": p.stderr, "seconds": round(time.monotonic() - start, 3)}
            self.calls.append(r)
            (self.out / "logs" / f"{r['id']:04d}.txt").write_text(p.stdout + p.stderr, encoding="utf-8")
            self.flush()
            return r

        def new_cases(self):
            repo, wt = self.fixture("process-defaults", worktree=True)
            origin = self.git(repo, "remote", "get-url", "origin")
            self.git(repo, "--git-dir", origin, "update-ref", "-d", "refs/dolt/verifier-sentinel")
            self.ok(self.wrapper(wt, ["init-workspace"]))
            self.ok(self.wrapper(repo, ["create", "Process-environment backup fixture", "--type", "task", "--silent"]))
            db = self.shared(repo)
            for index, key in enumerate(("OneDrive", "ONEDRIVE", "OneDriveConsumer")):
                root = self.out / f"fake-process-onedrive-{index}"
                self.default_case(repo, wt, "real-process-default-" + key, {key: str(root)},
                                  root / (repo.name + "-beads-backup"))
            root = self.out / "fake-preferred-onedrive"
            consumer = self.out / "fake-secondary-consumer"
            self.default_case(repo, wt, "real-process-OneDrive-precedes-consumer",
                              {"ONEDRIVE": str(root), "OneDriveConsumer": str(consumer)},
                              root / (repo.name + "-beads-backup"), absent=consumer)
            explicit = self.out / "explicit-process-backup"
            unused = self.out / "fake-explicit-unused-onedrive"
            self.default_case(repo, wt, "real-process-explicit-precedes-defaults",
                              {"DFM_BEADS_BACKUP": str(explicit), "OneDrive": str(unused),
                               "OneDriveConsumer": str(unused)}, explicit, absent=unused)
            for name, overrides in (("real-process-no-destination-refused", {}),
                                    ("real-process-default-inside-main-refused", {"ONEDRIVE": str(repo)}),
                                    ("real-process-default-inside-shared-refused", {"OneDriveConsumer": str(db.parent)})):
                before = self.snapshot(repo, wt)
                result = self.process_run([sys.executable, "-B", "-m", "research.workflows.graph.bdw", "backup-sync"], wt, overrides)
                after = self.snapshot(repo, wt)
                message = "no backup destination" if not overrides else "must be outside"
                self.case(2, name, "exit 2, destination refusal, no Git/files changes",
                          result["exit"] == 2 and message in result["stderr"] and before == after,
                          {"exit": result["exit"], "stderr": result["stderr"], "snapshots_equal": before == after},
                          "negative", [result])
                self.cases[-1]["new"] = True
                self.flush()

        def default_case(self, repo, wt, name, overrides, target, absent=None):
            probe = self.process_run([sys.executable, "-B", "-c",
                                     "import os,json; print(json.dumps({k:v for k,v in dict(os.environ).items() if k.upper().startswith('ONEDRIVE') or k=='DFM_BEADS_BACKUP'}))"], wt, overrides)
            effective = json.loads(self.ok(probe))
            before = self.snapshot(repo, wt)
            result = self.process_run([sys.executable, "-B", "-m", "research.workflows.graph.bdw", "backup-sync"], wt, overrides)
            after = self.snapshot(repo, wt)
            receipt = json.loads(result["stdout"]) if result["stdout"].lstrip().startswith("{") else {}
            expected_after = dict(before, files={**before["files"], module.REL.as_posix(): digest(repo / module.REL)}) if (repo / module.REL).exists() else before
            passed = (result["exit"] == 0 and receipt.get("ok") and Path(receipt.get("dolt_backup", ".")) == target
                      and (target / "manifest").is_file() and receipt.get("jsonl_issues") == 1
                      and Path(receipt.get("jsonl", ".")) == repo / module.REL
                      and not (wt / module.REL).exists() and after == expected_after
                      and (absent is None or not absent.exists()))
            self.case(2, name, "actual bdw subprocess writes expected owned backup and main JSONL; Git unchanged",
                      passed, {"effective_process_environment": effective, "expected_destination": str(target),
                               "manifest": (target / "manifest").is_file(), "receipt": receipt,
                               "git_unchanged_except_jsonl": after == expected_after,
                               "unused_default_absent": absent is None or not absent.exists()}, calls=[probe, result])
            self.cases[-1]["new"] = True
            self.flush()

    verifier = Verify02(CANDIDATE, BD, OUT)
    try:
        verifier.execute()
        assert len(verifier.cases) == 37, "frozen suite case count changed"
        verifier.report["frozen_backup_counts"] = dict(verifier.report["counts"])
        for case in verifier.cases:
            case["new"] = False
        verifier.new_cases()
        verifier.report["counts"] = {"total": len(verifier.cases), "passed": sum(c["pass"] for c in verifier.cases),
                                     "failed": sum(not c["pass"] for c in verifier.cases)}
        verifier.report["new_counts"] = {"total": sum(c["new"] for c in verifier.cases),
                                         "passed": sum(c["new"] and c["pass"] for c in verifier.cases)}
        verifier.report["verdict"] = "pass" if all(c["pass"] for c in verifier.cases) else "fail"
        verifier.report["verifier_sha256"] = BACKUP_HASH
        verifier.report["rev2_harness_sha256"] = digest(Path(__file__))
        verifier.report["plan"] = "../plan-02.json"
        verifier.report["limitations"] = ["No real OneDrive or real Beads workspace access. Owned fake paths test local Windows destination selection, not OneDrive cloud synchronization.",
            "No native Delft3D, external network, concurrency, interrupted backup or scientific validation.",
            "Frozen files remain byte-identical; runtime commit pins updated. Supplemental author-test cwd redirected to owned output."]
        verifier.report["frozen_files_unchanged"] = {
            "verify_backup.py": digest(OWNED / "verify_backup.py") == BACKUP_HASH,
            "verify_bdw_frozen.py": digest(OWNED / "verify_bdw_frozen.py") == BDW_HASH}
        verifier.flush()
        print(json.dumps({k: verifier.report[k] for k in ("verdict", "counts", "new_counts", "regression_64")}), flush=True)
    except Exception as exc:
        verifier.report["verdict"] = "fail"
        verifier.report["harness_error"] = repr(exc)
        verifier.flush()
        raise
    return 0 if verifier.report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
