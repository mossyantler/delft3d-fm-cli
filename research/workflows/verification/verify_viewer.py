"""Independent GRAPH-OPS-VIEWER-V contract verifier. No third-party dependencies.

All writes occur below --out. --out must be in this verifier's owned folder.
The TASK.md cwd ambiguity must be resolved before executing this program.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.request

SHA = "03bb993"
BV_HASH = "6ed65731cbee1a4407b360aa0ff00bfe72f7cf13a524bf66c75c6a7db8b381e1"
BD_HASH = "ac5b60114e5e7ef9de8878b45fc35941937341d3447366c99bc91c81557be7a4"
EXPORT = Path("research/notes/delivery/beads-state.jsonl")
PREFIXES = ("BEADS_", "BD_", "BV_", "DFM_")


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def tree(p):
    p = Path(p)
    return {str(f.relative_to(p)): digest(f) for f in sorted(p.rglob("*")) if f.is_file()} if p.exists() else {}


class IO(ctypes.Structure):
    _fields_ = [(x, ctypes.c_ulonglong) for x in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", W.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class EXTENDED(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class OwnedProcess:
    """Assign a suspended child to a retained kill-on-close job before resume."""
    def __init__(self, argv, cwd, env, log):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
        k.CreateJobObjectW.restype = W.HANDLE
        k.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
        k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        k.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
        k.CloseHandle.argtypes = [W.HANDLE]
        self.k = k
        self.job = k.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000
        if not k.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.log = Path(log)
        self.file = self.log.open("wb")
        self.p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                  stdout=self.file, stderr=subprocess.STDOUT,
                                  creationflags=0x4 | 0x08000000)
        if not k.AssignProcessToJobObject(self.job, W.HANDLE(int(self.p._handle))):
            self.p.kill()
            raise ctypes.WinError(ctypes.get_last_error())
        nt = ctypes.WinDLL("ntdll")
        nt.NtResumeProcess.argtypes = [W.HANDLE]
        nt.NtResumeProcess.restype = ctypes.c_long
        if nt.NtResumeProcess(W.HANDLE(int(self.p._handle))) != 0:
            self.stop()
            raise RuntimeError("NtResumeProcess failed")

    def stop(self):
        if self.job:
            if not self.k.TerminateJobObject(self.job, 125):
                raise ctypes.WinError(ctypes.get_last_error())
            self.p.wait(timeout=15)
            self.k.CloseHandle(self.job)
            self.job = None
            self.file.close()

    def finish(self, timeout=60):
        timed_out = False
        try:
            self.p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            self.stop()
        return {"exit": self.p.returncode, "timeout": timed_out, "log": str(self.log),
                "output": self.log.read_text(encoding="utf-8", errors="replace")[-12000:]}


AUDIT = '''import ctypes, json, os, pathlib, runpy, sys
def audit(event, args):
    if event != "subprocess.Popen": return
    executable, argv, cwd, env = args
    if isinstance(argv, str):
        count = ctypes.c_int()
        parse = ctypes.windll.shell32.CommandLineToArgvW
        parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
        pointer = parse(argv, ctypes.byref(count))
        argv = [pointer[i] for i in range(count.value)]
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(pointer)
    executable = executable or argv[0]
    env = os.environ if env is None else env
    path = next((v for k,v in env.items() if k.upper()=="PATH"), "")
    entry = {"executable":str(executable), "argv":list(map(str,argv)), "cwd":str(cwd),
             "special_env":{k:v for k,v in env.items() if k.upper().startswith(("BD_","BEADS_","BV_","DFM_"))},
             "path":path,
             "trackers_on_path":[str(pathlib.Path(p.strip(chr(34)))/n) for p in path.split(os.pathsep) if p for n in ("bd","bd.exe","bd.cmd","bd.bat","bd.com","br","br.exe","br.cmd","br.bat","br.com") if (pathlib.Path(p.strip(chr(34)))/n).is_file()]}
    with open(os.environ["VIEWER_VERIFY_AUDIT"],"a",encoding="utf-8") as f: f.write(json.dumps(entry)+"\\n")
sys.addaudithook(audit)
module = sys.argv.pop(1)
runpy.run_module(module, run_name="__main__")
'''


class Verifier:
    def __init__(self, args):
        self.args = args
        self.owned = Path(__file__).resolve().parent
        self.out = Path(args.out).resolve()
        if not self.out.is_relative_to(self.owned) or self.out == self.owned:
            raise ValueError("--out must be a fresh subfolder of the owned experiment folder")
        self.out.mkdir(parents=True, exist_ok=False)
        self.candidate = Path(args.candidate).resolve()
        if self.candidate.is_file(): self.candidate = self.candidate.parents[3]
        self.bv, self.bd = Path(args.bv).resolve(), Path(args.bd).resolve()
        assert digest(self.bv) == BV_HASH, "resource bv is not pinned"
        assert digest(self.bd) == BD_HASH, "resource bd is not pinned"
        self.base_env = {k:v for k,v in os.environ.items() if not k.upper().startswith(PREFIXES)}
        self.base_env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", GIT_OPTIONAL_LOCKS="0",
                             DFM_BV_EXE=str(self.bv), DFM_BD_EXE=str(self.bd),
                             BV_NO_UPDATE_CHECK="1",
                             TEMP=str(self.out / "temp"), TMP=str(self.out / "temp"))
        (self.out / "temp").mkdir()
        profile = self.out/"profile"
        for key,folder in (("HOME",profile),("USERPROFILE",profile),("APPDATA",profile/"AppData/Roaming"),
                           ("LOCALAPPDATA",profile/"AppData/Local"),("XDG_CONFIG_HOME",profile/"config"),
                           ("XDG_CACHE_HOME",profile/"cache")):
            folder.mkdir(parents=True,exist_ok=True)
            self.base_env[key] = str(folder)
        self.base_env["GIT_CONFIG_GLOBAL"] = str(profile/".gitconfig")
        (profile/".gitconfig").write_text("",encoding="utf-8")
        self.driver = self.out / "audit_driver.py"
        self.driver.write_text(AUDIT, encoding="utf-8")
        self.cases = []
        self.defects = []
        self.counter = 0
        self.manifest = {}
        self.repro = subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), "--candidate", str(self.candidate), "--bv", str(self.bv), "--bd", str(self.bd), "--out", str(self.owned / "reproduce-fresh")])

    def raw(self, argv, cwd=None, env=None, timeout=60):
        self.counter += 1
        cwd = Path(cwd or self.out).resolve()
        assert cwd.is_relative_to(self.out)
        p = OwnedProcess(list(map(str,argv)), cwd, env or self.base_env,
                         self.out / f"command-{self.counter:03}.log")
        result = p.finish(timeout)
        result.update(argv=list(map(str,argv)), cwd=str(cwd))
        write_json(self.out / f"command-{self.counter:03}.json", result)
        return result

    def git(self, cwd, *args):
        r = self.raw(["git", *args], cwd)
        assert r["exit"] == 0 and not r["timeout"], r
        return r["output"].strip()

    def source(self, rel):
        p = subprocess.run(["git", "show", f"{SHA}:{rel}"], cwd=self.candidate,
                           capture_output=True, check=True, env={**os.environ, "GIT_OPTIONAL_LOCKS":"0"})
        self.manifest[rel] = hashlib.sha256(p.stdout).hexdigest()
        return p.stdout

    def fixture(self, name):
        parent = self.out / name
        parent.mkdir()
        repo = parent / "main"
        repo.mkdir()
        self.git(parent, "init", "--bare", str(parent / "origin.git"))
        self.git(repo, "init")
        self.git(repo, "config", "user.email", "verifier@invalid.example")
        self.git(repo, "config", "user.name", "Independent verifier")
        self.git(repo, "config", "core.autocrlf", "false")
        self.git(repo, "remote", "add", "origin", str(parent / "origin.git"))
        for rel in ("research/workflows/__init__.py", "research/workflows/graph/__init__.py",
                    "research/workflows/graph/dashboard.py", "research/workflows/graph/bdw.py"):
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(self.source(rel))
        issues = [{"id":f"verify-{i}", "title":f"Independent issue {i}", "description":f"sentinel-content-{i}",
                   "status":("open","in_progress","closed")[i], "priority":i, "issue_type":"task",
                   "created_at":"2026-11-06T00:00:00Z", "updated_at":"2026-11-06T00:00:00Z"} for i in range(3)]
        p = repo / EXPORT
        p.parent.mkdir(parents=True)
        p.write_text("".join(json.dumps(x)+"\n" for x in issues), encoding="utf-8")
        (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", "test fixture only")
        beads = parent / "main-beads" / ".beads"
        beads.mkdir(parents=True)
        (beads / "untouchable.bin").write_bytes(bytes(range(256)))
        (beads / "nested").mkdir()
        (beads / "nested" / "config.yaml").write_text("sentinel: preserve\n", encoding="utf-8")
        return repo

    def dashboard_root(self, repo):
        return repo.parent / "main-beads" / "dashboard"

    def snapshot(self, repo):
        return {"head":self.git(repo, "rev-parse", "HEAD"),
                "index":digest(repo / ".git/index"),
                "status":self.git(repo, "status", "--porcelain=v1", "-uall"),
                "config":digest(repo / ".git/config"),
                "hooks":tree(repo / ".git/hooks"),
                "export":digest(repo / EXPORT) if (repo / EXPORT).exists() else None,
                "beads":tree(repo.parent / "main-beads" / ".beads")}

    def launch(self, repo, argv, env=None, module="dashboard", wait=True, timeout=60):
        self.counter += 1
        ident = self.counter
        audit = self.out / f"audit-{ident:03}.jsonl"
        child_env = {**self.base_env, "PYTHONPATH":str(repo), "VIEWER_VERIFY_AUDIT":str(audit)}
        if env:
            for k,v in env.items():
                if v is None: child_env.pop(k,None)
                else: child_env[k] = str(v)
        command = [sys.executable, str(self.driver), f"research.workflows.graph.{module}", *argv]
        p = OwnedProcess(command, repo, child_env, self.out / f"command-{ident:03}.log")
        metadata = {"argv":command, "cwd":str(repo), "audit_file":str(audit),
                    "env_overrides":env or {}, "log":str(p.log)}
        if not wait: return p, metadata
        r = p.finish(timeout)
        r.update(metadata)
        r["launches"] = self.audit(audit)
        write_json(self.out / f"command-{ident:03}.json",r)
        return r

    def audit(self, path):
        return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()] if Path(path).exists() else []

    def bv_launches(self, result):
        return [x for x in result.get("launches",[]) if Path(x["executable"]).name.lower() in ("bv.exe", "wrong.exe", "altered.exe")]

    def case(self, ident, contract, polarity, ok, expected, evidence, defect=None):
        item = {"id":ident,"contract":contract,"polarity":polarity,"passed":bool(ok),
                "expected":expected,"evidence_type":"observed behavior","evidence":evidence}
        self.cases.append(item)
        if not ok:
            d = {"id":f"VIEWER-V-{len(self.defects)+1:03}","case":ident,"contract":contract,
                 "summary":defect or expected,"reproducing_command":self.repro,
                 "source_commit":SHA,"source_file":"research/workflows/graph/dashboard.py"}
            self.defects.append(d)
        print(f"{'PASS' if ok else 'FAIL'} {ident}", flush=True)
        write_json(self.out / "partial-cases.json", self.cases)

    def invariance(self, ident, repo, args, env=None, timeout=60):
        before = self.snapshot(repo)
        r = self.launch(repo,args,env,timeout=timeout)
        after = self.snapshot(repo)
        self.case(ident,2,"positive",before==after,"All protected file bytes and Git state remain identical",
                  {"before":before,"after":after,"command":r})
        return r

    def port9000(self, listeners_only=True):
        # netstat sees IPv4 and IPv6 and retains the owning PID for cleanup evidence.
        r = self.raw(["netstat", "-ano"])
        return [line.strip() for line in Path(r["log"]).read_text(encoding="utf-8",errors="replace").splitlines()
                if (not listeners_only or "LISTENING" in line) and len(line.split())>=5
                and line.split()[0]=="TCP" and line.split()[1].endswith(":9000")]

    def address_probes(self):
        """Challenge a wildcard bind using exclusive binds on all local IPv4 addresses."""
        addresses = sorted(set(["127.0.0.1",*socket.gethostbyname_ex(socket.gethostname())[2]]))
        records = []
        for address in addresses:
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                try:
                    s.bind((address,9000))
                    records.append({"address":address,"bind_succeeded":True})
                except OSError as exc:
                    records.append({"address":address,"bind_succeeded":False,"winerror":exc.winerror})
        return records

    def preview(self, repo, label, extra_env=None):
        assert not self.port9000(), "port 9000 already occupied; do not touch existing listener"
        before = self.snapshot(repo)
        p, meta = self.launch(repo,["preview"],extra_env,wait=False)
        bindings, response, error, binding_samples, probes = [], None, None, [], []
        try:
            until = time.monotonic()+20
            while time.monotonic()<until and p.p.poll() is None:
                sample = self.port9000(listeners_only=False)
                binding_samples.append(sample)
                bindings = sorted(set(bindings+sample))
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:9000",timeout=1) as h:
                        response = {"status":h.status,"bytes":len(h.read())}
                    break
                except Exception as exc:
                    error = str(exc)
                    if bindings:
                        break
                    time.sleep(.15)
            bindings = sorted(set(bindings+self.port9000(listeners_only=False)))
            probes = self.address_probes()
        finally:
            p.stop()
        end = self.port9000()
        after = self.snapshot(repo)
        launches = self.audit(meta["audit_file"])
        log = p.log.read_text(encoding="utf-8",errors="replace")
        ev = {**meta,"bindings":bindings,"http":response,"error":error,
              "binding_samples":binding_samples,
              "exclusive_address_probes":probes,
              "after_cleanup":end,"output":log,"launches":launches,
              "before":before,"after":after}
        write_json(self.out / f"{label}-preview.json",ev)
        isolated = any(x["address"]=="127.0.0.1" and not x["bind_succeeded"] and x.get("winerror") in (10013,10048) for x in probes)
        others = [x for x in probes if not x["address"].startswith("127.")]
        isolated = isolated and bool(others) and all(x["bind_succeeded"] for x in others)
        self.case(label+"-preview-loopback",5,"positive",
                  isolated and all(x.split()[1].rsplit(":",1)[0] in ("127.0.0.1","[::1]") for x in bindings),
                  "Preview binds only loopback (HTTP response is a supplementary diagnostic)",ev,
                  "Preview has no exclusively loopback bind or uses a non-loopback address")
        self.case(label+"-preview-unchanged",2,"positive",before==after,"Preview startup preserves all protected state",ev)
        self.case(label+"-preview-cleanup",5,"negative",not end,"No listener remains on port 9000 after owned job shutdown",ev)
        actual_bv = self.bv_launches(ev)
        self.case(label+"-preview-env",3,"positive",bool(actual_bv) and all(
                  x["special_env"]=={"BV_NO_UPDATE_CHECK":"1"} and not x["trackers_on_path"]
                  and Path(x["cwd"])==self.dashboard_root(repo) for x in actual_bv),
                  "Preview receives the restricted environment and dashboard cwd",actual_bv)
        self.case(label+"-preview-argument",6,"positive",bool(actual_bv),"Exactly preview reaches bv",meta)
        return ev

    def run(self):
        baseline_port = self.port9000()
        assert not baseline_port, baseline_port
        repo = self.fixture("worker")
        root = self.dashboard_root(repo)
        version = self.raw([str(self.bv),"--version"],repo)
        self.case("C1-version",1,"positive",version["exit"]==0 and "0.25.2" in version["output"],"Pinned binary reports bv 0.25.2",version)
        good = self.invariance("C2-pages-state",repo,["pages"])
        launches = self.bv_launches(good)
        self.case("C1-genuine",1,"positive",good["exit"]==0 and bool(launches),"Pinned genuine bv executes pages",good)
        self.case("C6-pages",6,"positive",good["exit"]==0,"Exactly pages is accepted",good)
        self.case("C3-clean-launch",3,"positive",bool(launches) and all(
            x["special_env"]=={"BV_NO_UPDATE_CHECK":"1"} and not x["trackers_on_path"]
            and Path(x["cwd"])==root and x["argv"][1:3]==["--db",str(root/"source/issues.jsonl")] for x in launches),
            "Real bv launch has copied database, sanitized environment and dashboard cwd",launches)
        copied = root / "source/issues.jsonl"
        self.case("C4-worker-committed",4,"positive",copied.read_bytes()==(repo/EXPORT).read_bytes(),
                  "Worker copy equals committed export",{"source_sha256":digest(copied),"committed_sha256":digest(repo/EXPORT),"command":good})
        info = json.loads(good["output"])
        self.case("C4-worker-count",4,"positive",info["issues"]==3,"Reported worker issue count equals source",info)
        site = root / "site"
        ids = [json.loads(x)["id"] for x in copied.read_text(encoding="utf-8").splitlines() if x.strip()]
        matches = {i:[str(f.relative_to(site)) for f in site.rglob("*") if f.is_file() and i.encode() in f.read_bytes()] for i in ids}
        with sqlite3.connect((site/"beads.sqlite3").as_uri()+"?mode=ro", uri=True) as db:
            exported_ids = [x[0] for x in db.execute("select id from issues order by id")]
        db.close()
        self.case("C5-pages-every-issue",5,"positive",(site/"index.html").is_file() and all(matches.values()),
                  "site/index.html exists and exported site data contains every issue",{"matches":matches,"database_ids":exported_ids})
        self.case("C5-pages-exact-count",5,"positive",sorted(ids)==exported_ids,"Pages SQLite database contains every source issue including closed issues",exported_ids)
        for name, data in (("wrong.exe",b"not an executable\n"),("altered.exe",self.bv.read_bytes()+b"\0")):
            wrong = self.out / name
            wrong.write_bytes(data)
            before = self.snapshot(repo)
            r = self.launch(repo,["pages"],{"DFM_BV_EXE":str(wrong)})
            self.case("C1-reject-"+name,1,"negative",r["exit"]==2 and "SHA-256" in r["output"] and not self.bv_launches(r) and before==self.snapshot(repo),
                      "Unpinned binary is refused before execution and without protected mutations",r)
        r = self.launch(repo,["pages"],{"DFM_BV_EXE":str(self.out/"missing.exe")})
        self.case("C1-missing",1,"negative",r["exit"]==2 and not self.bv_launches(r),"Missing binary is refused",r)
        poison = self.out / "hostile-tracker-bin"
        poison.mkdir()
        for name in ("bd.exe","br.exe","bd","br"):
            (poison/name).write_bytes(b"tracker trap must not execute")
        env = {"BEADS_TEST":"poison","BD_TEST":"poison","BV_TEST":"poison","DFM_TEST":"poison",
               "BV_NO_UPDATE_CHECK":"0","PATH":str(poison)+os.pathsep+self.base_env.get("PATH","")}
        r = self.invariance("C2-hostile-env-state",repo,["pages"],env)
        launches = self.bv_launches(r)
        self.case("C3-poisoned-env-path",3,"negative",r["exit"]==0 and bool(launches) and all(
                  x["special_env"]=={"BV_NO_UPDATE_CHECK":"1"} and not x["trackers_on_path"] and str(poison) not in x["path"].split(os.pathsep) for x in launches),
                  "Hostile prefix variables and PATH tracker executables are absent in bv",launches)
        scripts = self.out / "tracker-command-scripts"
        scripts.mkdir()
        (scripts/"bd.cmd").write_text("@echo forbidden tracker\n",encoding="ascii")
        (scripts/"br.bat").write_text("@echo forbidden tracker\n",encoding="ascii")
        r = self.launch(repo,["pages"],{"PATH":str(scripts)+os.pathsep+self.base_env.get("PATH","")})
        launches = self.bv_launches(r)
        resolution = self.raw(["where.exe","bd","br"],repo,
                              {**self.base_env,"PATH":launches[0]["path"]}) if launches else None
        self.case("C3-command-script-path",3,"negative",r["exit"]==0 and bool(launches) and all(not x["trackers_on_path"] for x in launches),
                  "PATH entries holding Windows bd/br command scripts are removed",{"viewer_launches":launches,"windows_command_resolution":resolution},
                  "Windows tracker command scripts remain reachable on the viewer PATH")
        before = self.snapshot(repo)
        r = self.launch(repo,["pages"],{"BEADS_DIR":str(self.out/"unrelated-workspace")})
        self.case("C2-refuse-ambient-workspace",2,"negative",r["exit"]==2 and not self.bv_launches(r) and before==self.snapshot(repo),
                  "Mismatched ambient workspace is refused without touching protected state",r)
        dirty = {"id":"verify-dirty","title":"UNCOMMITTED NOT AUTHORITATIVE","status":"open","priority":0,"issue_type":"task"}
        original = (repo/EXPORT).read_bytes()
        (repo/EXPORT).write_text(json.dumps(dirty)+"\n",encoding="utf-8")
        r = self.launch(repo,["pages"])
        self.case("C4-dirty-export",4,"negative",r["exit"]==0 and copied.read_bytes()==original,
                  "Worker uses the committed HEAD export despite uncommitted file edits",
                  {"command":r,"committed_sha256":hashlib.sha256(original).hexdigest(),"actual_source_sha256":digest(copied)},
                  "Worker copies the uncommitted working-tree export rather than the committed export")
        (repo/EXPORT).write_bytes(original)
        (repo/EXPORT).unlink()
        r = self.launch(repo,["pages"])
        self.case("C4-missing-export",4,"negative",r["exit"]==2 and not self.bv_launches(r),"Missing worker export is refused",r)
        (repo/EXPORT).write_bytes(original)
        self.launch(repo,["pages"])
        self.preview(repo,"C5")
        r = self.invariance("C2-tui-state",repo,["tui"],timeout=4)
        self.case("C6-tui",6,"positive",bool(self.bv_launches(r)),"Exactly tui reaches bv startup (pipes are not an interactive terminal)",r)
        launches = self.bv_launches(r)
        self.case("C3-tui-env",3,"positive",bool(launches) and all(x["special_env"]=={"BV_NO_UPDATE_CHECK":"1"}
                  and not x["trackers_on_path"] and Path(x["cwd"])==root for x in launches),
                  "TUI starts with restricted environment and dashboard cwd",launches)
        for i,args in enumerate(([],["help"],["--help"],["PAGES"],["pages","extra"],["preview","--host","0.0.0.0"],["tui","--robot-triage"],["pages; echo injected"],["--export-pages",str(self.out/"escaped")])):
            before = self.snapshot(repo)
            r = self.launch(repo,args)
            self.case(f"C6-reject-{i}",6,"negative",r["exit"]==2 and not self.bv_launches(r) and before==self.snapshot(repo),
                      "Any argument vector other than the three exact single commands is refused",r)
        no_site = self.fixture("missing-site")
        r = self.launch(no_site,["preview"])
        self.case("C5-preview-missing-site",5,"negative",r["exit"]==2 and not self.bv_launches(r),"Preview without built pages is refused",r)
        self.hooks(repo)
        self.coordinator()
        self.author_tests()
        self.case("final-port9000",5,"negative",not self.port9000(),"All preview listeners were stopped",self.port9000())
        return self.report()

    def hooks(self, repo):
        root = self.dashboard_root(repo)
        # Schema and supported event are confirmed by a real unsuppressed control.
        for location, folder in (("dashboard",root),("repository",repo),("parent",repo.parent)):
            hooks = folder / ".bv/hooks.yaml"
            hooks.parent.mkdir(parents=True,exist_ok=True)
            marker = self.out / f"hook-{location}.txt"
            helper = self.out / f"hook-{location}.py"
            helper.write_text("from pathlib import Path\nPath("+repr(str(marker))+").write_text('executed')\n",encoding="utf-8")
            command = subprocess.list2cmdline([sys.executable,str(helper)])
            hooks.write_text("hooks:\n  pre-export:\n    - command: "+json.dumps(command)+"\n  post-export:\n    - command: "+json.dumps(command)+"\n",encoding="utf-8")
            self.raw([str(self.bv),"--db",str(root/"source/issues.jsonl"),"--export-pages",str(self.out/f"hook-control-{location}"),"--pages-include-history=false"],cwd=folder)
            control = marker.exists()
            if control: marker.unlink()
            self.case("C5-hook-control-"+location,5,"positive",control,"Hook trap executes with pinned bv when hooks are not suppressed",{"hooks":str(hooks),"helper":str(helper),"marker":str(marker)})
            r = self.invariance("C2-hook-pages-"+location,repo,["pages"])
            self.case("C5-hooks-pages-"+location,5,"negative",r["exit"]==0 and not marker.exists(),"Dashboard pages never executes installed hooks",r)
            if marker.exists(): marker.unlink()
            r = self.invariance("C2-hook-tui-"+location,repo,["tui"],timeout=3)
            self.case("C5-hooks-tui-"+location,5,"negative",not marker.exists(),"Dashboard TUI startup never executes installed hooks",r)
            if marker.exists(): marker.unlink()
            self.preview(repo,"C5-hook-"+location)
            self.case("C5-hooks-preview-"+location,5,"negative",not marker.exists(),"Dashboard preview startup never executes installed hooks",{"marker":str(marker)})
            hooks.unlink()

    def coordinator(self):
        repo = self.fixture("coordinator")
        # Remove sentinels so genuine bdw can initialize a fresh isolated workspace.
        beads = repo.parent / "main-beads/.beads"
        (beads/"nested/config.yaml").unlink()
        (beads/"nested").rmdir()
        (beads/"untouchable.bin").unlink()
        env = {"DFM_BD_ROLE":"coordinator"}
        init = self.launch(repo,["init-workspace"],env,module="bdw",timeout=90)
        write_json(self.out/"coordinator-init.json",init)
        if init["exit"] != 0:
            self.case("C4-coordinator-initialize",4,"positive",False,"Isolated genuine bd workspace initializes",init)
            return
        create = self.launch(repo,["create","Fresh independent issue","--description","live-coordinator-sentinel","--json"],env,module="bdw",timeout=90)
        assert create["exit"]==0,create
        expected = self.out / "expected-live.jsonl"
        exported = self.launch(repo,["export","-o",str(expected)],env,module="bdw",timeout=90)
        assert exported["exit"]==0,exported
        r = self.invariance("C2-coordinator-pages",repo,["pages"],env,timeout=90)
        source = self.dashboard_root(repo)/"source/issues.jsonl"
        expected_issues = [json.loads(x) for x in expected.read_text(encoding="utf-8").splitlines() if x.strip()]
        actual_issues = [json.loads(x) for x in source.read_text(encoding="utf-8").splitlines() if x.strip()] if source.exists() else []
        self.case("C4-coordinator-fresh",4,"positive",r["exit"]==0 and actual_issues==expected_issues and len(actual_issues)==1,
                  "Coordinator exports the genuine fresh bd workspace and matches its issue count",
                  {"expected":expected_issues,"actual":actual_issues,"command":r})
        self.preview(repo,"C5-coordinator",env)
        self.invariance("C2-coordinator-tui",repo,["tui"],env,timeout=3)
        self.invariance("C2-worker-real-dolt-pages",repo,["pages"])
        self.preview(repo,"C5-worker-real-dolt")
        self.invariance("C2-worker-real-dolt-tui",repo,["tui"],timeout=3)
        bad = self.launch(repo,["pages"],{"DFM_BD_ROLE":"coordinator","DFM_BD_EXE":str(self.out/"wrong.exe")})
        self.case("C4-coordinator-export-failure",4,"negative",bad["exit"]==2 and not self.bv_launches(bad),
                  "Coordinator export failure refuses viewer launch",bad)

    def author_tests(self):
        # Deliberately inspect/run author tests only after the independent matrix.
        repo = self.fixture("author-tests")
        for rel in ("research/workflows/graph/test_dashboard.py","research/workflows/graph/test_bdw.py"):
            (repo/rel).write_bytes(self.source(rel))
        # The author's integration test intentionally uses DEFAULT_BV, not DFM_BV_EXE.
        default_bv = repo/"research/tools/bv/0.25.2/bv.exe"
        default_bv.parent.mkdir(parents=True)
        default_bv.write_bytes(self.bv.read_bytes())
        result = self.raw([sys.executable,"-m","unittest","research.workflows.graph.test_dashboard","-v"],repo,timeout=90)
        self.author = {"derived_cases_from_author_tests":False,"result":result}

    def report(self):
        source = self.source("research/workflows/graph/dashboard.py").decode("utf-8").splitlines()
        anchors = {2:"p = subprocess.run([sys.executable",3:"entries = [p for p",4:"shutil.copyfile(committed, source)",5:'["--preview-pages"'}
        for defect in self.defects:
            anchor = anchors.get(defect["contract"])
            defect["source_line"] = next((n for n,line in enumerate(source,1) if anchor and anchor in line),None)
        report = {"task_code":"GRAPH-OPS-VIEWER-V","candidate_sha":SHA,
                  "verdict":"REJECT" if self.defects else "PASS",
                  "verifier_sha256":digest(__file__),"cases":self.cases,"defects":self.defects,
                  "author_tests":getattr(self,"author",{"executed":False}),
                  "source_manifest":self.manifest,
                  "directory_authorization":"User explicitly approved owned throwaway repositories despite the packet's nested-directory ambiguity.",
                  "coverage":{str(n):{polarity:sum(c["contract"]==n and c["polarity"]==polarity for c in self.cases)
                                      for polarity in ("positive","negative")} for n in range(1,7)},
                  "limitations":["TUI tested through startup with redirected stdin/stdout; full interactive TUI not exercised.",
                                 "HTTP response timings are retained as supplementary diagnostics; contract 5 specifies loopback binding, tested by endpoint tables plus exclusive bind challenges on every local IPv4 interface.",
                                 "All tracker and repository fixtures are disposable; no native Delft3D runs."]}
        write_json(self.out/"verification.json",report)
        write_json(self.owned/"verification.json",report)
        return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate","bv","bd","out"):
        p.add_argument("--"+name,required=True)
    args = p.parse_args()
    verifier = Verifier(args)
    try:
        result = verifier.run()
    except Exception:
        error = traceback.format_exc()
        write_json(verifier.out/"infrastructure-error.json",{"traceback":error})
        verifier.case("infrastructure",0,"negative",False,"Verifier completes all contract cases",{"traceback":error})
        result = verifier.report()
        print(error, file=sys.stderr)
    print(json.dumps({"verdict":result["verdict"],"cases":len(result["cases"]),"defects":len(result["defects"])}))
    return 1 if result["defects"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
