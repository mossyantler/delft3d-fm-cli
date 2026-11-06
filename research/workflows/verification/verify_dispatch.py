"""Independent Contract-first dispatch verifier. Standard library, owned writes only.

python -B verify_dispatch.py --candidate FROZEN --bd BD.EXE --out NEW_OWNED_CHILD
PLAN.md remains frozen. C4 and TASK-run.md govern the recorded fixture changes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import unicodedata

sys.dont_write_bytecode = True
OWNED = Path(__file__).resolve().parent
BASE = "299e7e05615366fafb3af2a79b40e49a075fc572"
CONTRACT = "f40af2b47aa0e5764fdf4a7430bc6cb9727a7694"
BD_HASH = "ac5b60114e5e7ef9de8878b45fc35941937341d3447366c99bc91c81557be7a4"
REL = "research.workflows.graph."
SAFE = {k: "1" for k in ("BD_DISABLE_METRICS", "BD_NO_INSTALL_HOOKS",
                              "BD_NO_REMOTE_ADOPT", "BD_NON_INTERACTIVE")}
FIXTURE_CHANGES = [
    {"clause": "C4.1", "change": "Replace permissive fake aliases with Herdr 0.9.5 positional CLI, result.pane/result.agent envelopes, agent_status and agent_session.value; errors use exit 1/JSON stderr.", "reason": "Binding installed protocol now supplied."},
    {"clause": "C4.1", "change": "Synthetic caller supplies HERDR_ENV=1 and HERDR_PANE_ID; fake start session is null until prompt, and agent get re-reads it; permanent-null case added.", "reason": "Model a Herdr caller and asynchronous session discovery without real Herdr."},
    {"clause": "C4.2", "change": "Accept documented main-relative packet path, usage_unavailable_reason, and documented tokens/models/wall_seconds nesting; retain all semantic expectations.", "reason": "Key spelling is author choice, documented in module docstring."},
    {"clause": "C4.3", "change": "All command errors require exit 2 and exactly one stderr JSON object containing refused/error; successful calls require one stdout object.", "reason": "Previously unspecified refusal protocol is now binding."},
    {"clause": "C4.4", "change": "Replacement-pane stop checks only prohibit closing the replacement; worktree removal is constrained solely by cleanliness.", "reason": "Do not impose rollback or recovery guarantees beyond C2."},
    {"clause": "C4.5 and TASK-run transcript keys", "change": "Codex fixture includes cache_write_input_tokens=7 and total_tokens; both fixtures include two malformed lines, which must be skipped and counted. Keep original token values, duplicate-ID exclusion and 120-second span.", "reason": "Binding malformed-line rule and coordinator-observed real field names."},
    {"clause": "C4.6", "change": "Add invalid task-code and owned junction containment cases; distinguish successful agent get on another pane from a live recorded dispatch.", "reason": "Task-code grammar, canonical containment and live definition are now explicit."},
    {"clause": "C1 coordinator ruling in TASK-run", "change": "Preserve byte-identical frozen case bodies and runtime re-pinning; retain raw stale-pin traceback and command calls.", "reason": "Explicit coordinator interpretation of old frozen commit pins."},
]


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decoded(text, default=None):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def metadata(issue):
    value = issue.get("metadata") or {}
    return decoded(value, {}) if isinstance(value, str) else value


def pick(data, *names):
    if isinstance(data, dict):
        for name in names:
            if name in data:
                return data[name]
    return None


def leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from leaves(v)
    else:
        yield value


def field(data, *names):
    value = pick(data, *names)
    if value is not None:
        return value
    if isinstance(data, dict):
        for child in data.values():
            result = field(child, *names)
            if result is not None:
                return result
    return None


def english_probe(text):
    # A screening check, not a language classifier; retain full prose for review.
    # English punctuation need not be ASCII. Fixture paths/names are ASCII.
    return any("a" <= c.lower() <= "z" for c in text) and not any(
        unicodedata.category(c).startswith("L") and "LATIN" not in unicodedata.name(c, "") for c in text)


FAKE = r'''import json, os, sys
from pathlib import Path
p=Path(os.environ["VERIFY_FAKE_STATE"])
s=json.loads(p.read_text(encoding="utf-8"))
a=sys.argv[1:]
def option(*names,default=None):
 for i,x in enumerate(a):
  for name in names:
   if x==name and i+1<len(a): return a[i+1]
   if x.startswith(name+"="): return x.split("=",1)[1]
 return default
group=a[0] if a else ""
verb=a[1] if len(a)>1 else ""
event={"argv":a,"group":group,"verb":verb,"cwd":os.getcwd()}
with open(os.environ["VERIFY_FAKE_LOG"],"a",encoding="utf-8") as f: f.write(json.dumps(event)+"\n")
def finish(data,rc=0):
 p.write_text(json.dumps(s,indent=2),encoding="utf-8")
 print(json.dumps(data),file=sys.stderr if rc else sys.stdout)
 raise SystemExit(rc)
if s.get("fail")==verb: finish({"error":"controlled "+verb+" failure"},1)
def agent_data():
 agent=s.get("agent",{})
 session=None if s.get("session_never") or not s.get("prompted",True) else s["session_id"]
 return {"name":agent.get("name"),"pane_id":agent.get("pane_id",s["pane_id"]),
  "agent_status":agent.get("status","idle"),"agent_session":{"value":session}}
if verb=="split":
 if group!="pane" or len(a)<3 or a[2]!="caller-pane" or option("--direction") not in ("right","down") or "--no-focus" not in a:
  finish({"error":"split protocol mismatch","argv":a},1)
 s["pane_open"]=True
 s["worktree"]=option("--cwd","--directory",default="")
 finish({"result":{"pane":{"pane_id":s["pane_id"],"cwd":s["worktree"]}}})
if verb=="start":
 if group!="agent" or len(a)<3 or a[2].startswith("-") or "--" not in a or option("--pane")!=s["pane_id"]:
  finish({"error":"start protocol mismatch","argv":a},1)
 name=a[2]
 s["agent"]={"name":name,"pane_id":s["pane_id"],"status":"idle"}
 s["prompted"]=False
 finish({"result":{"agent":agent_data()}})
if verb=="prompt":
 if group!="agent" or len(a)!=4 or a[2]!=s.get("agent",{}).get("name"):
  finish({"error":"prompt protocol mismatch","argv":a},1)
 s["prompted"]=True
 s.setdefault("prompts",[]).append(a); finish({"result":{"ok":True}})
if verb=="close":
 if group!="pane" or len(a)!=3 or a[2]!=s["pane_id"]:
  finish({"error":"close protocol mismatch","argv":a},1)
 s["pane_open"]=False; finish({"result":{"closed":s["pane_id"]}})
if verb=="get":
 if group!="agent" or len(a)!=3 or not s.get("pane_open") or a[2]!=s.get("agent",{}).get("name"):
  finish({"error":"agent not found"},1)
 finish({"result":{"agent":agent_data()}})
finish({"error":"unsupported fake protocol","argv":a},1)
'''

# This observer runs only for candidate dispatch invocations, not the verifier's
# own Git/fixture setup. It blocks accidental access rather than probing real tools.
OBSERVER = r'''import inspect,json,os,subprocess
from pathlib import Path
if os.environ.get("VERIFY_OBSERVE")=="1":
 original=subprocess.Popen.__init__
 def observed(self,args,*pos,**kw):
  argv=list(map(str,args)) if isinstance(args,(list,tuple)) else [str(args)]
  cwd=str(kw.get("cwd") or os.getcwd())
  exe=Path(argv[0]).name.lower()
  stack=[str(x.filename).replace("\\","/") for x in inspect.stack()]
  via=any(x.endswith("/research/workflows/graph/bdw.py") for x in stack)
  root=Path(os.environ["VERIFY_ROOT"]).resolve()
  owned_cwd=Path(cwd).resolve().is_relative_to(root)
  permitted=(exe.startswith(("python","git")) or
    exe in ("bd.exe","fake-herdr.cmd","fake-herdr","cmd.exe","cmd"))
  entry={"argv":argv,"cwd":cwd,"via_bdw":via,"owned_cwd":owned_cwd,
   "permitted":permitted,"stack":stack,
   "beads_dir":(kw.get("env") or os.environ).get("BEADS_DIR")}
  with open(os.environ["VERIFY_PROCESS_LOG"],"a",encoding="utf-8") as f: f.write(json.dumps(entry)+"\n")
  if not owned_cwd or not permitted: raise RuntimeError("Verifier blocked unsafe subprocess: "+repr(argv))
  if exe=="bd.exe":
   if Path(argv[0]).resolve()!=Path(os.environ["DFM_BD_EXE"]).resolve():
    raise RuntimeError("Verifier blocked unexpected bd executable")
   db=(kw.get("env") or os.environ).get("BEADS_DIR","")
   if not db or not Path(db).resolve().is_relative_to(root):
    raise RuntimeError("Verifier blocked non-owned Beads workspace")
  return original(self,args,*pos,**kw)
 subprocess.Popen.__init__=observed
'''

POLICY_PROBE = '''import json,sys
from research.workflows.graph import bdw
try:
 bdw.check_args(json.loads(sys.argv[1]),sys.argv[2])
 print(json.dumps({"allowed":True}))
except bdw.Refused as exc:
 print(json.dumps({"allowed":False,"reason":str(exc)}))
'''


class Harness:
    def __init__(self, candidate, bd, out):
        self.candidate, self.bd, self.out = candidate, bd, out
        self.calls, self.cases, self.defects = [], [], []
        for sub in ("profile", "temp", "bin", "observer", "codex", "claude", "safe-backup", "process"):
            (out / sub).mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith(
            ("BD_", "BEADS_", "DFM_", "GIT_", "DOLT_", "HERDR_", "CODEX_", "CLAUDE_", "ONEDRIVE"))}
        profile = out / "profile"
        self.env.update({"HOME": str(profile), "USERPROFILE": str(profile),
            "APPDATA": str(profile / "roaming"), "LOCALAPPDATA": str(profile / "local"),
            "XDG_CONFIG_HOME": str(profile / "config"), "XDG_CACHE_HOME": str(profile / "cache"),
            "TEMP": str(out / "temp"), "TMP": str(out / "temp"),
            "DFM_BD_EXE": str(bd), "DFM_BD_ROLE": "coordinator",
            "DFM_BEADS_BACKUP": str(out / "safe-backup"), "OneDrive": str(out / "fake-onedrive"),
            "DFM_CODEX_HOME": str(out / "codex"), "DFM_CLAUDE_HOME": str(out / "claude"),
            "HERDR_ENV": "1", "HERDR_PANE_ID": "caller-pane", "HERDR_PANE": "caller-pane",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
            "PYTHONPATH": os.pathsep.join((str(out / "observer"), str(candidate))),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
            "GIT_CEILING_DIRECTORIES": str(out), "VERIFY_ROOT": str(out), **SAFE})
        (out / "fake_herdr.py").write_text(FAKE, encoding="utf-8")
        (out / "observer/sitecustomize.py").write_text(OBSERVER, encoding="utf-8")
        self.probe = out / "policy_probe.py"
        self.probe.write_text(POLICY_PROBE, encoding="utf-8")
        shim = out / "bin/fake-herdr.cmd"
        shim.write_text('@echo off\r\n"' + sys.executable + '" -B "' + str(out / "fake_herdr.py") + '" %*\r\n', encoding="utf-8")
        # Fallback is a trap, not a route to a real Herdr installation.
        (out / "bin/herdr.cmd").write_text('@echo off\r\necho {"error":"DFM_HERDR_EXE ignored"}\r\nexit /b 93\r\n', encoding="ascii")
        self.env["DFM_HERDR_EXE"] = str(shim)
        self.env["PATH"] = str(out / "bin") + os.pathsep + self.env.get("PATH", "")
        self.env.update({"VERIFY_FAKE_STATE": str(out / "fake/default.json"),
                         "VERIFY_FAKE_LOG": str(out / "fake/default.jsonl")})
        write(out / "fake/default.json", {"pane_id": "default-fixture-pane", "session_id": "default-fixture-session",
            "requested_name": "default-fixture-agent", "pane_open": False})
        self.report = {"task_code": "GRAPH-OPS-P3-DISPATCH-V", "phase": "V-Run",
            "candidate_sha": None, "contract_sha": CONTRACT, "verdict": "REJECT",
            "verifier_sha256": digest(__file__), "plan_sha256": digest(OWNED / "PLAN.md"),
            "bd_sha256": digest(bd), "cases": self.cases, "defects": self.defects,
            "author_tests": {}, "calls": "calls.json", "ambiguities_resolved_by": "C4 at " + CONTRACT,
            "fixture_changes_after_plan": FIXTURE_CHANGES,
            "vplan_verifier_sha256": digest(OWNED / "verify_dispatch_vplan.py"),
            "evidence_kind": "observed behavior; source findings labeled static analysis"}
        self.repo = out / "fixtures/project"
        self.repo.parent.mkdir()
        self.repro = subprocess.list2cmdline([sys.executable, "-B", str(Path(__file__).resolve()),
            "--candidate", str(candidate), "--bd", str(bd), "--out", str(OWNED / "reproduce-NEW")])
        self.available = (candidate / "research/workflows/graph/dispatch.py").is_file()
        self.flush()

    def policies(self):
        for role in ("worker", "coordinator"):
            allowed = [["human", "list"], ["human", "stats"]]
            writes = [["human", x] for x in ("respond", "dismiss")] + [
                ["gate", x] for x in ("create", "list", "show", "check", "resolve")]
            denied = [["human"], ["gate"], ["human", "unknown"], ["gate", "unknown"],
                      ["gate", "add-waiter"], ["gate", "discover"]]
            if role == "coordinator":
                allowed += writes
            else:
                denied += writes
            denied += [["human", "--json", "respond", "x"], ["gate", "--json", "discover"],
                       ["human", "list", "--readonly=false"], ["gate", "list", "--sandbox=false"]]
            for expect, commands in ((True, allowed), (False, denied)):
                for args in commands:
                    r = self.run([sys.executable, "-B", self.probe, json.dumps(args), role])
                    data = decoded(r["stdout"], {})
                    self.case("POLICY-" + role + "-" + "-".join(args), "C1", "positive" if expect else "negative",
                        "bdw policy " + ("allows " if expect else "refuses ") + repr(args),
                        r["exit"] == 0 and data.get("allowed") is expect, {"call_id": r["id"], "result": data})
        for role in ("worker", "coordinator"):
            for args in (["human", "list", "--json"], ["human", "stats", "--json"]):
                r = self.bdw(args, role, check=False)
                self.case("POLICY-REAL-" + role + "-" + args[1], "C1", "positive",
                    "Newly allowed human read reaches real throwaway bd successfully",
                    r["exit"] == 0, {"call_id": r["id"], "exit": r["exit"], "stderr": r["stderr"]})
        r = self.bdw(["gate", "list", "--json"], "coordinator", check=False)
        self.case("POLICY-REAL-coordinator-gate-list", "C1", "positive",
            "Coordinator gate list reaches real throwaway bd successfully", r["exit"] == 0,
            {"call_id": r["id"], "exit": r["exit"], "stderr": r["stderr"]})

    def roles(self):
        f = self.new("roles", dispatch=True)
        receipt = self.out / "roles-receipt.json"
        write(receipt, {"task_code": f["code"], "verdict": "PASS"})
        for role in (None, "worker", "verifier", "Coordinator", "coordinator "):
            for command, args in (("start", self.startargs(f)), ("collect", ["collect", f["id"], "--receipt", receipt]),
                                  ("stop", ["stop", f["id"]])):
                before = self.issue(f["id"])
                comments = self.comments(f["id"])
                r = self.invoke(f, args, role)
                unchanged = before == self.issue(f["id"]) and comments == self.comments(f["id"])
                self.binding("ROLE-" + str(role) + "-" + command, "C2." + command,
                    "Non-coordinator refuses exit 2, JSON stderr, no Herdr calls or issue/comment writes",
                    r["exit"] == 2 and isinstance(decoded(r["stderr"]), dict) and not r["fake_calls"] and unchanged,
                    r, "negative", {"issue_comments_unchanged": unchanged})

    def starts(self):
        caller = self.repo.parent / "caller-linked"
        self.git("worktree", "add", "-q", "--detach", str(caller), self.oldhead)
        for variant in ("codex", "claude", "default-name", "explicit-base", "linked-default"):
            f = self.new("start-" + variant)
            if variant == "codex":
                self.bdw(["update", f["id"], "--assignee", "previous-owner"])
            if variant == "claude":
                self.fake(f, kind="claude")
            base = self.oldhead if variant == "explicit-base" else self.head
            r = self.invoke(f, self.startargs(f, "claude" if variant == "claude" else "codex",
                name=variant != "default-name", base=base if variant == "explicit-base" else None),
                cwd=caller if variant == "linked-default" else None)
            issue = self.issue(f["id"])
            m = metadata(issue)
            d = m.get("dispatch") or {}
            wt_ok = False
            if f["wt"].is_dir() and (f["wt"] / ".git").exists():
                wt_ok = self.git("rev-parse", "HEAD", cwd=f["wt"]) == base and not self.git("branch", "--show-current", cwd=f["wt"])
            self.binding("START-" + variant, "C2.start", "Successful JSON result; detached expected worktree and commit",
                self.success(r) and wt_ok, r, extra={"expected_base": base, "worktree_ok": wt_ok})
            values = list(leaves(d))
            required = (pick(d, "agent_name", "agent", "name"), pick(d, "pane_id", "pane"),
                        pick(d, "session_id", "agent_session_id"), pick(d, "started_at"))
            meta_ok = (all(required) and d.get("kind") == ("claude" if variant == "claude" else "codex")
                and required[1] == f["record"]["pane_id"] and required[2] == f["record"]["session_id"]
                and (variant == "default-name" or required[0] == f["name"])
                and pick(d, "model", "requested_model") == "explicit-test-model"
                and pick(d, "effort", "requested_effort") == "high" and d.get("base_sha") == base
                and d.get("worktree") == str(f["wt"]) and digest(f["packet"]) in values
                and isinstance(d.get("packet"), str) and (self.repo / d["packet"]).resolve() == f["packet"].resolve() and d.get("attempt") == 1
                and issue.get("status") == "in_progress" and not issue.get("assignee")
                and m.get("sentinel") == {"nested": [1, "preserve", {"unknown": True}]})
            self.binding("METADATA-" + variant, "C2.start", "Dispatch provenance/status/empty assignee and unknown metadata preserved",
                self.success(r) and meta_ok, r, extra={"issue": issue})
            splits = [e for e in r["fake_calls"] if e["verb"] == "split"]
            starts = [e for e in r["fake_calls"] if e["verb"] == "start"]
            prompts = [e for e in r["fake_calls"] if e["verb"] == "prompt"]
            start_text = " ".join(starts[0]["argv"]) if starts else ""
            split_text = " ".join(splits[0]["argv"]) if splits else ""
            prompt_text = " ".join(prompts[0]["argv"]) if prompts else ""
            no_focus = "--no-focus" in split_text or "--focus=false" in split_text or "--focus false" in split_text
            argv = starts[0]["argv"] if starts else []
            tail = argv[argv.index("--") + 1:] if "--" in argv else []
            expected_tail = ["--model", "explicit-test-model", "--effort", "high", "--permission-mode", "bypassPermissions"] if variant == "claude" else ["--model", "explicit-test-model", "-c", "model_reasoning_effort=high"]
            options_ok = tail == expected_tail
            prompt_ok = (len(prompts) == 1 and "AGENTS.md" in prompt_text and str(f["packet"]) in prompt_text
                         and "read" in prompt_text.lower() and ("execute" in prompt_text.lower() or "follow" in prompt_text.lower())
                         and english_probe(prompt_text))
            self.binding("HERDR-" + variant, "C2.start", "One no-focus adjacent split with worktree cwd, explicit options and one English prompt",
                self.success(r) and len(splits) == 1 and len(starts) == 1 and str(f["wt"]) in split_text
                and "caller-pane" in split_text and no_focus and options_ok and prompt_ok, r)
            events = [e["verb"] for e in r["fake_calls"]]
            self.binding("SESSION-reread-" + variant, "C4.1", "Read session from agent get after prompt when start returned null",
                self.success(r) and "get" in events and "prompt" in events and events.index("get") > events.index("prompt")
                and d.get("session_id") == f["record"]["session_id"], r)
        for variant in ("epic", "closed", "blocked", "live", "invalid-kind", "outside-packet", "prefix-packet", "missing-packet", "bad-base"):
            f = self.new("reject-" + variant, kind="epic" if variant == "epic" else "task", dispatch=variant == "live")
            if variant == "closed":
                self.bdw(["close", f["id"], "--reason", "Fixture closed"])
            if variant == "blocked":
                blocker = self.new("open-blocker")
                self.bdw(["dep", "add", f["id"], blocker["id"]])
            if variant in ("outside-packet", "prefix-packet"):
                target = self.out / ("outside.md" if variant == "outside-packet" else "fixtures/project/research/experiments-sibling/packet.md")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("English fixture packet\n", encoding="utf-8")
                f["packet"] = target
            if variant == "missing-packet":
                f["packet"].unlink()
            args = self.startargs(f, "invalid" if variant == "invalid-kind" else "codex", base="bad-not-a-sha" if variant == "bad-base" else None)
            before = self.issue(f["id"])
            r = self.invoke(f, args)
            forbidden = [e for e in r["fake_calls"] if e["verb"] in ("split", "start", "prompt")]
            self.binding("START-REFUSE-" + variant, "C2.start", "Invalid start refuses before split/start/prompt and leaves issue unchanged",
                self.refusal(r) and not forbidden and before == self.issue(f["id"]), r, "negative")
        for variant in ("clean", "dirty", "untracked", "wrong-sha", "occupied"):
            f = self.new("reuse-" + variant, worktree=variant != "occupied")
            if variant == "occupied":
                f["wt"].mkdir(parents=True)
                (f["wt"] / "sentinel").write_text("preserve", encoding="utf-8")
            elif variant == "dirty":
                (f["wt"] / "README.md").write_text("dirty", encoding="utf-8")
            elif variant == "untracked":
                (f["wt"] / "extra.txt").write_text("untracked", encoding="utf-8")
            elif variant == "wrong-sha":
                self.git("checkout", "-q", "--detach", self.oldhead, cwd=f["wt"])
            before = self.treebytes(f["wt"])
            r = self.invoke(f, self.startargs(f))
            good = self.success(r) if variant == "clean" else self.refusal(r) and not any(
                e["verb"] in ("split", "start", "prompt") for e in r["fake_calls"])
            self.binding("WORKTREE-" + variant, "C2.start", "Reuse only a clean worktree at same SHA; retain occupied-path bytes",
                good and before == self.treebytes(f["wt"]), r, "positive" if variant == "clean" else "negative")
        for stage in ("split", "start", "prompt"):
            f = self.new("failure-" + stage)
            self.fake(f, fail=stage)
            r = self.invoke(f, self.startargs(f))
            events = [e["verb"] for e in r["fake_calls"]]
            fake = json.loads(f["statefile"].read_text(encoding="utf-8"))
            if stage == "prompt":
                self.report.setdefault("diagnostics", []).append({"failure_stage": stage, "call_id": r["id"], "events": events, "state": fake})
            else:
                self.binding("HERDR-FAIL-" + stage, "C2.start", "Failed split never starts; failed agent start leaves no new pane open",
                    self.refusal(r) and ("start" not in events if stage == "split" else not fake["pane_open"]), r, "negative")
        f = self.new("retry", dispatch=True)
        previous = dict(f["record"])
        older = dict(previous, attempt=0, agent_name="older-agent")
        self.setmeta(f, dispatch_history=[older])
        self.fake(f, pane_open=False)
        r = self.invoke(f, self.startargs(f))
        m = metadata(self.issue(f["id"]))
        history = m.get("dispatch_history") or []
        self.binding("METADATA-retry-history", "C2.start", "Redispatch increments attempt and preserves complete earlier dispatches and unrelated metadata",
            self.success(r) and m.get("dispatch", {}).get("attempt") == 2 and older in history and previous in history
            and m.get("sentinel") == {"nested": [1, "preserve", {"unknown": True}]}, r, extra={"metadata": m})

    @staticmethod
    def treebytes(root):
        return {str(p.relative_to(root)): digest(p) for p in root.rglob("*") if p.is_file() and p.name != ".git"} if root.exists() else None

    def clarifications(self):
        f = self.new("null-session")
        self.fake(f, session_never=True)
        r = self.invoke(f, self.startargs(f))
        d = metadata(self.issue(f["id"])).get("dispatch", {})
        self.binding("SESSION-still-null", "C4.1", "Still-missing session is null with a documented reason after post-prompt get",
            self.success(r) and d.get("session_id", "MISSING") is None and bool(d.get("session_id_note"))
            and any(e["verb"] == "get" for e in r["fake_calls"]), r, "negative", {"dispatch": d})
        for label, code in (("lower", "lower-code"), ("underscore", "BAD_CODE"), ("escape", "../ESCAPE"), ("empty", ""), ("number", 123)):
            f = self.new("code-" + label)
            self.setmeta(f, task_code=code)
            before = self.issue(f["id"])
            r = self.invoke(f, self.startargs(f))
            self.binding("TASK-CODE-" + label, "C4.6", "Invalid task code refuses before split/start without metadata changes",
                self.refusal(r) and not any(e["verb"] in ("split", "start", "prompt") for e in r["fake_calls"])
                and before == self.issue(f["id"]), r, "negative")
        for variant in ("other-pane", "same-pane-done"):
            f = self.new("live-" + variant, dispatch=True)
            agent = {"name": f["name"], "pane_id": "different-pane" if variant == "other-pane" else f["record"]["pane_id"], "status": "done"}
            self.fake(f, agent=agent)
            r = self.invoke(f, self.startargs(f))
            good = (self.success(r) and metadata(self.issue(f["id"])).get("dispatch", {}).get("attempt") == 2) if variant == "other-pane" else (
                self.refusal(r) and not any(e["verb"] in ("split", "start", "prompt") for e in r["fake_calls"]))
            self.binding("LIVE-" + variant, "C4.6", "Live is successful agent get on the recorded pane, regardless of settled status", good, r,
                "positive" if variant == "other-pane" else "negative")
        for variant in ("inside", "escape"):
            f = self.new("junction-" + variant)
            target = (self.repo / "research/experiments" / ("target-" + variant)) if variant == "inside" else self.out / "outside-packet-target"
            target.mkdir()
            (target / "packet.md").write_text("Independent English task packet.\n", encoding="utf-8")
            alias = self.repo / "research/experiments" / ("alias-" + variant)
            assert target.resolve().is_relative_to(self.out) and alias.parent.resolve().is_relative_to(self.out)
            setup = self.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(target)])
            if setup["exit"] != 0 or alias.resolve() != target.resolve():
                raise RuntimeError({"owned_junction_setup_failed": setup})
            f["packet"] = alias / "packet.md"
            r = self.invoke(f, self.startargs(f))
            d = metadata(self.issue(f["id"])).get("dispatch", {})
            good = (self.success(r) and isinstance(d.get("packet"), str) and (self.repo / d["packet"]).resolve() == (target / "packet.md").resolve()) if variant == "inside" else (
                self.refusal(r) and not any(e["verb"] in ("split", "start", "prompt") for e in r["fake_calls"]))
            self.binding("PATH-resolved-" + variant, "C4.6", "Resolve an owned junction before testing packet containment", good, r,
                "positive" if variant == "inside" else "negative", {"setup_call_id": setup["id"], "target": str(target), "alias": str(alias)})

    def shows(self):
        for variant, role in (("live", "worker"), ("unset", None), ("other", "arbitrary"), ("missing", "worker"), ("mismatch", "worker")):
            f = self.new("show-" + variant, dispatch=True)
            if variant == "missing":
                self.fake(f, pane_open=False)
            if variant == "mismatch":
                self.fake(f, agent={"name": "replacement-agent", "status": "running", "state": "running"})
            before = self.issue(f["id"])
            comments = self.comments(f["id"])
            r = self.invoke(f, ["show", f["id"]], role)
            values = list(leaves(r["json"]))
            live_ok = variant in ("missing", "mismatch") or ("idle" in values and bool(r["fake_calls"]))
            self.binding("SHOW-" + variant, "C2.show", "Any role reads dispatch plus available live state without writes",
                self.success(r) and f["record"]["session_id"] in values and live_ok
                and before == self.issue(f["id"]) and comments == self.comments(f["id"]), r,
                "negative" if variant in ("missing", "mismatch") else "positive")

    def transcript(self, f, kind):
        session = f["record"]["session_id"]
        if kind == "codex":
            path = self.out / "codex/sessions/2026/11/06" / ("rollout-2026-11-06-" + session + ".jsonl")
            events = [
                {"timestamp": "2026-11-06T00:00:00Z", "type": "session_meta", "payload": {"id": session, "model": "codex-model-one"}},
                {"timestamp": "2026-11-06T00:00:01Z", "type": "turn_context", "payload": {"model": "codex-model-one", "effort": "high"}},
                {"timestamp": "2026-11-06T00:00:10Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 9999, "cached_input_tokens": 9999, "output_tokens": 9999, "reasoning_output_tokens": 9999}}}},
                {"timestamp": "2026-11-06T00:01:00Z", "type": "turn_context", "payload": {"model": "codex-model-two"}},
                {"timestamp": "2026-11-06T00:02:00Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 120, "cached_input_tokens": 30, "cache_write_input_tokens": 7, "output_tokens": 40, "reasoning_output_tokens": 10, "total_tokens": 160}, "last_token_usage": {"input_tokens": 3, "output_tokens": 2}}}},
            ]
        else:
            path = self.out / "claude/projects/fixture-project" / (session + ".jsonl")
            one = {"id": "message-one", "role": "assistant", "model": "claude-model-one", "usage": {
                "input_tokens": 10, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 4, "output_tokens": 5}}
            two = {"id": "message-two", "role": "assistant", "model": "claude-model-two", "usage": {
                "input_tokens": 20, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7, "output_tokens": 8}}
            events = [{"timestamp": "2026-11-06T00:00:00Z", "type": "assistant", "message": one},
                      {"timestamp": "2026-11-06T00:00:30Z", "type": "assistant", "message": one},
                      {"timestamp": "2026-11-06T00:01:00Z", "type": "user", "message": {"id": "user", "usage": {"input_tokens": 9999}}},
                      {"timestamp": "2026-11-06T00:01:30Z", "type": "tool", "message": {"id": "tool", "usage": {"output_tokens": 9999}}},
                      {"timestamp": "2026-11-06T00:02:00Z", "type": "assistant", "message": two}]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{not-json\n{"unterminated"\n' + "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        decoy = path.with_name(path.name.replace(session, "ffffffff-ffff-ffff-ffff-ffffffffffff"))
        decoy.write_text(json.dumps({"timestamp": "2020-01-01T00:00:00Z", "message": {"usage": {"input_tokens": 999999}}}) + "\n", encoding="utf-8")
        return path

    def collects(self):
        for variant in ("codex", "claude", "missing", "reject-receipt", "outcome-receipt", "wrong-code", "malformed", "missing-receipt", "repeat"):
            f = self.new("collect-" + variant, dispatch=True)
            if variant == "claude":
                f["record"]["kind"] = "claude"
                self.setmeta(f, dispatch=f["record"])
            self.bdw(["update", f["id"], "--status", "in_progress"])
            if variant in ("codex", "claude"):
                self.transcript(f, variant)
            receipt = self.out / "receipts" / (variant + ".json")
            verdict = "REJECT" if variant == "reject-receipt" else "PASS"
            write(receipt, {"task_code": "WRONG-CODE" if variant == "wrong-code" else f["code"], "verdict": verdict})
            if variant == "outcome-receipt":
                write(receipt, {"task_code": f["code"], "outcome": "PASS"})
            if variant == "malformed":
                receipt.write_text("{invalid", encoding="utf-8")
            if variant == "missing-receipt":
                receipt.unlink()
            before = self.issue(f["id"])
            comments = self.comments(f["id"])
            r = self.invoke(f, ["collect", f["id"], "--receipt", receipt])
            after = self.issue(f["id"])
            new_comments = self.comments(f["id"])
            if variant in ("wrong-code", "malformed", "missing-receipt"):
                self.binding("COLLECT-REFUSE-" + variant, "C2.collect", "Invalid receipt refused with no metadata/status/comment writes",
                    self.refusal(r) and before == after and comments == new_comments, r, "negative")
                continue
            m = metadata(after)
            rec, metrics = m.get("receipt", {}), m.get("metrics", {})
            values = list(leaves(rec))
            count_ok = isinstance(comments, list) and isinstance(new_comments, list) and len(new_comments) == len(comments) + 1
            comment_new = new_comments[-1] if count_ok else {}
            text = str(pick(comment_new, "text", "body", "content") or "")
            english = english_probe(text)
            self.binding("COLLECT-" + variant, "C2.collect", "Receipt provenance/outcome, metrics and one English comment; status and unrelated metadata preserved",
                self.success(r) and str(receipt) in values and digest(receipt) in values and verdict in values
                and before["status"] == after["status"] and m.get("sentinel") == metadata(before).get("sentinel")
                and m.get("dispatch") == metadata(before).get("dispatch") and bool(metrics) and count_ok and english,
                r, extra={"metadata": m, "comments_before": comments, "comments_after": new_comments})
            if variant in ("codex", "claude"):
                usage = metrics.get("usage", metrics)
                expected = {"input": 120, "cached": 30, "cache_write": 7, "output": 40, "reasoning": 10} if variant == "codex" else {
                    "input": 30, "cached": 7, "cache_write": 11, "output": 13}
                aliases = {"input": ("input_tokens", "input"), "cached": ("cached_input_tokens", "cache_read_input_tokens", "cached_input", "cached"),
                    "output": ("output_tokens", "output"), "reasoning": ("reasoning_output_tokens", "reasoning_tokens", "reasoning"),
                    "cache_write": ("cache_write_tokens", "cache_creation_input_tokens", "cache_write_input_tokens", "cache_write")}
                observed = {key: field(usage, *aliases[key]) for key in expected}
                models = list(leaves(metrics))
                duration = field(metrics, "wall_seconds", "wall_time_seconds", "wall_time", "duration_seconds", "elapsed_seconds")
                self.binding("USAGE-" + variant.upper(), "C2.collect", "Exact transcript counters, actual model IDs and 120-second timestamp span",
                    self.success(r) and observed == expected and variant + "-model-one" in models
                    and variant + "-model-two" in models and duration == 120, r,
                    extra={"metrics": metrics, "expected_tokens": expected, "observed_tokens": observed})
                self.binding("MALFORMED-" + variant, "C4.5", "Skip and count two malformed JSONL lines without failing collection",
                    self.success(r) and field(metrics, "malformed_lines") == 2, r, "negative", {"metrics": metrics})
            else:
                usage = metrics.get("usage", "MISSING")
                reason = field(metrics, "reason", "usage_reason", "usage_error", "usage_missing_reason", "usage_unavailable_reason")
                self.binding("USAGE-MISSING-" + variant, "C2.collect", "Missing transcript remains successful with explicit null usage and reason",
                    self.success(r) and usage is None and bool(reason), r, "negative", {"metrics": metrics})
            if variant == "repeat":
                r2 = self.invoke(f, ["collect", f["id"], "--receipt", receipt])
                final_comments = self.comments(f["id"])
                self.binding("COLLECT-repeat-one-comment", "C2.collect", "Each successful collect adds exactly one comment and does not close task",
                    self.success(r2) and len(final_comments) == len(new_comments) + 1
                    and self.issue(f["id"])["status"] == "in_progress", r2)

    def stops(self):
        for variant in ("idle", "done", "running", "replacement", "dirty", "untracked", "missing"):
            f = self.new("stop-" + variant, dispatch=True, state=variant if variant in ("running", "done") else "idle", worktree=True)
            if variant == "replacement":
                self.fake(f, agent={"name": "replacement", "agent_name": "replacement", "status": "idle", "state": "idle"})
            if variant == "dirty":
                (f["wt"] / "README.md").write_text("preserve dirty bytes\n", encoding="utf-8")
            if variant == "untracked":
                (f["wt"] / "untracked.txt").write_text("preserve untracked bytes\n", encoding="utf-8")
            if variant == "missing":
                self.fake(f, pane_open=False)
            before = self.treebytes(f["wt"])
            r = self.invoke(f, ["stop", f["id"]])
            closed = [e for e in r["fake_calls"] if e["verb"] == "close"]
            d = metadata(self.issue(f["id"])).get("dispatch", {})
            exact_close = len(closed) == 1 and f["record"]["pane_id"] in closed[0]["argv"]
            if variant in ("idle", "done"):
                good = self.success(r) and exact_close and not f["wt"].exists() and bool(d.get("ended_at"))
                expected = "Matching idle/done pane closes, clean worktree removed, ended_at recorded"
            elif variant in ("dirty", "untracked"):
                good = before == self.treebytes(f["wt"])
                expected = "Dirty/untracked worktree is retained byte-for-byte"
            else:
                good = not closed and (variant in ("missing", "replacement") or before == self.treebytes(f["wt"]))
                expected = "Never close a running, replacement or missing pane"
            self.binding("STOP-" + variant, "C2.stop", expected, good, r,
                "positive" if variant in ("idle", "done") else "negative", {"recorded_dispatch": d})

    def flush(self):
        self.report["counts"] = {"total": len(self.cases), "passed": sum(c["pass"] for c in self.cases),
                                 "failed": sum(not c["pass"] for c in self.cases)}
        write(self.out / "calls.json", self.calls)
        write(self.out / "verification.json", self.report)

    def run(self, argv, cwd=None, extra=None, timeout=90):
        cwd = Path(cwd or self.repo).resolve()
        assert cwd.is_relative_to(self.out), cwd
        env = dict(self.env)
        for key, value in (extra or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        start = time.monotonic()
        try:
            p = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout)
            rc, stdout, stderr = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as exc:
            rc, stdout, stderr = -999, str(exc.stdout or ""), str(exc.stderr or "")
        r = {"id": len(self.calls), "argv": list(map(str, argv)), "cwd": str(cwd),
            "environment_overrides": {k: None if v is None else str(v) for k, v in (extra or {}).items()}, "exit": rc, "stdout": stdout, "stderr": stderr,
            "elapsed_seconds": round(time.monotonic() - start, 3)}
        self.calls.append(r)
        self.flush()
        return r

    def git(self, *args, cwd=None):
        r = self.run(["git", "-c", "user.name=Independent verifier", "-c", "user.email=verifier@example.invalid", *args], cwd)
        if r["exit"]:
            raise RuntimeError({"fixture_git_failed": r})
        return r["stdout"].strip()

    def bdw(self, args, role="coordinator", check=True):
        r = self.run([sys.executable, "-B", "-m", REL + "bdw", *args], extra={"DFM_BD_ROLE": role})
        if check and r["exit"]:
            raise RuntimeError({"fixture_bdw_failed": r})
        return r

    def issue(self, ident):
        data = decoded(self.bdw(["show", ident, "--json"])["stdout"])
        return data[0] if isinstance(data, list) else data

    def comments(self, ident):
        return decoded(self.bdw(["comments", ident, "--json"])["stdout"], [])

    def new(self, label, kind="task", dispatch=False, state="idle", worktree=False):
        code = "VERIFY-" + label.upper().replace("_", "-")
        meta = {"task_code": code, "sentinel": {"nested": [1, "preserve", {"unknown": True}]}}
        wt = self.repo.parent / "project-wt" / code
        packet = self.repo / "research/experiments" / (code + ".md")
        packet.write_text("Read AGENTS.md and report independently in English.\n", encoding="utf-8")
        # Packet is ignored in the throwaway repo, matching real experiment layout.
        session = "00000000-0000-0000-0000-" + hashlib.sha256(code.encode()).hexdigest()[:12]
        pane = "pane-" + label
        name = "agent-" + label
        record = {"agent_name": name, "agent": name, "name": name,
            "pane_id": pane, "pane": pane, "kind": "codex", "model": "fixture-model",
            "requested_model": "fixture-model", "effort": "high", "requested_effort": "high",
            "session_id": session, "agent_session_id": session, "worktree": str(wt),
            "base_sha": self.head, "packet": str(packet), "packet_path": str(packet),
            "packet_sha256": digest(packet), "started_at": "2026-11-06T00:00:00Z", "attempt": 1}
        if dispatch:
            meta["dispatch"] = record
        r = self.bdw(["create", code + ": independent fixture", "-t", kind, "--silent", "--metadata", json.dumps(meta)])
        ident = r["stdout"].strip().splitlines()[-1]
        data = {"id": ident, "code": code, "packet": packet, "wt": wt, "record": record,
            "statefile": self.out / "fake" / (label + ".json"), "log": self.out / "fake" / (label + ".jsonl"),
            "process_log": self.out / "process" / (label + ".jsonl"), "name": name, "label": label}
        state_data = {"pane_id": pane, "session_id": session, "requested_name": name,
            "kind": "codex", "pane_open": dispatch, "worktree": str(wt),
            "agent": {"name": name, "agent_name": name, "pane_id": pane, "paneId": pane,
                "status": state, "state": state, "session_id": session, "sessionId": session}}
        write(data["statefile"], state_data)
        if worktree:
            self.git("worktree", "add", "-q", "--detach", str(wt), self.head)
        return data

    def fake(self, f, **changes):
        data = json.loads(f["statefile"].read_text(encoding="utf-8"))
        data.update(changes)
        write(f["statefile"], data)

    def setmeta(self, f, **changes):
        meta = metadata(self.issue(f["id"]))
        meta.update(changes)
        self.bdw(["update", f["id"], "--metadata", json.dumps(meta)])

    def snapshot(self):
        return {"head": self.git("rev-parse", "HEAD"),
            "status": self.git("status", "--porcelain=v1", "-uall"),
            "index": digest(self.repo / ".git/index"), "config": digest(self.repo / ".git/config"),
            "files": {str(p.relative_to(self.repo)): digest(p) for p in self.repo.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(self.repo).parts},
            "hooks": {p.name: digest(p) for p in (self.repo / ".git/hooks").iterdir() if p.is_file()},
            "origin_refs": self.git("--git-dir", str(self.origin), "for-each-ref", "--format=%(refname) %(objectname)")}

    def case(self, ident, contract, polarity, expected, passed, observed):
        item = {"id": ident, "contract": contract, "polarity": polarity, "expected": expected,
            "pass": bool(passed), "observed": observed, "reproducing_command": self.repro,
            "evidence_kind": "observed behavior", "source_commit": self.report["candidate_sha"]}
        self.cases.append(item)
        if not passed:
            self.defects.append({"id": "DISPATCH-V-%03d" % (len(self.defects) + 1), "case_id": ident,
                "contract": contract, "summary": expected, "evidence": observed,
                "reproducing_command": self.repro, "candidate_sha": self.report["candidate_sha"],
                "classification": "missing dispatch module" if contract.startswith("C2") and not self.available
                                  else "contract observation failed against binding C4"})
        print(("PASS " if passed else "FAIL ") + ident, flush=True)
        self.flush()

    @staticmethod
    def lines(path):
        return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()] if Path(path).exists() else []

    def invoke(self, f, args, role="coordinator", cwd=None):
        before = self.snapshot()
        log_count = len(self.lines(f["log"]))
        r = self.run([sys.executable, "-B", "-m", REL + "dispatch", *map(str, args)], cwd,
            {"DFM_BD_ROLE": role, "VERIFY_FAKE_STATE": f["statefile"], "VERIFY_FAKE_LOG": f["log"],
             "VERIFY_PROCESS_LOG": f["process_log"], "VERIFY_OBSERVE": "1"})
        r["fake_calls"] = self.lines(f["log"])[log_count:]
        r["main_unchanged"] = before == self.snapshot()
        r["module_present"] = self.available
        r["json"] = decoded(r["stdout"])
        error = decoded(r["stderr"])
        protocol_ok = self.success(r) or (r["exit"] == 2 and isinstance(error, dict)
            and bool(set(error) & {"refused", "error"}) and not r["stdout"].strip())
        self.case("JSON-" + str(r["id"]), "C4.3", "positive" if r["exit"] == 0 else "negative",
            "Success: one stdout JSON object; failure: exit 2, one stderr JSON object with refused/error",
            protocol_ok, {"call_id": r["id"], "exit": r["exit"], "stdout": r["stdout"], "stderr": r["stderr"]})
        trace = self.lines(f["process_log"])
        r["bd_via_bdw"] = all(e["via_bdw"] for e in trace if Path(e["argv"][0]).name.lower() == "bd.exe")
        r["process_safe"] = all(e["owned_cwd"] and e["permitted"] for e in trace)
        self.case("SAFETY-" + str(r["id"]), "C3", "negative",
            "Main files/index/config/HEAD/origin unchanged; all subprocess cwd owned; bd routed through bdw",
            r["main_unchanged"] and r["bd_via_bdw"] and r["process_safe"], {"call_id": r["id"],
                "main_unchanged": r["main_unchanged"], "bd_via_bdw": r["bd_via_bdw"], "process_log": str(f["process_log"])})
        return r

    def binding(self, ident, clause, expected, passed, r, polarity="positive", extra=None):
        self.case(ident, clause, polarity, expected, self.available and passed,
            {"call_id": r["id"], "exit": r["exit"], "stdout": r["stdout"], "stderr": r["stderr"],
             "fake_calls": r.get("fake_calls", []), **(extra or {})})

    def startargs(self, f, kind="codex", name=True, base=None):
        args = ["start", f["id"], "--packet", str(f["packet"]), "--kind", kind,
                "--model", "explicit-test-model", "--effort", "high"]
        if name:
            args += ["--name", f["name"]]
        if base:
            args += ["--base", base]
        return args

    @staticmethod
    def success(r):
        return r["exit"] == 0 and isinstance(r["json"], dict)

    @staticmethod
    def refusal(r):
        error = decoded(r["stderr"])
        return r["exit"] == 2 and isinstance(error, dict) and bool(set(error) & {"refused", "error"}) and not r["stdout"].strip()

    def prepare(self):
        assert digest(self.bd) == BD_HASH, "Unexpected bd resource hash"
        # All Git inspection of candidate uses git -C from owned cwd, never runs
        # candidate code there and disables optional Git locks.
        self.report["candidate_sha"] = self.git("-C", str(self.candidate), "rev-parse", "HEAD", cwd=self.out)
        self.report["candidate_initial_status"] = self.git("-C", str(self.candidate), "status", "--porcelain=v1", cwd=self.out)
        self.report["source_manifest"] = {name: digest(self.candidate / "research/workflows/graph" / name)
            for name in ("dispatch.py", "bdw.py", "test_dispatch.py", "test_bdw.py")}
        self.report["contract_blob"] = self.git("-C", str(self.candidate), "rev-parse", CONTRACT + ":research/notes/delivery/graph-ops-p3-dispatch.md", cwd=self.out)
        doc = ast.get_docstring(ast.parse((self.candidate / "research/workflows/graph/dispatch.py").read_text(encoding="utf-8"))) or ""
        self.case("SCHEMA-documented", "C4.2", "positive", "Module docstring documents dispatch, receipt and metrics semantic keys",
            all(key in doc for key in ("agent", "pane_id", "session_id", "packet", "packet_sha256", "attempt", "usage", "tokens", "models", "wall_seconds", "malformed_lines")),
            {"source": "research/workflows/graph/dispatch.py:1", "sha256": self.report["source_manifest"]["dispatch.py"]})
        self.origin = self.repo.parent / "origin.git"
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.out)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.out)
        (self.repo / "research/experiments").mkdir(parents=True)
        (self.repo / "README.md").write_text("baseline one\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("Independent throwaway project.\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("research/experiments/\n", encoding="utf-8")
        self.git("add", "README.md", "AGENTS.md", ".gitignore")
        self.git("commit", "-q", "-m", "throwaway baseline one")
        self.oldhead = self.git("rev-parse", "HEAD")
        (self.repo / "README.md").write_text("baseline two\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "throwaway baseline two")
        self.head = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("--git-dir", str(self.origin), "fetch", "-q", str(self.repo), "main:main")
        self.bdw(["init-workspace"])
        (self.repo / "README.md").write_text("dirty main sentinel\n", encoding="utf-8")
        (self.repo / "staged.txt").write_bytes(b"staged sentinel\x00\xff")
        self.git("add", "staged.txt")
        (self.repo / "untracked.txt").write_text("untracked sentinel\n", encoding="utf-8")
        self.flush()

    def regressions(self):
        root = self.out / "regression-tools"
        root.mkdir()
        hashes = {}
        for name in ("verify_bdw.py", "verify_backup.py"):
            # Frozen examples come from the Contract base, not the candidate.
            r = self.run(["git", "-C", str(self.candidate), "show", BASE + ":research/workflows/verification/" + name], self.out)
            if r["exit"]:
                raise RuntimeError("Cannot load frozen regression: " + r["stderr"])
            target = root / name
            # Git stores LF; retain those exact bytes, including final newline.
            target.write_bytes(r["stdout"].encode("utf-8"))
            hashes[name] = digest(target)
        launcher = root / "run_regressions.py"
        launcher.write_text(REGRESSION_DRIVER, encoding="utf-8")
        r = self.run([sys.executable, "-B", launcher, str(self.candidate), str(self.bd), self.report["candidate_sha"]], self.out, timeout=1200)
        result_path = root / "result.json"
        result = decoded(result_path.read_text(encoding="utf-8"), {}) if result_path.exists() else {}
        self.report["frozen_regressions"] = {"hashes": hashes, "result": result, "call_id": r["id"],
            "adjustments": "Byte-identical base scripts; runtime SHA/FULL_SHA selection, owned cwd for author tests and Git -C for candidate reads; backup nested bdw regression reuses full separate result."}
        for name in ("bdw", "backup"):
            item = result.get(name, {})
            self.case("REGRESSION-" + name, "C1", "positive", "All frozen " + name + " verifier cases still pass",
                item.get("verdict") == "pass" and item.get("counts", {}).get("total", 0) > 0
                and item.get("counts", {}).get("failed") == 0,
                {"call_id": r["id"], "result": item, "result_path": str(result_path)})

    def selfchecks(self):
        f = self.new("harness-selfcheck")
        extra = {"VERIFY_FAKE_STATE": f["statefile"], "VERIFY_FAKE_LOG": f["log"]}
        checks = []
        commands = (["pane", "split", "caller-pane", "--direction", "right", "--cwd", str(f["wt"]), "--no-focus"],
            ["agent", "start", f["name"], "--kind", "codex", "--pane", f["record"]["pane_id"], "--", "--model", "fixture", "-c", "model_reasoning_effort=high"],
            ["agent", "prompt", f["name"], "Read AGENTS.md and execute the packet in English."],
            ["agent", "get", f["name"]], ["pane", "close", f["record"]["pane_id"]])
        for args in commands:
            r = self.run([self.env["DFM_HERDR_EXE"], *args], extra=extra)
            checks.append({"case": "fake-success-" + args[1], "pass": r["exit"] == 0 and isinstance(decoded(r["stdout"]), dict), "call_id": r["id"]})
        for stage in ("split", "start", "prompt", "get", "close"):
            self.fake(f, fail=stage, pane_open=True)
            r = self.run([self.env["DFM_HERDR_EXE"], "pane" if stage in ("split", "close") else "agent", stage], extra=extra)
            checks.append({"case": "fake-failure-" + stage, "pass": r["exit"] == 1 and isinstance(decoded(r["stderr"]), dict) and not r["stdout"].strip(), "call_id": r["id"]})
        observer = {**extra, "VERIFY_OBSERVE": "1", "VERIFY_PROCESS_LOG": f["process_log"]}
        r = self.run([sys.executable, "-B", "-c", "import subprocess,sys; subprocess.run([sys.executable,'-B','-c','print(123)'],check=True)"], extra=observer)
        traces = self.lines(f["process_log"])
        checks.append({"case": "observer-records-owned-child", "pass": r["exit"] == 0 and bool(traces) and all(x["owned_cwd"] for x in traces), "call_id": r["id"]})
        r = self.run([sys.executable, "-B", "-c", "import subprocess; subprocess.run(['verification-unapproved-tool'])"], extra=observer)
        checks.append({"case": "observer-blocks-unapproved-tool", "pass": r["exit"] != 0 and "Verifier blocked unsafe subprocess" in r["stderr"], "call_id": r["id"]})
        for kind in ("codex", "claude"):
            path = self.transcript(f, kind)
            events = [decoded(line) for line in path.read_text(encoding="utf-8").splitlines() if isinstance(decoded(line), dict)]
            if kind == "codex":
                counts = [x["payload"]["info"]["total_token_usage"] for x in events if x.get("payload", {}).get("type") == "token_count"]
                good = counts[-1] == {"input_tokens": 120, "cached_input_tokens": 30, "cache_write_input_tokens": 7, "output_tokens": 40, "reasoning_output_tokens": 10, "total_tokens": 160}
            else:
                unique = {x["message"]["id"]: x["message"]["usage"] for x in events if x.get("type") == "assistant"}
                good = {k: sum(x[k] for x in unique.values()) for k in next(iter(unique.values()))} == {
                    "input_tokens": 30, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 11, "output_tokens": 13}
            checks.append({"case": "transcript-fixture-" + kind, "pass": good, "path": str(path)})
        self.report["harness_checks"] = checks
        self.flush()
        if not all(c["pass"] for c in checks):
            raise RuntimeError("Harness selfcheck failed; see harness_checks")

    def supplemental(self):
        for name in ("test_bdw", "test_dispatch"):
            r = self.run([sys.executable, "-B", "-m", "unittest", REL + name, "-v"], self.out, timeout=180)
            self.report["author_tests"][name] = {"call_id": r["id"], "exit": r["exit"], "stdout": r["stdout"], "stderr": r["stderr"]}
            self.case("AUTHOR-" + name, "C1" if name == "test_bdw" else "C2.done", "positive",
                "Required author test module passes (supplemental evidence)", r["exit"] == 0,
                {"call_id": r["id"], "exit": r["exit"], "stderr": r["stderr"]})
        r = self.run([sys.executable, "-m", "compileall", "-q", str(self.candidate / "research/workflows")],
            self.out, {"PYTHONPYCACHEPREFIX": self.out / "pycache", "PYTHONDONTWRITEBYTECODE": None}, timeout=120)
        self.case("SYNTAX-workflows", "C3", "positive", "Candidate workflow syntax compiles; all pycache writes owned",
            r["exit"] == 0, {"call_id": r["id"], "exit": r["exit"], "stderr": r["stderr"]})

    def execute(self):
        self.prepare()
        self.selfchecks()
        self.policies()
        self.roles()
        self.starts()
        self.clarifications()
        self.shows()
        self.collects()
        self.stops()
        self.regressions()
        self.supplemental()
        status = self.git("-C", str(self.candidate), "status", "--porcelain=v1", cwd=self.out)
        self.case("SAFETY-candidate-read-only", "C3", "negative", "Supplied read-only candidate status remains unchanged",
            status == self.report["candidate_initial_status"], {"initial": self.report["candidate_initial_status"], "final": status})
        self.report["coverage"] = {clause: {p: sum(c["contract"] == clause and c["polarity"] == p for c in self.cases)
            for p in ("positive", "negative")} for clause in sorted({c["contract"] for c in self.cases})}
        self.report["limitations"] = [
            "No real Beads/Herdr/transcript/native-engine access. No scientific or simulation validation.",
            "C4 resolves the original PLAN ambiguities; recovery beyond explicit C2 guarantees is diagnostic.",
            "C3 snapshots cover main working-tree/index/config/hooks/HEAD/origin; legitimate administrative worktree registrations excluded.",
            "Author tests are separately reported and do not replace independent cases."]
        self.report["verdict"] = "REJECT" if self.defects else "PASS"
        self.flush()
        print(json.dumps({"verdict": self.report["verdict"], "counts": self.report["counts"], "report": str(self.out / "verification.json")}))


REGRESSION_DRIVER = r'''import importlib.util,json,os,sys,traceback
from pathlib import Path
candidate,bd,sha=sys.argv[1:]
root=Path(__file__).resolve().parent
def load(name):
 spec=importlib.util.spec_from_file_location("frozen_"+name,root/("verify_"+name+".py"))
 m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
 return m
result={}
try:
 b=load("bdw"); stale_sha=b.SHA; b.SHA=sha
 original=b.Verifier.run
 def owned_run(self,argv,cwd,overrides=None,timeout=90):
  if Path(cwd).resolve()==Path(candidate).resolve():
   if str(argv[0])=="git": argv=[argv[0],"-C",str(candidate),*argv[1:]]
   cwd=self.out
  self.env.update({"HOME":str(self.out/"profile"),"DFM_BEADS_BACKUP":str(self.out/"safe-backup"),
   "DFM_CODEX_HOME":os.environ["DFM_CODEX_HOME"],"DFM_CLAUDE_HOME":os.environ["DFM_CLAUDE_HOME"],
   "DFM_HERDR_EXE":os.environ["DFM_HERDR_EXE"]})
  return original(self,argv,cwd,overrides,timeout)
 b.Verifier.run=owned_run
 out=root/"bdw-run"; out.mkdir()
 v=b.Verifier(Path(candidate),Path(bd),out); v.execute(); result["bdw"]=v.report
 b.SHA=stale_sha
 stale=root/"stale-pin-run"; stale.mkdir()
 try:
  v=b.Verifier(Path(candidate),Path(bd),stale); v.execute()
  result["stale_pin_refused"]=False
 except AssertionError:
  result["stale_pin_refused"]=True
  result["stale_pin_failure"]=traceback.format_exc()
  (stale/"pinned-failure.txt").write_text(result["stale_pin_failure"],encoding="utf-8")
 finally:
  b.SHA=sha
 a=load("backup"); a.SHA=sha; a.FULL_SHA=sha
 backup_run=a.Verify.run
 def safe_run(self,argv,cwd,overrides=None,timeout=120):
  if Path(cwd).resolve()==Path(candidate).resolve():
   if str(argv[0])=="git": argv=[argv[0],"-C",str(candidate),*argv[1:]]
   cwd=self.out
  self.env["HOME"]=str(self.out/"profile")
  return backup_run(self,argv,cwd,overrides,timeout)
 a.Verify.run=safe_run
 def reuse(self):
  counts=result["bdw"].get("counts",{})
  self.report["regression_64"]="Reused independently executed unchanged frozen bdw cases at runtime candidate SHA"
  self.case(6,"reused-frozen-bdw-regression","All independent frozen bdw cases pass",counts.get("failed")==0 and counts.get("total",0)>0,
   {"report":str(root/"bdw-run/verification.json"),"counts":counts})
  self.case(6,"unchanged-verifier-rejects-stale-commit-pin","Original frozen commit pin refuses the new candidate before cases",
   result.get("stale_pin_refused") is True,{"original_pin":stale_sha,"candidate":sha,"report":str(stale/"verification.json")},"negative")
 a.Verify.regression=reuse
 out=root/"backup-run"; out.mkdir()
 v=a.Verify(Path(candidate),Path(bd),out); v.execute(); result["backup"]=v.report
except BaseException:
 result["harness_error"]=traceback.format_exc()
finally:
 (root/"result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
raise SystemExit(0 if all(result.get(x,{}).get("verdict")=="pass" for x in ("bdw","backup")) else 1)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--bd", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(OWNED) or out == OWNED or out.exists():
        parser.error("--out must be a new subdirectory of the owned verification folder")
    if not args.candidate.resolve().is_dir() or not args.bd.resolve().is_file():
        parser.error("Candidate directory and bd executable must exist")
    out.mkdir(parents=True)
    h = Harness(args.candidate.resolve(), args.bd.resolve(), out)
    try:
        h.execute()
    except BaseException:
        h.report["harness_error"] = traceback.format_exc()
        h.report["verdict"] = "REJECT"
        h.flush()
        print(h.report["harness_error"], file=sys.stderr)
        return 2
    return 0 if h.report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
