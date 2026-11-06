"""Independent contract verifier for frozen GRAPH-OPS-BDW-I candidate.

All writes, Git fixtures, local origins, subprocess profiles and evidence live
under --out, which must be a fresh directory under this script's owned folder.
The candidate and supplied executable are read-only inputs. No native FM runs.
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

PIN = "ac5b60114e5e7ef9de8878b45fc35941937341d3447366c99bc91c81557be7a4"
SHA = "aec83cb"
SAFE = ("BD_DISABLE_METRICS", "BD_NO_INSTALL_HOOKS", "BD_NO_REMOTE_ADOPT", "BD_NON_INTERACTIVE")
DRIVER = '''import json, os, subprocess, sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ["CANDIDATE_ROOT"])
from research.workflows.graph import bdw
original = subprocess.run
def observed_run(argv, *args, **kwargs):
    if Path(str(argv[0])).name.lower() == "bd.exe":
        e = kwargs.get("env", os.environ)
        with open(os.environ["BDW_TRACE"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": list(map(str, argv)), "cwd": str(kwargs.get("cwd", Path.cwd())),
                "env": {k:v for k,v in e.items() if k.startswith(("BD_", "BEADS_"))}}) + "\\n")
    return original(argv, *args, **kwargs)
subprocess.run = observed_run
sys.exit(bdw.main(sys.argv[1:]))
'''


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


class Verifier:
    def __init__(self, candidate, bd, out):
        self.candidate, self.bd, self.out = candidate, bd, out
        self.calls, self.cases, self.defects = [], [], []
        self.profile = out / "profile"
        self.profile.mkdir(exist_ok=True)
        self.temp = out / "temp"
        self.temp.mkdir(exist_ok=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(
            ("BD_", "BEADS_", "DFM_BD", "GIT_"))}
        self.env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(candidate),
                         "DFM_BD_EXE": str(bd), "CANDIDATE_ROOT": str(candidate),
                         "HOME": str(self.profile), "USERPROFILE": str(self.profile),
                         "APPDATA": str(self.profile / "roaming"),
                         "LOCALAPPDATA": str(self.profile / "local"),
                         "XDG_CONFIG_HOME": str(self.profile / "config"),
                         "XDG_CACHE_HOME": str(self.profile / "cache"),
                         "TEMP": str(self.temp), "TMP": str(self.temp),
                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                         "GIT_CEILING_DIRECTORIES": str(out),
                         "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
                         **{k: "1" for k in SAFE}})
        self.driver = out / "observe_bdw.py"
        self.driver.write_text(DRIVER, encoding="utf-8")
        self.exe_sha = digest(bd)
        self.report = {"task_code": "GRAPH-OPS-BDW-V", "candidate_sha": SHA,
                       "verdict": "fail", "cases": self.cases, "defects": self.defects,
                       "author_tests": "not yet run", "experiment": out.name,
                       "evidence_kind": "observed behavior; source locations are static analysis",
                       "bd_sha256": self.exe_sha, "calls": "calls.json"}

    def run(self, argv, cwd, overrides=None, timeout=90):
        env = dict(self.env)
        for key, val in (overrides or {}).items():
            if val is None:
                env.pop(key, None)
            else:
                env[key] = str(val)
        i = len(self.calls)
        start = time.monotonic()
        try:
            p = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout)
            rc, stdout, stderr = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as exc:
            # subprocess.run owns and kills its direct process on timeout. No
            # unowned process is stopped or inferred to have exited.
            rc, stdout, stderr = -999, str(exc.stdout or ""), str(exc.stderr or "")
        result = {"id": i, "argv": list(map(str, argv)), "cwd": str(cwd),
                  "environment_overrides": overrides or {}, "exit": rc,
                  "stdout": stdout, "stderr": stderr,
                  "elapsed_seconds": round(time.monotonic() - start, 3)}
        self.calls.append(result)
        self.flush()
        return result

    def git(self, repo, *args):
        r = self.run(["git", "-c", "user.name=Independent verifier", "-c",
                      "user.email=verifier@example.invalid", *args], repo)
        if r["exit"]:
            raise RuntimeError(r)
        return r["stdout"].strip()

    def repo(self, name, worktree=False):
        base = self.out / name
        base.mkdir()
        origin, repo = base / "origin.git", base / "project"
        self.git(base, "init", "--bare", "-q", "-b", "main", str(origin))
        self.git(base, "init", "-q", "-b", "main", str(repo))
        for name_, data in {"README.md": b"baseline\n", ".gitignore": b"*.tmp\n",
                            "AGENTS.md": b"independent sentinel\n"}.items():
            (repo / name_).write_bytes(data)
        self.git(repo, "add", "README.md", ".gitignore", "AGENTS.md")
        self.git(repo, "commit", "-q", "-m", "throwaway verification baseline")
        self.git(repo, "remote", "add", "origin", str(origin))
        # No push: seed only the LOCAL bare origin by fetching the local fixture.
        self.git(base, "--git-dir", str(origin), "fetch", "-q", str(repo), "main:main")
        (repo / ".git" / "hooks" / "pre-commit").write_bytes(b"#!/bin/sh\nexit 0\n")
        if worktree:
            wt = base / "linked"
            self.git(repo, "worktree", "add", "-q", "--detach", str(wt))
            return repo, wt
        return repo

    def shared(self, repo):
        common = Path(self.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        main = common.parent
        path = main.parent / (main.name + "-beads") / ".beads"
        assert common.is_relative_to(self.out) and path.is_relative_to(self.out), path
        assert common.name == ".git"
        return path

    def call(self, repo, args, role=None, extra=None):
        # These assertions are the safety gate: NEVER derive a database for a
        # real checkout. Only independently initialized repositories qualify.
        self.shared(repo)
        i = len(self.calls)
        trace = self.out / ("trace-%04d.jsonl" % i)
        env = {"DFM_BD_ROLE": role, "BDW_TRACE": str(trace), **(extra or {})}
        r = self.run([sys.executable, self.driver, *args], repo, env)
        r["bd_calls"] = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()] if trace.exists() else []
        self.flush()
        return r

    @staticmethod
    def refused(r):
        return r["exit"] == 2 and '"refused"' in r["stderr"] and not r.get("bd_calls")

    def case(self, contract, name, expected, passed, observed, calls=(), polarity="positive"):
        item = {"contract": contract, "name": name, "polarity": polarity,
                "expected": expected, "observed": observed, "pass": bool(passed),
                "call_ids": [r["id"] for r in calls]}
        self.cases.append(item)
        print(f"{'PASS' if passed else 'FAIL'} C{contract}: {name}", flush=True)
        self.flush()
        return item

    def defect(self, code, contract, summary, evidence, source, reproduce):
        self.defects.append({"id": code, "contract": contract, "summary": summary,
                             "evidence": evidence, "candidate_source": source,
                             "reproducing_command": reproduce})
        self.flush()

    def snapshot(self, repo):
        # Refresh status first; then preserve actual index bytes, independent
        # of the candidate's weaker name-only staged-change comparison.
        status = self.git(repo, "status", "--porcelain=v1", "-uall")
        main = Path(self.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
        files = {str(p.relative_to(main)): digest(p) for p in main.rglob("*")
                 if p.is_file() and ".git" not in p.relative_to(main).parts}
        hooks = {str(p.relative_to(main / ".git")): digest(p)
                 for p in (main / ".git" / "hooks").rglob("*") if p.is_file()}
        origin = self.git(repo, "remote", "get-url", "origin")
        return {"head": self.git(repo, "rev-parse", "HEAD"), "status": status,
                "index_sha256": digest(main / ".git" / "index"), "files": files, "hooks": hooks,
                "git_config_sha256": digest(main / ".git" / "config"),
                "git_config_text": (main / ".git" / "config").read_text(encoding="utf-8"),
                "origin_refs": self.git(repo, "--git-dir", origin, "for-each-ref", "--format=%(refname) %(objectname)")}

    def db_snapshot(self, repo):
        root = self.shared(repo)
        return {str(p.relative_to(root)): digest(p) for p in root.rglob("*") if p.is_file()} if root.exists() else {}

    def save_pair(self, name, before, after):
        (self.out / (name + ".json")).write_text(json.dumps({"before": before, "after": after}, indent=2), encoding="utf-8")

    def flush(self):
        (self.out / "calls.json").write_text(json.dumps(self.calls, indent=2), encoding="utf-8")
        (self.out / "verification.json").write_text(json.dumps(self.report, indent=2), encoding="utf-8")

    def execute(self):
        assert self.exe_sha == PIN, "Resource binary is not the contract binary"
        head = self.git(self.candidate, "rev-parse", "HEAD")
        assert head.startswith(SHA), head
        self.report["candidate_full_sha"] = head
        rel = "research/workflows/graph/bdw.py"
        actual = self.git(self.candidate, "hash-object", str(self.candidate / rel))
        frozen = self.git(self.candidate, "rev-parse", f"{SHA}:{rel}")
        assert actual == frozen, "Candidate is modified"
        self.report["candidate_blob"] = frozen
        repo, wt = self.repo("normal", worktree=True)
        shared = self.shared(repo)
        nested = repo / "nested"
        nested.mkdir()
        paths = [self.call(p, ["paths"]) for p in (repo, wt, nested)]
        decoded = [json.loads(r["stdout"]) for r in paths]
        self.case(2, "main-linked-nested-share-exact-path", str(shared),
                  all(r["exit"] == 0 and Path(d["beads_dir"]) == shared and Path(d["main"]) == repo
                      for r, d in zip(paths, decoded)), decoded, paths)
        match = self.call(wt, ["paths"], extra={"BEADS_DIR": str(shared)})
        self.case(2, "matching-ambient-accepted", "exit 0", match["exit"] == 0, match, [match])
        for name, ambient in (("external", self.out / "conflicting"), ("internal", repo / ".beads")):
            r = self.call(repo, ["init-workspace"], "coordinator", {"BEADS_DIR": str(ambient)})
            self.case(2, "conflicting-ambient-" + name, "refuse before bd/no created data",
                      self.refused(r) and not ambient.exists() and not shared.exists(), r, [r], "negative")
        worker_init = self.call(repo, ["init-workspace"])
        self.case(4, "worker-cannot-initialize", "refuse/no shared data",
                  self.refused(worker_init) and not shared.exists(), worker_init, [worker_init], "negative")
        # Real initialization from a linked worktree, with dirty and untracked
        # sentinels in main. No staged content in this positive control.
        (repo / "README.md").write_bytes(b"dirty baseline\n")
        (repo / "untracked.txt").write_bytes(b"retain exactly\n")
        before = self.snapshot(repo)
        init = self.call(wt, ["init-workspace"], "coordinator")
        after = self.snapshot(repo)
        self.save_pair("init-git-state", before, after)
        receipt = json.loads(init["stdout"]) if init["stdout"].strip().startswith("{") else {}
        required_state_equal = all(before[k] == after[k] for k in before if not k.startswith("git_config_"))
        self.case(6, "initialize-from-linked-preserves-dirty-main", "initialize once; exact Git/files/hooks/origin equality; sync.remote unset",
                  init["exit"] == 0 and required_state_equal and receipt.get("ok") and
                  (not receipt.get("sync_remote") or "not set" in receipt["sync_remote"].lower()),
                  {"call": init, "required_state_equal": required_state_equal,
                   "full_state_equal": before == after, "snapshot": "init-git-state.json"}, [init])
        self.case(5, "initialization-preserves-git-configuration", "no Git config mutation (clearing Beads sync.remote is separate)",
                  before["git_config_sha256"] == after["git_config_sha256"],
                  {"before": before["git_config_sha256"], "after": after["git_config_sha256"],
                   "snapshot": "init-git-state.json", "after_config": after["git_config_text"]}, [init], "negative")
        if before["git_config_sha256"] != after["git_config_sha256"]:
            self.defect("BDW-V-004", 5, "Initialization changes repository Git config by adding beads.role=maintainer, while reporting git_unchanged=true.",
                        [init["id"]], "aec83cb:research/workflows/graph/bdw.py:164-168,172-199",
                        f'In a fresh local-origin fixture: $env:DFM_BD_ROLE="coordinator"; python -B -m research.workflows.graph.bdw init-workspace; git config --local --get beads.role')
        trace = init["bd_calls"]
        self.case(3, "initialization-process-policy", "three real calls, sandbox and all four safety variables",
                  len(trace) == 3 and all("--sandbox" in t["argv"] and all(t["env"].get(k) == "1" for k in SAFE) for t in trace), trace, [init])
        db_before = self.db_snapshot(repo)
        repeat = self.call(repo, ["init-workspace"], "coordinator")
        db_after = self.db_snapshot(repo)
        self.case(6, "repeat-initialization-refused-preserves-database", "refuse before bd; exact database hashes unchanged",
                  self.refused(repeat) and db_before == db_after, {"call": repeat, "database_equal": db_before == db_after}, [repeat], "negative")

        version = self.call(repo, ["version"])
        self.case(1, "exact-pinned-executable-accepted", "real bd version 1.3.1", version["exit"] == 0 and "1.3.1" in version["stdout"], version, [version])
        bin_dir = self.out / "tampered"
        bin_dir.mkdir()
        tampered = bin_dir / "bd.exe"
        shutil.copyfile(self.bd, tampered)
        with tampered.open("r+b") as f:
            f.seek(-1, 2)
            b = f.read(1)
            f.seek(-1, 2)
            f.write(bytes([b[0] ^ 1]))
        for name, exe in (("one-byte-changed", tampered), ("missing", bin_dir / "missing.exe")):
            r = self.call(repo, ["version"], extra={"DFM_BD_EXE": str(exe)})
            self.case(1, name + "-binary-refused", "refuse before executable launch", self.refused(r), r, [r], "negative")

        hostile = {k: "0" for k in SAFE}
        hostile.update({"BD_FAKE_SENTINEL": "unsafe", "BEADS_DOLT_SERVER_HOST": "external.invalid"})
        r = self.call(repo, ["ready", "--json"], extra=hostile)
        envs = r["bd_calls"]
        self.case(3, "hostile-ambient-values-overridden", "safety values all 1; other BD_/BEADS_ values scrubbed",
                  r["exit"] == 0 and len(envs) == 1 and all(envs[0]["env"].get(k) == "1" for k in SAFE)
                  and "BD_FAKE_SENTINEL" not in envs[0]["env"] and "BEADS_DOLT_SERVER_HOST" not in envs[0]["env"], r, [r], "negative")
        made = self.call(repo, ["create", "independent coordinator issue", "--silent"], "coordinator")
        issue = made["stdout"].strip().splitlines()[-1] if made["exit"] == 0 else "missing-id"
        self.case(4, "coordinator-can-create", "successful issue creation without --readonly", made["exit"] == 0 and
                  all("--readonly" not in t["argv"] for t in made["bd_calls"]), made, [made])
        second = self.call(repo, ["create", "second independent issue", "--silent"], "coordinator")
        second_id = second["stdout"].strip().splitlines()[-1] if second["exit"] == 0 else "missing-id"
        for role in (None, "", "worker", "verifier", "Coordinator", "coordinator "):
            r = self.call(wt, ["list", "--all", "--json"], role)
            rows = json.loads(r["stdout"]) if r["exit"] == 0 else []
            self.case(4, "read-only-role-" + repr(role), "read both shared issues; --readonly on real bd invocation",
                      r["exit"] == 0 and len(rows) == 2 and all("--readonly" in t["argv"] for t in r["bd_calls"]), r, [r])
            denied = self.call(repo, ["create", "must not exist", "--silent"], role)
            self.case(4, "deny-write-role-" + repr(role), "allowlist refuses before bd", self.refused(denied), denied, [denied], "negative")
        for args in (["update", issue, "--title", "forbidden"], ["close", issue],
                     ["dep", "add", issue, second_id], ["comments", "add", issue, "forbidden"]):
            r = self.call(repo, args)
            self.case(4, "worker-deny-" + "-".join(args[:2]), "refuse before bd", self.refused(r), r, [r], "negative")

        safe_read = self.call(repo, ["dep", "cycles"])
        self.case(5, "safe-graph-read-positive-control", "real read succeeds", safe_read["exit"] == 0, safe_read, [safe_read])
        safe_write = self.call(repo, ["update", issue, "--priority", "2"], "coordinator")
        self.case(5, "safe-coordinator-write-positive-control", "scoped graph update succeeds", safe_write["exit"] == 0, safe_write, [safe_write])
        forbidden = [ ["sync"], ["dolt", "push"], ["init", "--reinit-local"], ["ready", "--discard-remote"],
            ["compact"], ["cleanup"], ["admin", "compact"], ["admin", "cleanup"], ["delete", issue],
            ["config", "set", "sync.remote", "origin"], ["hooks", "install"], ["setup", "claude"],
            ["bootstrap"], ["vc", "commit"], ["vc", "reset"], ["dolt", "reset"], ["import", "x"],
            ["federation", "sync"], ["github", "sync"], ["ready", "--db=elsewhere"],
            ["ready", "--remote=origin"], ["ready", "--global"], ["ready", "--force"] ]
        state_before = self.snapshot(repo)
        db_before = self.db_snapshot(repo)
        for args in forbidden:
            r = self.call(repo, args, "coordinator")
            self.case(5, "deny-" + "-".join(args), "policy refuses before bd", self.refused(r), r, [r], "negative")
        state_after = self.snapshot(repo)
        db_after = self.db_snapshot(repo)
        self.save_pair("dangerous-operations-git-state", state_before, state_after)
        self.case(5, "refused-operations-preserve-state", "Git/files and database hashes unchanged",
                  state_before == state_after and db_before == db_after,
                  {"git_equal": state_before == state_after, "db_equal": db_before == db_after})

        # Adversarial global-boolean overrides are parsed by the real pinned bd.
        # Help is a safe probe: no synchronization is triggered in this probe.
        bypass = self.call(repo, ["help", "--sandbox=false"])
        self.case(3, "caller-cannot-disable-sandbox", "refuse explicit --sandbox=false",
                  self.refused(bypass), bypass, [bypass], "negative")
        if not self.refused(bypass):
            self.defect("BDW-V-001", 3, "Caller can override mandatory --sandbox with a later --sandbox=false.",
                        [bypass["id"]], "aec83cb:research/workflows/graph/bdw.py:106-126,144-155",
                        f'Set-Location -LiteralPath "{repo}"; $env:DFM_BD_EXE="{self.bd}"; $env:PYTHONPATH="{self.candidate}"; python -B -m research.workflows.graph.bdw help --sandbox=false')
        ro = self.call(repo, ["help", "--readonly=false"])
        self.case(4, "caller-cannot-disable-readonly", "refuse explicit --readonly=false",
                  self.refused(ro), ro, [ro], "negative")
        # Put a supported global flag VALUE before the comments subcommand.
        # This probes both the allowlist and bd's final effective readonly bit.
        comment = self.call(repo, ["comments", "--actor", "verifier", "add", issue,
                                   "independent forbidden worker comment", "--readonly=false"])
        comments = self.call(repo, ["comments", issue, "--json"])
        wrote = "independent forbidden worker comment" in comments["stdout"]
        self.case(4, "worker-comment-global-flag-value-bypass", "allowlist refuses and no comment is written",
                  self.refused(comment) and not wrote, {"call": comment, "readback": comments, "unauthorized_comment_exists": wrote},
                  [comment, comments], "negative")
        if not self.refused(ro) or wrote:
            self.defect("BDW-V-002", 4,
                        "Worker can override --readonly; comments subcommand filtering can be bypassed by a preceding global-flag value."
                        + (" Real unauthorized comment persisted." if wrote else " See probe output for actual mutation result."),
                        [ro["id"], comment["id"], comments["id"]],
                        "aec83cb:research/workflows/graph/bdw.py:119-126,144-155",
                        f'Set-Location -LiteralPath "{repo}"; $env:DFM_BD_EXE="{self.bd}"; $env:PYTHONPATH="{self.candidate}"; Remove-Item Env:DFM_BD_ROLE -ErrorAction SilentlyContinue; python -B -m research.workflows.graph.bdw comments --actor verifier add {issue} "worker write" --readonly=false')
        # Prove that the subcommand allowlist itself refuses the same write
        # when bd's independent readonly mechanism remains enabled.
        allowlist = self.call(repo, ["comments", "--actor", "verifier", "add", issue, "blocked by bd"])
        self.case(4, "worker-allowlist-before-native-readonly", "wrapper refuses before launching bd",
                  self.refused(allowlist), allowlist, [allowlist], "negative")
        # Repeat the demonstrated mutation via the exact uninstrumented module
        # entry point so the observation shim is not needed for the finding.
        self.shared(repo)
        write = self.run([sys.executable, "-B", "-m", "research.workflows.graph.bdw",
                          "comments", "--actor", "verifier", "add", issue,
                          "uninstrumented forbidden worker write", "--readonly=false"],
                         repo, {"DFM_BD_ROLE": None})
        read = self.call(repo, ["comments", issue, "--json"])
        persisted = "uninstrumented forbidden worker write" in read["stdout"]
        self.case(4, "uninstrumented-worker-mutation-confirmation", "read-only caller cannot persist comment",
                  write["exit"] != 0 and not persisted,
                  {"write": write, "readback": read, "unauthorized_comment_exists": persisted},
                  [write, read], "negative")
        if persisted:
            next(d for d in self.defects if d["id"] == "BDW-V-002")["evidence"].extend([write["id"], read["id"]])

        # Init-workspace must not silently bypass dangerous-flag policy.
        init_args_repo = self.repo("init-dangerous-flag")
        extra = self.call(init_args_repo, ["init-workspace", "--discard-remote"], "coordinator")
        self.case(5, "init-workspace-rejects-dangerous-extra-flag", "policy refuses --discard-remote before any bd call",
                  self.refused(extra), extra, [extra], "negative")
        if not self.refused(extra):
            self.defect("BDW-V-003", 5, "init-workspace bypasses argument validation and silently ignores forbidden trailing flags.",
                        [extra["id"]], "aec83cb:research/workflows/graph/bdw.py:203-215",
                        f'Set-Location -LiteralPath "{init_args_repo}"; $env:DFM_BD_ROLE="coordinator"; $env:DFM_BD_EXE="{self.bd}"; $env:PYTHONPATH="{self.candidate}"; python -B -m research.workflows.graph.bdw init-workspace --discard-remote  # use a fresh fixture for first-run reproduction')
        # Supplemental init fail-closed cases: staged content and existing data.
        staged = self.repo("staged")
        (staged / "README.md").write_bytes(b"staged sentinel\n")
        self.git(staged, "add", "README.md")
        before = self.snapshot(staged)
        r = self.call(staged, ["init-workspace"], "coordinator")
        after = self.snapshot(staged)
        self.save_pair("staged-init-state", before, after)
        self.case(6, "staged-index-fails-closed-without-changes", "refuse before bd or initialize with exact state preservation",
                  self.refused(r) and before == after and not self.shared(staged).exists(), r, [r], "negative")
        existing = self.repo("preexisting")
        existing_shared = self.shared(existing)
        existing_shared.mkdir(parents=True)
        (existing_shared / "sentinel.bin").write_bytes(b"do not delete\x00\xff")
        before = self.db_snapshot(existing)
        r = self.call(existing, ["init-workspace"], "coordinator")
        after = self.db_snapshot(existing)
        self.case(6, "preexisting-data-refused-intact", "refuse before bd and retain sentinel exactly",
                  self.refused(r) and before == after, r, [r], "negative")

        # Required regression ONLY, never included in independent verdict.
        regression = self.run([sys.executable, "-m", "unittest", "research.workflows.graph.test_bdw"],
                              self.candidate, timeout=120)
        self.report["author_tests"] = f'exit={regression["exit"]}; ' + regression["stderr"].strip()
        self.report["author_tests_call_id"] = regression["id"]
        (self.out / "author-tests.txt").write_text(regression["stdout"] + regression["stderr"], encoding="utf-8")
        coverage = {str(c): {p: sum(x["contract"] == c and x["polarity"] == p for x in self.cases)
                             for p in ("positive", "negative")} for c in range(1, 7)}
        assert all(all(v.values()) for v in coverage.values()), coverage
        self.report["coverage"] = coverage
        self.report["counts"] = {"total": len(self.cases), "passed": sum(c["pass"] for c in self.cases),
                                 "failed": sum(not c["pass"] for c in self.cases)}
        self.report["verdict"] = "pass" if all(c["pass"] for c in self.cases) else "fail"
        self.report["limitations"] = ["No native Delft3D, real workspace migration, concurrency or external network tested.",
            "Database file equality is checked only around refused operations; successful bd reads may write lock/metrics files.",
            "Staged-index initialization refusal is treated as acceptable fail-closed behavior.",
            "Nested throwaway Git repositories have their own .git and local bare origins; all derived database paths are asserted inside output."]
        self.flush()
        print(json.dumps({"verdict": self.report["verdict"], "counts": self.report["counts"], "defects": len(self.defects)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--bd", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidate, bd, out = args.candidate.resolve(), args.bd.resolve(), args.out.resolve()
    owned = Path(__file__).resolve().parent
    if not out.is_relative_to(owned) or out == owned:
        parser.error("--out must be a fresh subdirectory of the owned verification folder")
    out.mkdir(parents=True, exist_ok=False)
    v = Verifier(candidate, bd, out)
    try:
        v.execute()
    except Exception as exc:
        v.report["harness_error"] = repr(exc)
        v.flush()
        raise
    return 0 if v.report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
