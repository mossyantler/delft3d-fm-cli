"""Independent P0-P6/C1-C5 verifier; stdlib only, all execution/writes owned.

python -B verify_p4.py --candidate WORKTREE --bd BD.EXE --out NEW_CHILD
Contract: 8754727 (P0.3 and P8.7), original base 39273eb.
Historical --reuse-wiring is refused after P8; every verification runs from scratch.
No real Herdr, external Beads, or transcript access.
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
import threading

sys.dont_write_bytecode = True
OWNED = Path(__file__).resolve().parent
BASE_CONTRACT = "39273eb96c08cc1dd3556e4f7b7cb83758aa88cb"
CONTRACT = "14c17264142a8af2305f1cf6c7037e52e421c34e"
BD_HASH = "ac5b60114e5e7ef9de8878b45fc35941937341d3447366c99bc91c81557be7a4"
REL = "research.workflows.graph."


def load(text, fallback=None):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return fallback


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    path = Path(path)
    assert path.resolve().is_relative_to(OWNED), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def meta(issue):
    value = issue.get("metadata") or {}
    return load(value, {}) if isinstance(value, str) else value


def records(obj):
    """Schema-neutral traversal; P4 does not prescribe outer wrapper names."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from records(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from records(value)


def find(obj, ident):
    return next((r for r in records(obj) if r.get("id", r.get("node_id", r.get("beads_id", r.get("dependency")))) == ident
        or ident in [v for v in r.values() if isinstance(v, str)]), {})


def field(obj, name, default=None):
    """Read semantic fields through wrappers; P8.1 permits documented spelling."""
    aliases = {"agent": ("agent", "agent_name", "name"), "pane_id": ("pane_id", "pane"),
        "session_id": ("session_id", "agent_session_id", "session"), "model": ("model", "requested_model"),
        "worktree": ("worktree", "worktree_path"), "receipt_collected": ("receipt_collected", "collected"),
        "task_code": ("task_code", "code")}.get(name, (name,))
    for r in records(obj):
        for key in aliases:
            if key in r:
                return r[key]
    return default


def listed_ids(obj, known):
    result = []
    def visit(value):
        if isinstance(value, str) and value in known and value not in result:
            result.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                visit(v)
        elif isinstance(value, list):
            for v in value:
                visit(v)
    visit(obj)
    return result


def gate_reasons(obj, expected):
    """P8.1 fixes this shape even though other output wrappers are flexible."""
    reasons = (obj or {}).get("reasons")
    return isinstance(reasons, list) and len(reasons) == len(expected) and all(
        isinstance(r, dict) and isinstance(r.get("dependency"), str) and bool(r.get("reason")) for r in reasons
    ) and {r["dependency"] for r in reasons} == set(expected)


def _r2_render(value, template, sent):
    if isinstance(value, str):
        if value == template[:84]:
            return sent[:84]
        if value == template.replace("task packet", "task  packet"):
            return sent.replace("task packet", "task  packet")
        return value.replace(template, sent)
    if isinstance(value, list):
        return [_r2_render(v, template, sent) for v in value]
    if isinstance(value, dict):
        return {k: _r2_render(v, template, sent) for k, v in value.items()}
    return value


FAKE = r'''import json,os,sys
from pathlib import Path
p=Path(os.environ['P4_FAKE_STATE']); log=Path(os.environ['P4_FAKE_LOG'])
s=json.loads(p.read_text(encoding='utf-8')); initial=json.loads(json.dumps(s)); a=sys.argv[1:]
with log.open('a',encoding='utf-8') as f: f.write(json.dumps({'argv':a,'cwd':os.getcwd()})+'\n')
def done(obj,rc=0):
 if s!=initial: p.write_text(json.dumps(s,indent=2),encoding='utf-8')
 print(json.dumps(obj),file=sys.stderr if rc else sys.stdout); raise SystemExit(rc)
def error(msg,code='fixture_error'): done({'error':{'code':code,'message':msg}},1)
def opt(key): return a[a.index(key)+1]
def prompt_rows(value, template, sent):
 if isinstance(value,str):
  if value==template[:84]: return sent[:84]
  if value==template.replace('task packet','task  packet'): return sent.replace('task packet','task  packet')
  return value.replace(template,sent)
 if isinstance(value,list): return [prompt_rows(v,template,sent) for v in value]
 if isinstance(value,dict): return {k:prompt_rows(v,template,sent) for k,v in value.items()}
 return value
def prompt_file(kind,session):
 home=Path(os.environ['DFM_CODEX_HOME' if kind=='codex' else 'DFM_CLAUDE_HOME'])
 return home/'sessions'/'round2'/('rollout-fixture-'+session+'.jsonl') if kind=='codex' else home/'projects'/'round2'/(session+'.jsonl')
def publish_prompt(agent,sent):
 session=(agent.get('agent_session') or {}).get('value')
 if not session: return
 case=s.get('prompt_case') or {}
 if case.get('missing'): return
 kind=agent['kind']; path=prompt_file(kind,session)
 assert path.resolve().is_relative_to(Path(os.environ['P4_ROOT']).resolve())
 path.parent.mkdir(parents=True,exist_ok=True)
 rows=case.get('rows')
 if rows is None:
  rows=[{'type':'event_msg','payload':{'type':'item_completed','item':{'type':'UserMessage','content':[{'type':'text','text':sent}]}}}] if kind=='codex' else [{'type':'user','message':{'content':sent}}]
 else: rows=prompt_rows(rows,case['template_prompt'],sent)
 if case.get('timeline'): rows=prompt_rows(case['timeline_rows'],case['template_prompt'],sent)
 if s.get('truncate_agent')==agent['name']: rows=prompt_rows(rows,sent,sent[:84])
 path.write_text('\n'.join(r if isinstance(r,str) else json.dumps(r) for r in rows)+'\n',encoding='utf-8')
 if case.get('other_session_rows'):
  other=prompt_file(kind,'000-other-session')
  other.write_text('\n'.join(json.dumps(r) for r in prompt_rows(case['other_session_rows'],case['template_prompt'],sent))+'\n',encoding='utf-8')
verb=a[:2]
if verb==['agent','get'] and s.get('unreachable_get_after'):
 s['get_calls']=s.get('get_calls',0)+1
 if s['get_calls']>=s['unreachable_get_after']:
  p.write_text(json.dumps(s,indent=2),encoding='utf-8')
  if s.get('late_error_code'): error('controlled late server failure',s['late_error_code'])
  print('controlled late transport failure',file=sys.stderr); raise SystemExit(1)
if s.get('outage_code'): error('controlled server error',s['outage_code'])
if s.get('non_json'):
 print('controlled non-JSON server reply'); raise SystemExit(0)
if s.get('unreachable') or (s.get('unreachable_agent') and verb==['agent','get'] and a[2]==s['unreachable_agent']):
 print('controlled transport unavailable',file=sys.stderr); raise SystemExit(1)
if s.get('fail')==' '.join(verb) or (s.get('fail_agent') and verb==['agent','start'] and a[2]==s['fail_agent']): error('controlled worker failure')
if verb==['pane','layout']:
 if a[2:]!=['--pane','caller-pane']: error('bad layout protocol')
 width=s.get('width',240)
 done({'id':'cli:pane:layout','result':{'type':'pane_layout','layout':{
  'area':{'height':62,'width':width+400,'x':0,'y':0},'focused_pane_id':'caller-pane',
  'panes':[{'focused':False,'pane_id':'decoy-wide-pane','rect':{'height':62,'width':400,'x':0,'y':0}},
   {'focused':True,'pane_id':'caller-pane','rect':{'height':62,'width':width,'x':400,'y':0}}],
  'splits':[],'tab_id':'fixture-tab','workspace_id':'fixture-workspace','zoomed':False}}})
if verb==['pane','split']:
 if a[2]!='caller-pane' or '--no-focus' not in a or opt('--direction') not in ('right','down'): error('bad split protocol')
 s['counter']+=1; pane='fixture-pane-'+str(s['counter']); s['panes'][pane]={'pane_id':pane,'cwd':opt('--cwd')}
 done({'result':{'pane':s['panes'][pane]}})
if verb==['agent','start']:
 if '--' not in a or opt('--pane') not in s['panes']: error('bad start protocol')
 name=a[2]; mode=s.get('submit','normal')
 preexisting=mode in ('retry','never','seq','screen','rotate')
 s['agents'][name]={'name':name,'pane_id':opt('--pane'),'agent_status':'idle',
  'kind':opt('--kind'),'agent_session':{'value':'session-'+name if preexisting and not s.get('session_never') else None},'state_change_seq':0}
 done({'result':{'agent':s['agents'][name]}})
if verb==['agent','list']: done({'result':{'agents':list(s['agents'].values())}})
if verb==['pane','list']: done({'result':{'panes':list(s['panes'].values())}})
if verb==['agent','get']:
 if a[2] not in s['agents']: error('agent absent','agent_not_found')
 done({'result':{'agent':s['agents'][a[2]]}})
if verb==['agent','read']:
 if len(a)!=5 or a[3:]!=['--source','visible']: error('bad visible-read protocol')
 if a[2] not in s['agents']: error('agent absent','agent_not_found')
 # Coordinator-reported Herdr 0.9.5 behavior: raw stdout, NOT JSON.
 print(s.get('screens',{}).get(a[2],'')); raise SystemExit(0)
if verb in (['agent','prompt'],['agent','send-keys']):
 if a[2] not in s['agents']: error('agent absent','agent_not_found')
 agent=s['agents'][a[2]]
 mode=s.get('submit','normal')
 if verb==['agent','prompt']:
  if len(a)!=4: error('bad prompt protocol')
  s.setdefault('prompts',[]).append(a[3])
  s['last_prompt_agent']=a[2]
  s.setdefault('screens',{})[a[2]]=s.get('visible_text','') if mode=='screen' else ''
  if mode!='empty' and not s.get('session_never'): agent['agent_session']={'value':('new-session-' if mode=='rotate' else 'session-')+a[2]}
  publish_prompt(agent,a[3])
 ack=(mode in ('normal','seq') or (mode=='retry' and verb==['agent','send-keys']))
 if ack:
  agent['state_change_seq']+=1
  agent['agent_status']='idle' if mode=='seq' else 'working'
 done({'result':{'submitted':ack}})
if verb==['pane','close']:
 pane=a[2]; s['panes'].pop(pane,None)
 for name in list(s['agents']):
  if s['agents'][name]['pane_id']==pane: del s['agents'][name]
 done({'result':{'closed':pane}})
error('unsupported fake protocol: '+repr(a))
'''

# Applies only in subprocesses. Candidate workflow sources themselves are copied
# into owned output. This guard also protects nested bdw and author-test calls.
OBSERVER = r'''import inspect,json,os,subprocess,sys
from pathlib import Path
if os.environ.get('P4_GUARD')=='1':
 def transcript_read(event,args):
  log=os.environ.get('P4_PROMPT_READ_LOG')
  if event!='open' or not log or not args or not isinstance(args[0],str): return
  mode=args[1] if len(args)>1 else None
  if not isinstance(mode,str) or 'r' not in mode: return
  path=Path(args[0]).resolve()
  homes=[Path(os.environ[k]).resolve() for k in ('DFM_CODEX_HOME','DFM_CLAUDE_HOME') if os.environ.get(k)]
  if path.suffix=='.jsonl' and any(path.is_relative_to(h) for h in homes):
   with open(log,'a',encoding='utf-8') as f: f.write(json.dumps({'path':str(path)})+'\n')
 sys.addaudithook(transcript_read)
 original=subprocess.Popen.__init__
 def guarded(self,args,*pos,**kw):
  a=list(map(str,args)) if isinstance(args,(list,tuple)) else [str(args)]
  env=kw.get('env') or os.environ; root=Path(os.environ['P4_ROOT']).resolve()
  cwd=Path(kw.get('cwd') or os.getcwd()).resolve(); exe=Path(a[0]).name.lower()
  stack=[str(x.filename).replace('\\','/') for x in inspect.stack()]
  via=any(x.endswith('/research/workflows/graph/bdw.py') for x in stack)
  allowed=exe.startswith(('python','git')) or exe in ('bd.exe','fake-herdr.cmd','fake-herdr','cmd.exe','cmd')
  safe=cwd.is_relative_to(root) and allowed
  if exe=='bd.exe':
   safe=safe and Path(a[0]).resolve()==Path(os.environ['DFM_BD_EXE']).resolve()
   db=env.get('BEADS_DIR',''); safe=safe and bool(db) and Path(db).resolve().is_relative_to(root)
  if 'herdr' in exe and not exe.startswith('fake-herdr'): safe=False
  # External -C/--git-dir are never legitimate in child candidate/test processes.
  if exe.startswith('git'):
   for i,x in enumerate(a):
    target=a[i+1] if x in ('-C','--git-dir','--work-tree') and i+1<len(a) else x.split('=',1)[1] if x.startswith(('--git-dir=','--work-tree=')) else None
    if target and not (cwd/target).resolve().is_relative_to(root): safe=False
  event={'argv':a,'cwd':str(cwd),'safe':bool(safe),'via_bdw':via,'beads_dir':env.get('BEADS_DIR')}
  with open(os.environ['P4_PROCESS_LOG'],'a',encoding='utf-8') as f: f.write(json.dumps(event)+'\n')
  if not safe: raise RuntimeError('P4 verifier blocked unsafe subprocess '+repr(event))
  return original(self,args,*pos,**kw)
 subprocess.Popen.__init__=guarded
'''


class Harness:
    def __init__(self, candidate, bd, out, reuse_wiring=None):
        self.candidate, self.bd, self.out = candidate, bd, out
        self.reuse_wiring = reuse_wiring
        self.calls, self.cases, self.defects = [], [], []
        self.repro = subprocess.list2cmdline([sys.executable, "-B", str(Path(__file__).resolve()),
            "--candidate", str(candidate), "--bd", str(bd), "--out", str(OWNED / "reproduce-NEW")])
        self.report = {"task_code": "GRAPH-OPS-P4-PARALLEL-V-Run", "contract_sha": CONTRACT,
            "base_contract_sha": BASE_CONTRACT, "scope": "P0-P6 and focused C1-C5; historical frozen verifiers and G live trials separate",
            "candidate_sha": None, "verdict": "REJECT", "verifier_sha256": digest(__file__),
            "plan_sha256": digest(OWNED / "r2-PLAN.md"), "cases": self.cases, "defects": self.defects,
            "author_tests": {}, "evidence_kind": "observed behavior", "calls": "calls.json",
            "ambiguities": [], "ambiguities_resolved_by": "P8 at " + CONTRACT,
            "limitations": ["Fake Herdr and fixture transcripts only; G live trials remain separate.",
                "No Delft3D syntax/references/semantics/initialization/simulation/scientific validity validation.",
                "Frozen historical verifiers require outside-scope ignored resources and pin adaptations; planned for V-Run."]}
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith(
            ("BD_", "BEADS_", "DFM_", "GIT_", "HERDR_", "CODEX_", "CLAUDE_", "DOLT_", "ONEDRIVE"))}
        for name in ("profile", "tmp", "bin", "observer", "codex", "claude", "source"):
            (out / name).mkdir()
        profile = out / "profile"
        self.env.update({"HOME": str(profile), "USERPROFILE": str(profile), "APPDATA": str(profile / "roaming"),
            "LOCALAPPDATA": str(profile / "local"), "XDG_CONFIG_HOME": str(profile / "config"),
            "XDG_CACHE_HOME": str(profile / "cache"), "TEMP": str(out / "tmp"), "TMP": str(out / "tmp"),
            "DFM_BD_EXE": str(bd), "DFM_BD_ROLE": "coordinator", "DFM_BEADS_BACKUP": str(out / "backup"),
            "DFM_CODEX_HOME": str(out / "codex"), "DFM_CLAUDE_HOME": str(out / "claude"),
            "DFM_DISPATCH_SUBMIT_SECONDS": "0.1", "HERDR_ENV": "1", "HERDR_PANE_ID": "caller-pane",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
            "GIT_CEILING_DIRECTORIES": str(out), "P4_ROOT": str(out),
            "P4_PROCESS_LOG": str(out / "process.jsonl"),
            **{k: "1" for k in ("BD_NON_INTERACTIVE", "BD_DISABLE_METRICS", "BD_NO_INSTALL_HOOKS", "BD_NO_REMOTE_ADOPT")}})
        self.source = out / "source"
        self.env["PYTHONPATH"] = os.pathsep.join((str(out / "observer"), str(self.source)))
        (out / "observer/sitecustomize.py").write_text(OBSERVER, encoding="utf-8")
        (out / "fake_herdr.py").write_text(FAKE, encoding="utf-8")
        shim = out / "bin/fake-herdr.cmd"
        shim.write_text('@echo off\r\n"' + sys.executable + '" -B "' + str(out / "fake_herdr.py") + '" %*\r\n', encoding="utf-8")
        (out / "bin/herdr.cmd").write_text('@echo off\r\necho {"error":"real Herdr blocked"} 1>&2\r\nexit /b 93\r\n', encoding="ascii")
        self.env["PATH"] = str(out / "bin") + os.pathsep + self.env.get("PATH", "")
        self.env["DFM_HERDR_EXE"] = str(shim)
        self.repo = out
        self.group_no = 0
        # Retain exact executable verifier bytes, including interrupted attempts.
        (out / "verifier-source.py").write_bytes(Path(__file__).read_bytes())
        (out / "plan-source.md").write_bytes((OWNED / "r2-PLAN.md").read_bytes())
        self.flush()

    def flush(self):
        self.report["counts"] = {"total": len(self.cases), "passed": sum(x["pass"] for x in self.cases),
            "failed": sum(not x["pass"] for x in self.cases)}
        write(self.out / "calls.json", self.calls)
        write(self.out / "verification.json", self.report)

    def case(self, ident, clause, expected, passed, observed=None, diagnostic=False):
        item = {"id": ident, "contract": clause, "expected": expected, "pass": bool(passed),
            "diagnostic": diagnostic, "observed": observed, "source_commit": self.report["candidate_sha"],
            "evidence_kind": "observed behavior", "reproducing_command": self.repro}
        self.cases.append(item)
        if not passed and not diagnostic:
            self.defects.append({"case_id": ident, "contract": clause, "summary": expected,
                "reproducing_command": self.repro, "evidence": observed})
        self.flush()
        print(("PASS " if passed else "DIAG " if diagnostic else "FAIL ") + ident, flush=True)

    def run(self, argv, cwd=None, extra=None, check=False, timeout=90):
        cwd = Path(cwd or self.repo).resolve()
        assert cwd.is_relative_to(self.out), cwd
        env = dict(self.env)
        for k, v in (extra or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = str(v)
        start = time.monotonic()
        try:
            p = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout)
            rc, stdout, stderr = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as exc:
            rc, stdout, stderr = -999, str(exc.stdout or ""), str(exc.stderr or "")
        r = {"call_id": len(self.calls), "argv": list(map(str, argv)), "cwd": str(cwd),
            "environment_overrides": {k: None if v is None else str(v) for k, v in (extra or {}).items()},
            "exit": rc, "stdout": stdout, "stderr": stderr, "seconds": round(time.monotonic() - start, 3)}
        self.calls.append(r)
        if check and rc:
            raise RuntimeError("Fixture command failed: " + repr(r))
        return r

    def git(self, *args, cwd=None):
        return self.run(["git", "-c", "user.name=Independent verifier", "-c",
            "user.email=verifier@example.invalid", *args], cwd=cwd, check=True)["stdout"].strip()

    def bdw(self, *args, check=True):
        return self.run([sys.executable, "-B", "-m", REL + "bdw", *map(str, args)],
            extra={"P4_GUARD": "1"}, check=check)

    def issue(self, ident):
        return load(self.bdw("show", ident, "--json")["stdout"])[0]

    def comments(self, ident):
        return load(self.bdw("comments", ident, "--json")["stdout"])

    def setmeta(self, f, **changes):
        m = meta(self.issue(f["id"]))
        m.update(changes)
        self.bdw("update", f["id"], "--metadata", json.dumps(m))

    def state(self, **changes):
        s = load(self.statefile.read_text(encoding="utf-8"))
        s.update(changes)
        write(self.statefile, s)
        return s

    def lines(self, path):
        return [load(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def group(self, label):
        self.group_no += 1
        self.root = self.out / ("fixture-%02d-" % self.group_no + label)
        self.root.mkdir()
        self.repo, self.origin = self.root / "project", self.root / "origin.git"
        self.statefile, self.logfile = self.root / "fake.json", self.root / "fake.jsonl"
        write(self.statefile, {"counter": 0, "agents": {}, "panes": {}, "prompts": []})
        self.env.update(P4_FAKE_STATE=str(self.statefile), P4_FAKE_LOG=str(self.logfile))
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.out)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.out)
        (self.repo / "research/experiments").mkdir(parents=True)
        (self.repo / "AGENTS.md").write_text("Owned disposable fixture.\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("research/experiments/\n", encoding="utf-8")
        self.git("add", "AGENTS.md", ".gitignore")
        self.git("commit", "-q", "-m", "fixture old base")
        self.old = self.git("rev-parse", "HEAD")
        (self.repo / "data.txt").write_text("baseline\n", encoding="utf-8")
        self.git("add", "data.txt")
        self.git("commit", "-q", "-m", "fixture dispatch base")
        self.head = self.git("rev-parse", "HEAD")
        # Create a known unrelated commit without touching the checked-out branch.
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.orphan = self.git("commit-tree", tree, "-m", "unrelated fixture")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("--git-dir", str(self.origin), "fetch", "-q", str(self.repo), "main:main")
        self.bdw("init-workspace")
        (self.repo / "data.txt").write_text("dirty main sentinel\n", encoding="utf-8")
        (self.repo / "staged.txt").write_text("staged sentinel\n", encoding="utf-8")
        self.git("add", "staged.txt")
        self.nodes = []

    def new(self, label, status="open", dispatch=False, live=False, priority=2, plan=False, kind="task", **dispatch_values):
        code = "P4-" + label
        packet = self.repo / "research/experiments" / (code + ".md")
        packet.write_text("Read AGENTS.md. Execute this fixture in English.\n", encoding="utf-8")
        name = "v-" + label.lower()
        wt = self.root / "project-wt" / code
        rec = {"agent": name, "pane_id": "pane-" + label, "kind": "codex", "model": "fixture-model",
            "effort": "high", "session_id": "session-" + name, "worktree": str(wt),
            "base_sha": self.head, "packet": packet.relative_to(self.repo).as_posix(),
            "packet_sha256": digest(packet), "started_at": "2026-11-06T00:00:00Z", "attempt": 1,
            "owned_paths": [], "native": False, "approved": None, **dispatch_values}
        m = {"task_code": code, "sentinel": {"unknown": [1, "preserve"]}}
        if dispatch:
            m["dispatch"] = rec
        if plan:
            m["plan"] = {"packet": str(packet), "kind": "codex", "model": "fixture-model", "effort": "high", "name": name}
        r = self.bdw("create", code + ": independent fixture", "-t", kind, "-p", priority,
            "--silent", "--metadata", json.dumps(m))
        ident = r["stdout"].strip().splitlines()[-1]
        f = {"id": ident, "code": code, "packet": packet, "name": name, "wt": wt, "record": rec}
        self.nodes.append(f)
        if status != "open":
            self.bdw("update", ident, "--status", status)
        if live:
            s = self.state()
            s["panes"][rec["pane_id"]] = {"pane_id": rec["pane_id"], "cwd": str(wt)}
            s["agents"][name] = {"name": name, "pane_id": rec["pane_id"], "agent_status": "working",
                "agent_session": {"value": rec["session_id"]}, "state_change_seq": 1}
            write(self.statefile, s)
        return f

    def args(self, f, **options):
        defaults = {"packet": str(f["packet"]), "kind": "codex", "model": "fixture-model", "effort": "high", "name": f["name"]}
        defaults.update(options)
        args = ["start", f["id"]]
        for key, value in defaults.items():
            if value is None or value is False:
                continue
            if value is True:
                args += ["--" + key.replace("_", "-")]
            elif isinstance(value, list):
                for item in value:
                    args += ["--" + key.replace("_", "-"), str(item)]
            else:
                args += ["--" + key.replace("_", "-"), str(value)]
        return args

    def snapshot(self):
        return {"head": self.git("rev-parse", "HEAD"), "status": self.git("status", "--porcelain=v1", "-uall"),
            "index": digest(self.repo / ".git/index"), "config": digest(self.repo / ".git/config"),
            "files": {str(p.relative_to(self.repo)): digest(p) for p in self.repo.rglob("*") if p.is_file() and ".git" not in p.relative_to(self.repo).parts},
            "refs": self.git("--git-dir", str(self.origin), "for-each-ref", "--format=%(refname) %(objectname)")}

    def graph(self):
        # Export contains all issue fields, dependencies and complete comment
        # bodies. One bdw call avoids O(nodes) database startups per observation.
        path = self.root / ("graph-snapshot-%04d.jsonl" % len(self.calls))
        self.bdw("export", "-o", path)
        result = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            obj = load(line, {})
            if obj.get("_type", "issue") == "issue" and obj.get("id"):
                comments = obj.pop("comments", [])
                result[obj["id"]] = {"issue": obj, "comments": comments}
        return result

    def invoke(self, args, extra=None):
        before = self.snapshot()
        offset = len(self.lines(self.logfile))
        r = self.run([sys.executable, "-B", "-m", REL + "dispatch", *map(str, args)],
            extra={"P4_GUARD": "1", **(extra or {})})
        r["json"], r["error_json"] = load(r["stdout"]), load(r["stderr"])
        r["fake_calls"] = self.lines(self.logfile)[offset:]
        r["main_unchanged"] = before == self.snapshot()
        protocol = self.success(r) or self.refused(r) or (r["exit"] == 2 and isinstance(r["error_json"], dict) and "error" in r["error_json"] and not r["stdout"].strip())
        self.case("protocol-%d" % r["call_id"], "C3/C4.3", "Single JSON protocol; main Git/files/origin unchanged", protocol and r["main_unchanged"], r)
        return r

    @staticmethod
    def success(r):
        return r["exit"] == 0 and isinstance(r["json"], dict) and not r["stderr"].strip()

    @staticmethod
    def refused(r, reason=None):
        e = r.get("error_json")
        return r["exit"] == 2 and isinstance(e, dict) and "refused" in e and not r["stdout"].strip() and (reason is None or reason in json.dumps(e))

    def reject(self, ident, clause, f, options=None, reason=None, extra=None, diagnostic=False, mentions=()):
        before = self.graph()
        state = self.statefile.read_bytes()
        worktrees = self.git("worktree", "list", "--porcelain")
        r = self.invoke(self.args(f, **(options or {})), extra)
        unchanged = before == self.graph() and state == self.statefile.read_bytes() and worktrees == self.git("worktree", "list", "--porcelain")
        no_start = not any(c["argv"][:2] in (["pane", "split"], ["agent", "start"], ["agent", "prompt"]) for c in r["fake_calls"])
        self.case(ident, clause, "Refuse before side effects" + (": " + reason if reason else ""),
            self.refused(r, reason) and unchanged and no_start and all(x in r["stderr"] for x in mentions),
            {"call": r, "graph_fake_worktrees_unchanged": unchanged}, diagnostic)
        return r

    def accept(self, ident, clause, f, options=None, extra=None, check=None):
        r = self.invoke(self.args(f, **(options or {})), extra)
        issue = self.issue(f["id"])
        d = meta(issue).get("dispatch", {})
        ok = self.success(r) and issue["status"] == "in_progress" and f["wt"].is_dir()
        if check:
            ok = ok and check(r, issue, d)
        self.case(ident, clause, "Start succeeds with specified provenance", ok, {"call": r, "issue": issue})
        return r

    def inactive(self, f):
        self.bdw("update", f["id"], "--status", "closed")

    def prepare(self):
        assert digest(self.bd) == BD_HASH, "Unexpected bd executable hash"
        self.report["bd_sha256"] = digest(self.bd)
        self.report["candidate_sha"] = self.git("-C", str(self.candidate), "rev-parse", "HEAD", cwd=self.out)
        self.initial_status = self.git("-C", str(self.candidate), "status", "--porcelain=v1", "-uall", cwd=self.out)
        docs = {}
        for label, sha in (("original", BASE_CONTRACT), ("amended", CONTRACT)):
            doc = self.git("-C", str(self.candidate), "show", sha + ":research/notes/delivery/graph-ops-p4-parallel.md", cwd=self.out)
            (self.out / ("contract-" + label + ".md")).write_text(doc + "\n", encoding="utf-8")
            docs[label] = doc
        self.unchanged_p1_p6 = docs["original"].split("## P1.", 1)[1].split("## P7.", 1)[0] == docs["amended"].split("## P1.", 1)[1].split("## P7.", 1)[0]
        self.report["p1_p6_contract_unchanged"] = self.unchanged_p1_p6
        self.manifest = {}
        # Copy exact bytes, never import from or compile into the supplied worktree.
        for p in sorted((self.candidate / "research/workflows").rglob("*.py")):
            relative = p.relative_to(self.candidate)
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
            self.manifest[str(relative)] = digest(p)
        for relative in ("research/__init__.py",):
            p = self.candidate / relative
            if p.is_file():
                target = self.source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(p.read_bytes())
        self.report["source_manifest"] = self.manifest
        self.report["dispatch_docstring"] = ast.get_docstring(ast.parse(
            (self.source / "research/workflows/graph/dispatch.py").read_text(encoding="utf-8"))) or ""
        self.case("P8-output-documentation", "P8.1", "Module docstring documents resources/status/review output values",
            all(word in self.report["dispatch_docstring"].lower() for word in
                ("owned", "native", "approved", "status", "receipt", "live", "review", "dirty", "session", "model")),
            {"file": "research/workflows/graph/dispatch.py:1", "docstring": self.report["dispatch_docstring"]})
        self.report["frozen_regressions"] = {name: {"status": "planned-for-V-Run; historical resources/pins required" if (self.source / "research/workflows/verification" / name).is_file() else "unavailable-in-supplied-base",
            "sha256": self.manifest.get(str(Path("research/workflows/verification") / name))}
            for name in ("verify_dispatch.py", "verify_codefix.py", "verify_livefix.py")}
        self.flush()

    def reuse_prior(self):
        raise ValueError("P8 changes prior expectations; --reuse-wiring is disabled. Run V-Run from scratch.")

    def p0_cases(self):
        self.group("p0-layout")
        # Exercise the fake protocol directly: old bases never call these APIs.
        self.state(width=61)
        r = self.run([self.env["DFM_HERDR_EXE"], "pane", "layout", "--pane", "caller-pane"])
        panes = (load(r["stdout"], {}).get("result", {}).get("layout", {}).get("panes", []))
        self.case("P0-fake-layout-envelope", "Harness/P0", "Fake layout has coordinator-supplied JSON shape and caller width", r["exit"] == 0
            and next((x["rect"]["width"] for x in panes if x["pane_id"] == "caller-pane"), None) == 61, r)
        s = self.state()
        s["agents"]["protocol-probe"] = {"name": "protocol-probe", "pane_id": "probe-pane", "agent_status": "idle", "agent_session": {"value": "probe-session"}}
        s["screens"] = {"protocol-probe": "Working (0s)"}
        write(self.statefile, s)
        r = self.run([self.env["DFM_HERDR_EXE"], "agent", "read", "protocol-probe", "--source", "visible"])
        self.case("P0-fake-visible-plain-text", "Harness/P0", "Fake visible read returns raw text, not JSON", r["exit"] == 0
            and r["stdout"].strip() == "Working (0s)" and load(r["stdout"]) is None, r)
        for width in (30, 61, 119, 120, 121, 240, None):
            label = "Failure" if width is None else str(width)
            f = self.new("P0Width" + label)
            self.state(width=width or 240, fail="pane layout" if width is None else None)
            r = self.invoke(self.args(f))
            expected = "right" if width is not None and width >= 120 else "down"
            d = meta(self.issue(f["id"])).get("dispatch", {})
            layouts = [x["argv"] for x in r["fake_calls"] if x["argv"][:2] == ["pane", "layout"]]
            splits = [x["argv"] for x in r["fake_calls"] if x["argv"][:2] == ["pane", "split"]]
            direction = splits[0][splits[0].index("--direction") + 1] if splits and "--direction" in splits[0] else None
            self.case("P0-width-" + label, "P0.1", "Caller width/layout failure selects and records " + expected,
                self.success(r) and layouts == [["pane", "layout", "--pane", "caller-pane"]] and direction == expected and d.get("split_direction") == expected, {"call": r, "dispatch": d})
            self.inactive(f)
        self.group("p0-turns")
        samples = [("SessionOnly", "session", "", True), ("VisibleEsc", "screen", "status: esc to interr...", True),
            ("VisibleWorking", "screen", "Working (0s)", True), ("ExistingSession", "never", "", False),
            ("RotatedSession", "rotate", "", False), ("AlwaysNull", "empty", "", False),
            ("TruncatedText", "screen", "Working; esc to int", False)]
        for label, mode, screen, accepted in samples:
            f = self.new("P0" + label)
            self.state(submit=mode, visible_text=screen, width=61)
            before = self.graph()
            prior_panes = set(self.state()["panes"])
            r = self.invoke(self.args(f))
            enters = [x["argv"] for x in r["fake_calls"] if x["argv"][:2] == ["agent", "send-keys"]]
            reads = [x["argv"] for x in r["fake_calls"] if x["argv"][:2] == ["agent", "read"]]
            if accepted:
                ok = self.success(r) and r["json"].get("submit_retry") is False and not enters
                if mode == "screen":
                    ok = ok and bool(reads) and all(x == ["agent", "read", f["name"], "--source", "visible"] for x in reads)
            else:
                ok = r["exit"] == 2 and isinstance(r["error_json"], dict) and bool(set(r["error_json"]) & {"error", "refused"})
                ok = ok and enters == [["agent", "send-keys", f["name"], "enter"]] and before == self.graph()
                ok = ok and not f["wt"].exists() and f["name"] not in self.state()["agents"] and set(self.state()["panes"]) == prior_panes
            self.case("P0-turn-" + label, "P0.2/C5.1", "Independent turn signal accepted without retry" if accepted else "Insufficient evidence retries once then cleans up without graph writes", ok, r)
            self.inactive(f)

    def ownership_and_limits(self):
        self.group("parallel")
        a, b, c = [self.new(x) for x in ("One", "Two", "Three")]
        self.accept("parallel-first", "P1/P2", a,
            check=lambda r, i, d: d.get("owned_paths") == [] and d.get("native") is False and "approved" in d and d["approved"] is None)
        self.accept("parallel-second", "P2", b, {"kind": "claude"})
        s = self.state()
        ds = [meta(self.issue(x["id"])).get("dispatch", {}) for x in (a, b)]
        self.case("parallel-overlap", "P2", "Two working agents with different worktrees/panes/sessions", len(s["agents"]) == 2 and all(x["agent_status"] == "working" for x in s["agents"].values()) and all(len({d.get(k) for d in ds}) == 2 for k in ("pane_id", "session_id", "worktree")), s)
        self.reject("parallel-third-default-limit", "P2.1", c)
        self.accept("limit-cli-overrides-env", "P2.1", c, {"max_parallel": 3}, {"DFM_DISPATCH_MAX_PARALLEL": "1"})
        self.group("preflight")
        active = self.new("Active", status="in_progress", dispatch=True, owned_paths=["research/a"], native=True)
        f = self.new("Next")
        self.reject("limit-env", "P2.1", f, extra={"DFM_DISPATCH_MAX_PARALLEL": "1"})
        for value in ("0", "-1", "1.5", "no"):
            self.reject("limit-invalid-" + value, "P2.1", f, {"max_parallel": value})
        for paths in (["research/a"], ["research/a/file.py"], ["research"]):
            self.reject("ownership-" + paths[0], "P2.2", f, {"owns": paths, "max_parallel": 10}, "ownership_conflict", mentions=(active["id"], "research/a", paths[0]))
        self.reject("native-busy", "P2.3", f, {"native": True, "max_parallel": 10}, "native_busy")
        self.accept("ownership-boundary-nonnative", "P1/P2.2/P2.3", f, {"owns": ["research/ab", "z\\file.py", "a"], "max_parallel": 10},
            check=lambda r, i, d: d.get("owned_paths") == ["a", "research/ab", "z/file.py"])
        self.inactive(f)
        ended = dict(active["record"], ended_at="2026-11-06T00:01:00Z")
        self.setmeta(active, dispatch=ended)
        f = self.new("AfterEnded")
        self.accept("ended-resources-free", "P2.1/P2.2/P2.3", f, {"owns": ["research/a"], "native": True, "max_parallel": 1})
        self.group("paths")
        for n, path in enumerate(("", "../a", "a/../b", "a//b", "/root", "C:\\root", "a\\..\\b", "a/", ".", "a/./b", "a\\", "a\\\\b")):
            f = self.new("Path" + str(n))
            self.reject("path-invalid-" + str(n), "P1/P8.2", f, {"owns": [path]})
        f = self.new("Explicit")
        self.accept("explicit-native-approval", "P1", f, {"owns": ["b", "a"], "native": True, "approved": "HUMAN-20261106-7"},
            check=lambda r, i, d: d.get("owned_paths") == ["a", "b"] and d.get("native") is True and d.get("approved") == "HUMAN-20261106-7")
        self.inactive(f)
        self.new("LowercaseOwner", status="in_progress", dispatch=True, owned_paths=["a"])
        f = self.new("UppercaseAndDuplicates")
        self.accept("P8-case-sensitive-deduplicated-paths", "P8.2", f,
            {"owns": ["A", "A", "dir\\file", "dir/file"]},
            check=lambda r, i, d: d.get("owned_paths") == ["A", "dir/file"])

    def model_policy(self):
        self.group("models")
        for n, effort in enumerate(("low", "medium", "high")):
            f = self.new("Effort" + str(n))
            self.accept("effort-" + effort, "P2.4", f, {"effort": effort})
            self.inactive(f)
        for n, effort in enumerate(("", "xhigh", "HIGH", "maximum")):
            f = self.new("InvalidEffort" + str(n))
            self.reject("effort-refuse-" + effort, "P2.4", f, {"effort": effort})
            self.inactive(f)
        for n, (model, approval) in enumerate((("vendor-ASTRA-1", None), ("vendor-OpUs-2", None),
                ("opus", "HUMAN-20261106"), ("astra", "human-20261106-1"), ("opus", "HUMAN-20261106-1-extra"))):
            f = self.new("InvalidPremium" + str(n))
            self.reject("premium-refuse-" + str(n), "P2.4", f, {"model": model, "approved": approval})
            self.inactive(f)
        f = self.new("ApprovedPremium")
        self.accept("premium-approved", "P2.4", f, {"model": "vendor-OpUs-2", "approved": "HUMAN-20261106-15"})

    def predecessor_and_gate(self):
        self.group("predecessors")
        f = self.new("Dependent")
        p = self.new("Predecessor", status="closed", dispatch=True)
        self.bdw("dep", "add", f["id"], p["id"])
        self.reject("predecessor-missing", "P2.5", f, reason="missing_receipt")
        self.inactive(f)
        for n, receipt in enumerate(({"verdict": "REJECT"}, {"verdict": "FAIL"},
                {"verdict": "PASS", "outcome": "numeric FAILure"}, {"verdict": "PASS", "outcome": "was ReJeCtEd"},
                {"outcome": "FAIL"}, {"outcome": "was rejected"})):
            f = self.new("FailedDependent" + str(n))
            self.bdw("dep", "add", f["id"], p["id"])
            self.setmeta(p, receipt=receipt)
            self.reject("predecessor-failed-" + str(n), "P2.5", f, reason="failed_predecessor")
            self.inactive(f)
        self.setmeta(p, receipt={"verdict": "PASS", "outcome": "accepted"})
        f = self.new("PassDependent")
        self.bdw("dep", "add", f["id"], p["id"])
        self.accept("predecessor-pass", "P2.5", f)
        self.inactive(f)
        for n, receipt in enumerate(({}, {"outcome": "completed"}, {"verdict": None}, {"verdict": None, "outcome": "completed"})):
            self.setmeta(p, receipt=receipt)
            f = self.new("OmittedVerdictDependent" + str(n))
            self.bdw("dep", "add", f["id"], p["id"])
            self.accept("P87-predecessor-no-verdict-" + str(n), "P8.7", f)
            self.inactive(f)
        for n, dep_type in enumerate(("blocks", "conditional-blocks", "waits-for")):
            f = self.new("Typed" + str(n))
            self.bdw("dep", "add", f["id"], p["id"], "--type", dep_type)
            self.setmeta(p, receipt={"verdict": "REJECT"})
            self.reject("typed-blocker-" + dep_type, "P2.5", f, reason="failed_predecessor")
            self.inactive(f)
        self.group("gates")
        target = self.new("Gate")
        before = self.graph()
        r = self.invoke(["gate", target["id"]], {"DFM_BD_ROLE": "worker"})
        self.case("gate-empty", "P6/P8.1", "Worker gate exits zero, ok true, reasons list empty, read-only", self.success(r) and r["json"].get("ok") is True and gate_reasons(r["json"], []) and before == self.graph(), r)
        good = self.new("Good", status="closed", dispatch=True)
        self.setmeta(good, receipt={"verdict": "PASS"})
        legacy = self.new("Legacy", status="closed")
        omitted = self.new("NoVerdict", status="closed", dispatch=True)
        self.setmeta(omitted, receipt={"outcome": "completed"})
        empty_receipt = self.new("EmptyReceipt", status="closed", dispatch=True)
        self.setmeta(empty_receipt, receipt={})
        stored_null = self.new("StoredNull", status="closed", dispatch=True)
        self.setmeta(stored_null, receipt={"verdict": None, "outcome": "completed"})
        for p in (good, legacy, omitted, empty_receipt, stored_null):
            self.bdw("dep", "add", target["id"], p["id"])
        before = self.graph()
        r = self.invoke(["gate", target["id"]])
        self.case("gate-good", "P6/P8.4", "Closed PASS, omitted-verdict and never-dispatched predecessors pass", self.success(r) and r["json"].get("ok") is True and gate_reasons(r["json"], []) and before == self.graph(), r)
        self.accept("legacy-predecessor-start", "P2.5", target)
        self.inactive(target)
        failures = []
        for label, status, dispatched, receipt in (("Open", "open", False, None), ("Missing", "closed", True, None),
                ("Reject", "closed", True, {"verdict": "REJECT"}), ("BadVerdict", "closed", True, {"verdict": "FAIL"}),
                ("NullBadOutcome", "closed", True, {"verdict": None, "outcome": "FAILED"}), ("Outcome", "closed", True, {"verdict": "PASS", "outcome": "FAIL"}),
                ("NoVerdictBadOutcome", "closed", True, {"outcome": "reject"}), ("SeveralFaults", "open", True, {"verdict": "REJECT"})):
            t = self.new("Gate" + label)
            p = self.new("Block" + label, status=status, dispatch=dispatched)
            if receipt is not None:
                self.setmeta(p, receipt=receipt)
            self.bdw("dep", "add", t["id"], p["id"])
            failures.append(p)
            before = self.graph()
            r = self.invoke(["gate", t["id"]], {"DFM_BD_ROLE": "worker"})
            self.case("gate-not-ok-" + label, "P6", "Gate false, one failing dependency reason, read-only",
                self.success(r) and r["json"].get("ok") is False and gate_reasons(r["json"], [p["id"]]) and before == self.graph(), r)
        mixed = self.new("MixedGate")
        for p in [good, stored_null, *failures]:
            self.bdw("dep", "add", mixed["id"], p["id"])
        before = self.graph()
        r = self.invoke(["gate", mixed["id"]])
        self.case("gate-mixed", "P6", "One reason per failing dependency; all failed IDs reported", self.success(r)
            and r["json"].get("ok") is False and gate_reasons(r["json"], [p["id"] for p in failures]) and before == self.graph(), r)

    def fill_cases(self):
        self.group("fill")
        first = self.new("First", priority=0, plan=True)
        conflict = self.new("Conflict", priority=1, plan=True)
        later = self.new("Later", priority=2, plan=True)
        native_conflict = self.new("NativeConflict", priority=3, plan=True)
        tie1 = self.new("TieA", priority=4, plan=True)
        tie2 = self.new("TieB", priority=4, plan=True)
        beyond = self.new("BeyondProjectedLimit", priority=4, plan=True)
        no_plan = self.new("NoPlan", priority=0)
        uncertain = self.new("Uncertain", dispatch=True, priority=0, plan=True)
        for f, paths in ((first, ["src/a"]), (conflict, ["src/a/sub"]), (later, ["src/b"])):
            plan = meta(self.issue(f["id"]))["plan"]
            plan.update(owns=paths)
            if f == later:
                plan.update(kind="claude", native=True, approved="HUMAN-20261106-7", base=self.old, model="approved-opus")
            self.setmeta(f, plan=plan)
        native_plan = meta(self.issue(native_conflict["id"]))["plan"]
        native_plan["native"] = True
        self.setmeta(native_conflict, plan=native_plan)
        expected_tasks = [first, later, *sorted((tie1, tie2, beyond), key=lambda x: x["id"])[:2]]
        expected_ids = [x["id"] for x in expected_tasks]
        known_ids = {x["id"] for x in self.nodes}
        before, fake = self.graph(), self.statefile.read_bytes()
        wt = self.git("worktree", "list", "--porcelain")
        r = self.invoke(["fill", "--max-parallel", "4", "--dry-run"])
        dry = r
        self.case("fill-dry-run", "P3/P8.3", "Projects capacity/ownership/native use without any graph/fake/worktree writes", self.success(r)
            and all(k in r["json"] for k in ("started", "skipped", "limit", "active_before"))
            and listed_ids(r["json"].get("started"), known_ids) == expected_ids
            and all(word in json.dumps(r["json"].get("skipped")) for word in ("ownership_conflict", "native_busy", conflict["id"], native_conflict["id"]))
            and before == self.graph() and fake == self.statefile.read_bytes() and wt == self.git("worktree", "list", "--porcelain"), r)
        r = self.invoke(["fill", "--max-parallel", "4"])
        calls = [x["argv"][2] for x in r["fake_calls"] if x["argv"][:2] == ["agent", "start"]]
        expected = [x["name"] for x in expected_tasks]
        data = r["json"] or {}
        self.case("P8-dry-run-matches-real-fill", "P8.3", "Projected and actual ordered started IDs match exactly",
            self.success(dry) and self.success(r) and listed_ids(data.get("started"), known_ids) == expected_ids
            and listed_ids(dry["json"].get("started"), known_ids) == listed_ids(data.get("started"), known_ids), {"dry_run": dry, "real_fill": r})
        later_d = meta(self.issue(later["id"])).get("dispatch", {})
        self.case("fill-order-continue", "P3", "Priority/id order; refusal in middle does not stop later tasks", self.success(r)
            and calls == expected and data.get("limit") == 4 and data.get("active_before") == 0
            and all(word in json.dumps(data) for word in ("ownership_conflict", "native_busy", conflict["id"], native_conflict["id"])), {"call": r, "expected_names": expected})
        self.case("fill-plan-options", "P3/P1", "Plan optional resources/model/base/name applied", later_d.get("kind") == "claude"
            and later_d.get("base_sha") == self.old and later_d.get("native") is True
            and later_d.get("approved") == "HUMAN-20261106-7" and later_d.get("owned_paths") == ["src/b"], later_d)
        self.case("fill-no-plan", "P3", "Ready node without plan reported no_plan and unchanged", self.success(r)
            and no_plan["id"] in json.dumps(data.get("skipped")) and "no_plan" in json.dumps(data.get("skipped"))
            and "dispatch" not in meta(self.issue(no_plan["id"])), r)
        self.case("fill-unended-not-restarted", "P3", "Open node with absent agent/unended dispatch never restarted", self.success(r)
            and uncertain["name"] not in calls and meta(self.issue(uncertain["id"])).get("dispatch") == uncertain["record"], r)
        self.group("fill-failure")
        first = self.new("StartFirst", priority=0, plan=True)
        broken = self.new("Broken", priority=1, plan=True)
        last = self.new("StartLast", priority=2, plan=True)
        self.state(fail_agent=broken["name"])
        r = self.invoke(["fill", "--max-parallel", "2"])
        self.case("fill-worker-failure-continue", "P3", "Failed worker neither undoes first nor prevents later start", self.success(r)
            and all(self.issue(f["id"])["status"] == "in_progress" for f in (first, last))
            and self.issue(broken["id"])["status"] == "open" and broken["id"] in json.dumps(r["json"]), r)

    def status_reconcile(self):
        self.group("reconcile")
        live = self.new("Live", status="in_progress", dispatch=True, live=True, owned_paths=["a"], native=True)
        finished = self.new("Finished", status="in_progress", dispatch=True)
        absent = self.new("Absent", status="in_progress", dispatch=True)
        untracked = self.new("Untracked", status="in_progress")
        closed = self.new("Closed", status="closed", dispatch=True)
        ended = self.new("Ended", status="in_progress", dispatch=True, ended_at="2026-11-06T00:01:00Z")
        self.setmeta(finished, receipt={"verdict": "PASS"})
        for f in (live, finished):
            self.git("worktree", "add", "-q", "--detach", str(f["wt"]), self.head)
        (finished["wt"] / "data.txt").write_text("dirty worker\n", encoding="utf-8")
        s = self.state()
        s["agents"]["unrecorded"] = {"name": "unrecorded", "pane_id": "unknown-pane", "agent_status": "working", "agent_session": {"value": "unknown"}}
        write(self.statefile, s)
        before = self.graph()
        r = self.invoke(["status"], {"DFM_BD_ROLE": "worker"})
        data = r["json"] or {}
        for f, islive, receipt in ((live, True, False), (finished, False, True), (absent, False, False)):
            item = find(data, f["id"])
            required = ("task_code", "agent", "kind", "pane_id", "session_id", "worktree", "model", "started_at", "attempt", "owned_paths", "native", "receipt_collected", "live")
            # P8.1 permits documented aliases and arbitrary output wrappers.
            missing = object()
            self.case("status-" + f["code"], "P4", "Active dispatch fields, receipt flag and liveness", self.success(r)
                and all(field(item, k, missing) is not missing for k in required) and field(item, "live") is islive and field(item, "receipt_collected") is receipt, {"record": item, "call_id": r["call_id"]})
        self.case("status-active-set-readonly", "P4", "Exclude closed/ended; worker read-only", self.success(r)
            and not find(data, closed["id"]) and not find(data, ended["id"]) and before == self.graph(), r)
        self.state(unreachable=True)
        r = self.invoke(["status"], {"DFM_BD_ROLE": "worker"})
        self.case("status-unreachable-null", "P4", "Unreachable Herdr gives live null and no graph writes", self.success(r)
            and all(field(find(r["json"], f["id"]), "live", "missing") is None for f in (live, finished, absent)) and before == self.graph(), r)
        self.state(unreachable=False)
        outage_modes = [("server-not-running", {"outage_code": "server_not_running"}, {}),
            ("other-structured-error", {"outage_code": "permission_denied"}, {}),
            ("non-json-stdout", {"non_json": True}, {}),
            ("failure-to-execute", {}, {"DFM_HERDR_EXE": self.out / "missing" / "fake-herdr.cmd"})]
        for label, state, overrides in outage_modes:
            self.state(**{"outage_code": None, "non_json": False, **state})
            # Separate calls must both be read-only, regardless of error shape.
            before_outage = self.graph()
            sr = self.invoke(["status"], {"DFM_BD_ROLE": "worker", **overrides})
            self.case("P8-status-outage-" + label, "P8.5", "Every unreachable class yields null liveness and no writes",
                self.success(sr) and all(field(find(sr["json"], f["id"]), "live", "missing") is None for f in (live, finished, absent))
                and before_outage == self.graph(), sr)
            rr = self.invoke(["reconcile"], overrides)
            self.case("P8-reconcile-outage-" + label, "P8.5", "Every unreachable class exits 2 error and writes nothing",
                rr["exit"] == 2 and isinstance(rr["error_json"], dict) and "error" in rr["error_json"] and before_outage == self.graph(), rr)
        self.state(outage_code=None, non_json=False)
        r = self.invoke(["reconcile"])
        after = self.graph()
        self.case("reconcile-live", "P4", "Live record unchanged", self.success(r) and before[live["id"]] == after[live["id"]], r)
        for f, expected_state, exists, dirty in ((finished, "finished", True, True), (absent, "needs_review", False, None)):
            issue = after[f["id"]]["issue"]
            d = meta(issue).get("dispatch", {})
            review = d.get("review", {})
            comments = after[f["id"]]["comments"]
            good = self.success(r) and review.get("state") == expected_state and bool(review.get("reason")) and bool(review.get("detected_at"))
            good = good and review.get("worktree_exists") is exists and "worktree_dirty" in review and review["worktree_dirty"] is dirty
            good = good and issue["status"] == "in_progress" and not d.get("ended_at") and len(comments) == len(before[f["id"]]["comments"]) + 1
            good = good and json.dumps(comments, ensure_ascii=False).isascii()
            self.case("reconcile-" + expected_state, "P4", "Review state/artifacts; one English comment; status/end unchanged", good, after[f["id"]])
        self.case("reconcile-untracked-unrecorded", "P4", "Report untracked issue and unrecorded live agent only", self.success(r)
            and untracked["id"] in json.dumps((r["json"] or {}).get("untracked_in_progress"))
            and "unrecorded" in json.dumps((r["json"] or {}).get("unrecorded_agents")) and before[untracked["id"]] == after[untracked["id"]], r)
        r2 = self.invoke(["reconcile"])
        self.case("reconcile-idempotent", "P4", "Second unchanged review writes no comments/timestamps", self.success(r2) and after == self.graph(), r2)
        # Remove reviews in fixtures, then make a later lookup unreachable: no partial writes.
        self.setmeta(finished, dispatch=finished["record"])
        self.setmeta(absent, dispatch=absent["record"])
        # Third active-agent lookup must occur after at least one absent lookup:
        # of three active fixtures only one is live. This tests partial writes.
        self.state(unreachable_get_after=3, get_calls=0, late_error_code="server_not_running")
        before = self.graph()
        r = self.invoke(["reconcile"])
        self.case("reconcile-outage-atomic", "P4", "Herdr unreachable => exit 2 error, no node writes", r["exit"] == 2
            and isinstance(r["error_json"], dict) and "error" in r["error_json"] and before == self.graph(), r)

    def collect_cases(self):
        self.group("collect")
        f = self.new("Receipt", status="in_progress", dispatch=True)
        directory = self.root / "receipt-folder"
        directory.mkdir()
        evidence = directory / "evidence.txt"
        evidence.write_text("retained evidence\n", encoding="utf-8")
        receipt_path = directory / "receipt.json"
        tree = self.git("rev-parse", "HEAD^{tree}")
        invalid = [("sha-missing", {"candidate_sha": "f" * 40}), ("sha-not-commit", {"candidate_sha": tree}),
            ("sha-unrelated", {"candidate_sha": self.orphan}), ("sha-ancestor", {"candidate_sha": self.old}),
            ("evidence-relative-missing", {"evidence": ["missing.txt"]}),
            ("evidence-absolute-missing", {"evidence": [str(directory / "missing.txt")]}),
            ("verdict-garbage", {"verdict": "MAYBE"}), ("verdict-lowercase", {"verdict": "pass"}),
            ("verdict-null", {"verdict": None})]
        for label, change in invalid:
            write(receipt_path, {"task_code": f["code"], "verdict": "PASS", "candidate_sha": self.head, **change})
            before = self.graph()
            r = self.invoke(["collect", f["id"], "--receipt", receipt_path])
            self.case("collect-refuse-" + label, "P5", "Invalid fan-in refused without metadata/metrics/comments writes", self.refused(r) and before == self.graph(), r)
        # Descendant created with commit-tree; no main branch/index/worktree mutation.
        descendant = self.git("commit-tree", tree, "-p", self.head, "-m", "descendant fixture")
        for label, change in (("equal", {"candidate_sha": self.head, "evidence": ["evidence.txt", str(directory)]}),
                ("descendant", {"candidate_sha": descendant[:12], "evidence": [str(evidence)]}),
                ("null", {"candidate_sha": None}), ("reject", {"candidate_sha": self.head, "verdict": "REJECT", "outcome": "rejected"})):
            write(receipt_path, {"task_code": f["code"], "verdict": "PASS", **change})
            r = self.invoke(["collect", f["id"], "--receipt", receipt_path])
            issue = self.issue(f["id"])
            m = meta(issue)
            self.case("collect-valid-" + label, "P5/C2", "Valid receipt collected/hash recorded; status unchanged", self.success(r)
                and m.get("receipt", {}).get("sha256") == digest(receipt_path) and m.get("receipt", {}).get("verdict") == change.get("verdict", "PASS")
                and issue["status"] == "in_progress", {"call": r, "issue": issue})
        self.inactive(f)
        child = self.new("RejectedDependent")
        self.bdw("dep", "add", child["id"], f["id"])
        self.reject("collected-reject-blocks-start", "P2.5/P5", child, reason="failed_predecessor")
        r = self.invoke(["gate", child["id"]])
        self.case("collected-reject-blocks-gate", "P5/P6", "Actual collected REJECT blocks gate", self.success(r) and r["json"].get("ok") is False, r)
        # Exercise the entire collect -> closed predecessor -> gate/start path.
        # A source receipt omitting verdict must not become a failing null verdict.
        for n, payload in enumerate(({}, {"outcome": "completed"})):
            parent = self.new("CollectedNoVerdict" + str(n), status="in_progress", dispatch=True)
            path = directory / ("omitted-verdict-" + str(n) + ".json")
            write(path, {"task_code": parent["code"], "candidate_sha": self.head, **payload})
            collected = self.invoke(["collect", parent["id"], "--receipt", path])
            self.case("P8-collect-omitted-verdict-" + str(n), "P8.4/P5", "Omitted verdict is accepted without becoming a fan-in failure", self.success(collected), collected)
            self.inactive(parent)
            child = self.new("CollectedNoVerdictChild" + str(n))
            self.bdw("dep", "add", child["id"], parent["id"])
            gate = self.invoke(["gate", child["id"]])
            self.case("P8-collected-omitted-verdict-gate-" + str(n), "P8.4/P6", "Collected omitted-verdict receipt passes gate",
                self.success(gate) and gate["json"].get("ok") is True and gate_reasons(gate["json"], []), gate)
            self.accept("P8-collected-omitted-verdict-start-" + str(n), "P8.4/P2.5", child)
            self.inactive(child)

    def c_regressions(self):
        self.group("regressions")
        probe = self.out / "policy_probe.py"
        probe.write_text("import json,sys\nfrom research.workflows.graph import bdw\ntry:\n bdw.check_args(json.loads(sys.argv[1]),sys.argv[2]); print('true')\nexcept bdw.Refused:\n print('false')\n", encoding="utf-8")
        for role in ("worker", "coordinator"):
            for args in (["human", "list"], ["human", "stats"], ["human", "respond"], ["human", "dismiss"],
                    *[["gate", x] for x in ("create", "list", "show", "check", "resolve", "add-waiter", "discover")], ["human"], ["gate"]):
                allowed = args in (["human", "list"], ["human", "stats"]) or role == "coordinator" and len(args) == 2 and args[1] not in ("add-waiter", "discover")
                r = self.run([sys.executable, "-B", probe, json.dumps(args), role])
                self.case("C1-" + role + "-" + "-".join(args), "C1", "bdw command allowlist", r["exit"] == 0 and load(r["stdout"]) is bool(allowed), r)
        f = self.new("Role")
        for command in (self.args(f), ["collect", f["id"], "--receipt", self.root / "none.json"], ["stop", f["id"]], ["fill"], ["reconcile"]):
            before = self.graph()
            r = self.invoke(command, {"DFM_BD_ROLE": "worker"})
            self.case("C2-worker-" + command[0], "C2/P3/P4", "Non-coordinator writes refused before Herdr/state", self.refused(r) and not r["fake_calls"] and before == self.graph(), r)
        r = self.invoke(["show", f["id"]], {"DFM_BD_ROLE": "worker"})
        self.case("C2-worker-show", "C2", "Any-role show succeeds read-only", self.success(r), r)
        for label, status, kind in (("Epic", "open", "epic"), ("Closed", "closed", "task")):
            n = self.new(label, status=status, kind=kind)
            self.reject("C2-refuse-" + label, "C2", n)
        for label, options in (("kind", {"kind": "other"}), ("packet", {"packet": self.root / "outside.md"}),
                ("base", {"base": "not-a-sha"})):
            self.reject("C2-refuse-" + label, "C2", f, options)
        self.setmeta(f, task_code="bad_code")
        self.reject("C4-task-code", "C4.6", f)
        self.setmeta(f, task_code=f["code"])
        for variant in ("normal", "retry", "never", "seq"):
            n = self.new("Submit" + variant)
            self.state(submit=variant)
            before = self.graph()
            r = self.invoke(self.args(n))
            enters = [x for x in r["fake_calls"] if x["argv"][:2] == ["agent", "send-keys"]]
            keys_ok = all(x["argv"][2:] == [n["name"], "enter"] for x in enters)
            if variant == "never":
                passed = r["exit"] == 2 and before == self.graph() and len(enters) == 1 and not n["wt"].exists() and n["name"] not in self.state()["agents"]
            else:
                passed = self.success(r) and (r["json"] or {}).get("submit_retry") is (variant == "retry") and len(enters) == int(variant == "retry")
            self.case("C5-submit-" + variant, "C5.1", "Turn acknowledged, retry/cleanup policy followed", passed and keys_ok, r)
            if self.success(r):
                self.inactive(n)
        self.state(submit="normal")
        n = self.new("History", dispatch=True)
        old = n["record"].copy()
        r = self.invoke(self.args(n))
        m = meta(self.issue(n["id"]))
        history = m.get("dispatch_history", [])
        prev = history[-1] if history else {}
        self.case("C5-history-interrupted", "C5.2", "Prior unended attempt preserved and marked interrupted", self.success(r)
            and m.get("dispatch", {}).get("attempt") == 2 and prev.get("interrupted") is True and bool(prev.get("interrupted_detected_at"))
            and all(prev.get(k) == v for k, v in old.items()), {"call": r, "metadata": m})

    def c_start_stop(self):
        self.group("start-stop")
        for kind in ("codex", "claude"):
            f = self.new("Argv" + kind)
            self.bdw("update", f["id"], "--assignee", "prior-owner")
            r = self.invoke(self.args(f, kind=kind))
            issue = self.issue(f["id"])
            d = meta(issue).get("dispatch", {})
            starts = [x["argv"] for x in r["fake_calls"] if x["argv"][:2] == ["agent", "start"]]
            prompts = [x["argv"] for x in r["fake_calls"] if x["argv"][:2] == ["agent", "prompt"]]
            tail = starts[0][starts[0].index("--") + 1:] if starts else []
            wanted = ["--model", "fixture-model", "--effort", "high", "--permission-mode", "bypassPermissions"] if kind == "claude" else ["--model", "fixture-model", "-c", "model_reasoning_effort=high"]
            detached = f["wt"].is_dir() and not self.git("branch", "--show-current", cwd=f["wt"]) and self.git("rev-parse", "HEAD", cwd=f["wt"]) == self.head
            self.case("C2-start-" + kind, "C2/C4", "Explicit vendor argv; English prompt; detached worktree and provenance", self.success(r)
                and tail == wanted and len(prompts) == 1 and prompts[0][3].isascii() and "AGENTS.md" in prompts[0][3] and str(f["packet"]) in prompts[0][3]
                and detached and d.get("packet_sha256") == digest(f["packet"]) and d.get("base_sha") == self.head
                and d.get("session_id") == "session-" + f["name"] and d.get("attempt") == 1
                and not issue.get("assignee") and meta(issue).get("sentinel") == {"unknown": [1, "preserve"]}, {"call": r, "issue": issue})
            if not self.success(r):
                continue
            # A still-working recorded agent cannot be restarted or stopped.
            self.reject("C2-live-restart-" + kind, "C2", f)
            before = self.graph()
            r = self.invoke(["stop", f["id"]])
            self.case("C2-stop-working-" + kind, "C2", "Working agent stop refused without changes", self.refused(r) and before == self.graph(), r)
            s = self.state()
            s["agents"][f["name"]]["agent_status"] = "done"
            write(self.statefile, s)
            if kind == "claude":
                (f["wt"] / "worker-change.txt").write_text("dirty worker\n", encoding="utf-8")
            r = self.invoke(["stop", f["id"]])
            d = meta(self.issue(f["id"])).get("dispatch", {})
            self.case("C2-stop-done-" + kind, "C2", "Recorded done pane closed; clean worktree removed, dirty retained; ended recorded", self.success(r)
                and bool(d.get("ended_at")) and f["name"] not in self.state()["agents"] and f["wt"].exists() is (kind == "claude"), r)
            self.inactive(f)
        # Reuse and worktree refusal paths: fixture setup is separate from dispatch.
        for label in ("Clean", "Dirty", "WrongSha", "Occupied"):
            f = self.new("Reuse" + label)
            if label == "Occupied":
                f["wt"].mkdir(parents=True)
                (f["wt"] / "keep.txt").write_text("preserve\n", encoding="utf-8")
            else:
                self.git("worktree", "add", "-q", "--detach", str(f["wt"]), self.old if label == "WrongSha" else self.head)
                if label == "Dirty":
                    (f["wt"] / "AGENTS.md").write_text("dirty\n", encoding="utf-8")
            if label == "Clean":
                self.accept("C2-reuse-clean", "C2", f)
                self.inactive(f)
            else:
                self.reject("C2-worktree-refuse-" + label, "C2", f)
        f = self.new("OpenBlocked")
        p = self.new("OpenBlocker")
        self.bdw("dep", "add", f["id"], p["id"])
        self.reject("C2-open-blocker", "C2/P2.6", f)
        # Existing dispatch pointing at another pane must not close that replacement.
        f = self.new("Replacement", status="in_progress", dispatch=True, live=True)
        s = self.state()
        s["agents"][f["name"]]["pane_id"] = "replacement-pane"
        s["panes"]["replacement-pane"] = {"pane_id": "replacement-pane"}
        write(self.statefile, s)
        r = self.invoke(["stop", f["id"]])
        self.case("C4-replacement-pane", "C2/C4.6", "Stop never closes a replacement agent pane", self.success(r)
            and "replacement-pane" in self.state()["panes"] and not any(x["argv"] == ["pane", "close", "replacement-pane"] for x in r["fake_calls"]), r)

    def transcript_regressions(self):
        self.group("transcripts")
        for kind in ("codex", "claude"):
            f = self.new("Usage" + kind, status="in_progress", dispatch=True, kind="task")
            d = dict(f["record"], kind=kind)
            self.setmeta(f, dispatch=d)
            session = d["session_id"]
            if kind == "codex":
                transcript = self.out / "codex/sessions/fixture" / ("rollout-fixture-" + session + ".jsonl")
                rows = [
                    {"timestamp": "2026-11-06T00:00:00Z", "type": "turn_context", "payload": {"model": "observed-codex"}},
                    {"timestamp": "2026-11-06T00:01:00Z", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 20, "output_tokens": 2}}}},
                    {"timestamp": "2026-11-06T00:02:00Z", "payload": {"type": "token_count", "info": {"total_token_usage": {
                        "input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 7, "output_tokens": 12, "reasoning_output_tokens": 3, "total_tokens": 112}}}}]
                wanted = {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_tokens": 7, "output_tokens": 12, "reasoning_tokens": 3}
                model = "observed-codex"
            else:
                transcript = self.out / "claude/projects/fixture" / (session + ".jsonl")
                rows = [
                    {"timestamp": "2026-11-06T00:00:00Z", "type": "assistant", "message": {"id": "one", "model": "observed-claude", "usage": {"input_tokens": 30, "cache_read_input_tokens": 11, "cache_creation_input_tokens": 5, "output_tokens": 7}}},
                    {"timestamp": "2026-11-06T00:01:00Z", "type": "assistant", "message": {"id": "one", "model": "observed-claude", "usage": {"input_tokens": 30, "cache_read_input_tokens": 11, "cache_creation_input_tokens": 5, "output_tokens": 7}}},
                    {"timestamp": "2026-11-06T00:02:00Z", "type": "assistant", "message": {"id": "two", "model": "observed-claude", "usage": {"input_tokens": 10, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1, "output_tokens": 3}}}]
                wanted = {"input_tokens": 40, "cached_input_tokens": 13, "cache_write_tokens": 6, "output_tokens": 10}
                model = "observed-claude"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text("malformed-json\n[]\n" + "\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
            receipt = self.root / (kind + "-receipt.json")
            write(receipt, {"task_code": f["code"], "candidate_sha": self.head, "verdict": "PASS"})
            r = self.invoke(["collect", f["id"], "--receipt", receipt])
            m = meta(self.issue(f["id"]))
            usage = m.get("metrics", {}).get("usage") or {}
            self.case("C2-usage-" + kind, "C2/C4.5", "Fixture token accounting/models/span/malformed lines; Claude dedup", self.success(r)
                and all(usage.get("tokens", {}).get(k) == v for k, v in wanted.items()) and usage.get("wall_seconds") == 120
                and usage.get("malformed_lines") == 2 and model in usage.get("models", [])
                and (kind != "claude" or usage.get("messages_counted") == 2), {"call": r, "metrics": m.get("metrics")})
            for label, raw in (("malformed", "{"), ("wrong-code", json.dumps({"task_code": "OTHER"}))):
                receipt.write_text(raw, encoding="utf-8")
                before = self.graph()
                r = self.invoke(["collect", f["id"], "--receipt", receipt])
                self.case("C2-receipt-" + kind + "-" + label, "C2", "Malformed/mismatched receipt refused without writes", self.refused(r) and before == self.graph(), r)
        f = self.new("MissingTranscript", status="in_progress", dispatch=True)
        receipt = self.root / "missing-transcript.json"
        write(receipt, {"task_code": f["code"], "candidate_sha": None, "verdict": "PASS"})
        r = self.invoke(["collect", f["id"], "--receipt", receipt])
        metrics = meta(self.issue(f["id"])).get("metrics", {})
        self.case("C2-transcript-missing", "C2", "Missing transcript does not fail collect; usage null with reason", self.success(r)
            and "usage" in metrics and metrics["usage"] is None and bool(metrics.get("usage_unavailable_reason")), r)

    def author_checks(self):
        external = os.environ.get("P4_EXTERNAL_AUTHOR_REPORT")
        if external:
            report = Path(external).resolve()
            if not report.is_relative_to(OWNED):
                raise ValueError("External author report must stay inside V-Run folder")
            self.report["author_tests"] = {"external_report": str(report),
                "status": "separate background execution; final verdict reconciles actual results"}
            self.flush()
            return
        # Run exact source bytes from owned source snapshot; no source-tree pycache.
        self.repo = self.out
        for name in ("test_bdw", "test_dispatch", "test_dashboard"):
            r = self.run([sys.executable, "-B", "-m", "unittest", REL + name, "-v"],
                extra={"P4_GUARD": "1"}, timeout=900)
            self.report["author_tests"][name] = r
            self.case("author-" + name, "Done-when", "Author suite passes (skips recorded separately)", r["exit"] == 0, r)
        r = self.run([sys.executable, "-m", "compileall", "-q", str(self.source / "research/workflows")])
        self.report["author_tests"]["compileall-owned-copy"] = r
        self.case("compileall-owned-copy", "Done-when", "Copied workflow syntax compiles", r["exit"] == 0, r)

    def round2_cases(self, case_ids=None):
        inputs = self.out / "round2-inputs"
        shutil.copytree(OWNED / "r2-corpus-p88", inputs)
        corpus = load((inputs / "cases.json").read_text(encoding="utf-8"))
        assert corpus["contract_sha"] == CONTRACT
        self.report["round2_inputs"] = {"case_count": len(corpus["cases"]),
            "cases_sha256": digest(inputs / "cases.json"), "manifest_sha256": digest(inputs / "manifest.json")}
        if case_ids is not None:
            corpus["cases"] = [c for c in corpus["cases"] if c["id"] in case_ids]
        self.group("prompt-received")
        for index, c in enumerate(x for x in corpus["cases"] if x["stage"] == "start_prompt_check"):
            f = self.new("P03-" + str(index))
            rows = [load(line, line) for line in (inputs / c["fixture"]).read_text(encoding="utf-8").splitlines()] if c.get("fixture") else []
            mode = {"enter-retry": "retry", "session-only": "session", "visible-only": "screen"}.get(c["turn_evidence"], "normal")
            config = {"rows": rows, "template_prompt": c["sent_prompt"], "missing": c.get("fixture") is None,
                "timeline": bool(c.get("timeline")), "timeline_rows": next((s["rows"] for s in c.get("timeline", []) if s.get("rows")), []),
                "other_session_rows": c.get("other_session_rows")}
            self.state(submit=mode, visible_text="Working (fixture)" if mode == "screen" else "", prompts=[],
                       session_never=c.get("session_id", "present") is None, prompt_case=config)
            before = self.graph()
            read_log = self.root / ("reads-" + str(index) + ".jsonl")
            publisher_errors = []
            publisher = None
            if c.get("timeline"):
                def publish_later(f=f, rows=rows, template=c["sent_prompt"], read_log=read_log):
                    try:
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            state = load(self.statefile.read_text(encoding="utf-8"), {})
                            if state.get("last_prompt_agent") == f["name"] and read_log.exists() and read_log.stat().st_size:
                                agent = state["agents"][f["name"]]
                                session = agent["agent_session"]["value"]
                                home = Path(self.env["DFM_CODEX_HOME" if agent["kind"] == "codex" else "DFM_CLAUDE_HOME"])
                                target = home / "sessions/round2" / ("rollout-fixture-" + session + ".jsonl") if agent["kind"] == "codex" else home / "projects/round2" / (session + ".jsonl")
                                assert target.resolve().is_relative_to(self.out)
                                time.sleep(0.15)
                                data = _r2_render(rows, template, state["prompts"][-1])
                                temporary = target.with_suffix(".pending")
                                temporary.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in data) + "\n", encoding="utf-8")
                                temporary.replace(target)
                                return
                            time.sleep(0.02)
                        raise RuntimeError("Bounded prompt publisher never observed a transcript read")
                    except Exception:
                        publisher_errors.append(traceback.format_exc())
                publisher = threading.Thread(target=publish_later)
                publisher.start()
            extra = {"DFM_DISPATCH_SUBMIT_SECONDS": "3" if publisher else "0.1", "P4_PROMPT_READ_LOG": str(read_log)}
            r = self.invoke(self.args(f, kind=c["vendor"]), extra)
            if publisher:
                publisher.join(16)
            issue = self.issue(f["id"])
            d = meta(issue).get("dispatch", {})
            expected = c["expected"]["prompt_received"]
            prompt_calls = [x for x in r["fake_calls"] if x["argv"][:2] == ["agent", "prompt"]]
            enters = [x for x in r["fake_calls"] if x["argv"][:2] == ["agent", "send-keys"]]
            closes = [x for x in r["fake_calls"] if x["argv"][:2] == ["pane", "close"]]
            warning = field(r["json"], "warning")
            ok = self.success(r) and issue["status"] == "in_progress" and d.get("prompt_received", "MISSING") is expected
            ok = ok and f["wt"].is_dir() and len(prompt_calls) == 1 and not closes and len(enters) == c.get("expected_enter_calls", 0)
            ok = ok and (warning == "prompt_truncated" if expected is False else warning != "prompt_truncated")
            if expected is None:
                ok = ok and bool(d.get("prompt_check_note"))
            if publisher:
                ok = ok and not publisher.is_alive() and not publisher_errors and len(self.lines(read_log)) >= 2
            self.case(c["id"], "P0.3", "Record exact first prompt match/mismatch/unknown without resend or cleanup", ok,
                {"call": r, "dispatch": d, "publisher_errors": publisher_errors, "read_log": str(read_log)})
            active_before_status = self.graph()
            status = self.invoke(["status"], {"DFM_BD_ROLE": "worker"})
            item = find(status["json"], f["id"])
            self.case(c["id"] + "-status", "P0.3/P4", "Status exposes prompt_received and writes nothing",
                self.success(status) and field(item, "prompt_received", "MISSING") is expected and active_before_status == self.graph(), status)
            self.inactive(f)
        self.state(prompt_case=None, submit="normal", session_never=False)

        self.group("r2-intake")
        for index, c in enumerate(x for x in corpus["cases"] if x["stage"] == "collect_intake"):
            f = self.new("Intake" + str(index), status="in_progress", dispatch=True)
            if c.get("existing_stored_receipt"):
                self.setmeta(f, receipt=c["existing_stored_receipt"])
            path = self.root / ("intake-" + str(index) + ".json")
            write(path, {**c["receipt"], "task_code": f["code"]})
            before = self.graph()
            r = self.invoke(["collect", f["id"], "--receipt", path])
            ok = self.success(r) if c["expected"]["accepted"] else self.refused(r) and before == self.graph()
            self.case(c["id"], "P5/P8.7", "Enforce enum at intake; omitted verdict remains valid", ok, r)
            self.inactive(f)

        self.group("stored-compatibility")
        for index, c in enumerate(x for x in corpus["cases"] if x["stage"] == "stored_fan_in"):
            parent = self.new("Legacy" + str(index), status=c["predecessor_status"], dispatch=True)
            if not c.get("stored_receipt_missing"):
                self.setmeta(parent, receipt=c["stored_receipt"])
            child = self.new("Child" + str(index))
            self.bdw("dep", "add", child["id"], parent["id"])
            before = self.graph()
            gate = self.invoke(["gate", child["id"]], {"DFM_BD_ROLE": "worker"})
            allowed = c["expected"]["gate_ok"]
            self.case(c["id"] + "-gate", "P8.7/P6", "Legacy null equals omitted verdict; outcome/status still govern",
                self.success(gate) and gate["json"].get("ok") is allowed and gate_reasons(gate["json"], [] if allowed else [parent["id"]]) and before == self.graph(), gate)
            parent_before = before[parent["id"]]
            start = self.invoke(self.args(child))
            ok = self.success(start) if allowed else self.refused(start, c["expected"].get("refusal_reason"))
            after = self.graph()
            ok = ok and parent_before == after[parent["id"]]
            if not allowed:
                ok = ok and before == after
            self.case(c["id"] + "-start", "P8.7/P2.5", "Start uses stored compatibility without recollecting or mutating predecessor", ok, start)
            # Cleanup only after the start/gate observations: Beads refuses to close a blocked child.
            if self.issue(parent["id"])["status"] != "closed":
                self.inactive(parent)
            self.inactive(child)

        self.group("r2-mixed")
        target = self.new("MixedGate")
        ids = []
        for index, receipt in enumerate(({"verdict": None}, {"verdict": "REJECT"}, {"verdict": None, "outcome": "fail"})):
            f = self.new("Mixed" + str(index), status="closed", dispatch=True)
            self.setmeta(f, receipt=receipt)
            self.bdw("dep", "add", target["id"], f["id"])
            ids.append(f["id"])
        before = self.graph()
        r = self.invoke(["gate", target["id"]])
        self.case("gate-mixed-legacy-null-and-failures", "P8.7/P6", "Benign null excluded; REJECT and failing outcome remain in reasons",
            self.success(r) and r["json"].get("ok") is False and gate_reasons(r["json"], ids[1:]) and before == self.graph(), r)
        legacy = self.new("StatusLegacy", status="in_progress", dispatch=True)
        before = self.graph()
        r = self.invoke(["status"])
        self.case("status-legacy-unknown-prompt", "P0.3/P4", "Old dispatch gets null prompt_received in read-only status",
            self.success(r) and field(find(r["json"], legacy["id"]), "prompt_received", "MISSING") is None and before == self.graph(), r)

        self.group("r2-fill-prompt")
        first = self.new("TruncatedFirst", priority=0, plan=True)
        second = self.new("CompleteSecond", priority=1, plan=True)
        plan = meta(self.issue(second["id"]))["plan"]
        plan["kind"] = "claude"
        self.setmeta(second, plan=plan)
        self.state(truncate_agent=first["name"])
        r = self.invoke(["fill", "--max-parallel", "2"])
        ds = [meta(self.issue(f["id"])).get("dispatch", {}) for f in (first, second)]
        prompts = [x for x in r["fake_calls"] if x["argv"][:2] == ["agent", "prompt"]]
        self.case("fill-warning-keeps-both-workers", "P0.3/P3", "Truncated worker remains started; next worker starts; neither is resent or rolled back",
            self.success(r) and ds[0].get("prompt_received", "MISSING") is False and ds[1].get("prompt_received", "MISSING") is True
            and all(self.issue(f["id"])["status"] == "in_progress" and f["wt"].is_dir() for f in (first, second))
            and len(prompts) == 2 and not any(x["argv"][:2] == ["pane", "close"] for x in r["fake_calls"]), {"call": r, "dispatches": ds})

    def finish(self):
        self.repo = self.out
        final_sha = self.git("-C", str(self.candidate), "rev-parse", "HEAD", cwd=self.out)
        final_status = self.git("-C", str(self.candidate), "status", "--porcelain=v1", "-uall", cwd=self.out)
        unchanged = final_sha == self.report["candidate_sha"] and final_status == self.initial_status
        unchanged = unchanged and all(digest(self.candidate / p) == sha for p, sha in self.manifest.items())
        trace = self.lines(self.out / "process.jsonl")
        bd_calls = [x for x in trace if Path(x["argv"][0]).name.lower() == "bd.exe"]
        self.case("safety-subprocess-routing", "C3", "Owned cwd/executables; independent dispatch bd calls through bdw", bool(trace) and all(x["safe"] for x in trace)
            and all(x["via_bdw"] for x in bd_calls), {"trace": "process.jsonl", "bd_calls": len(bd_calls)})
        self.case("safety-source-readonly", "C3", "Supplied candidate HEAD/status/source hashes unchanged", unchanged,
            {"initial_status": self.initial_status, "final_status": final_status, "final_sha": final_sha})
        self.report["verdict"] = "REJECT" if self.defects else "PASS"
        self.flush()

    def execute(self):
        self.prepare()
        if self.reuse_wiring:
            self.reuse_prior()
        self.report["execution_mode"] = "Full independent execution from scratch (P8-bound)"
        groups = ("round2_cases", "p0_cases", "ownership_and_limits", "model_policy", "predecessor_and_gate", "fill_cases", "status_reconcile", "collect_cases", "c_regressions", "c_start_stop", "transcript_regressions", "author_checks")
        for name in groups:
            print("GROUP " + name, flush=True)
            try:
                getattr(self, name)()
            except Exception:
                error = traceback.format_exc()
                self.report.setdefault("harness_errors", []).append({"group": name, "traceback": error})
                self.case("harness-" + name, "Harness", "Fixture group executes without harness errors", False, error)
                print(error, file=sys.stderr, flush=True)
        self.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--bd", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--reuse-wiring", type=Path, help="Historical option; refused after P8 because prior expectations changed")
    a = parser.parse_args()
    candidate, bd, out = a.candidate.resolve(), a.bd.resolve(), a.out.resolve()
    if out == OWNED or not out.is_relative_to(OWNED) or out.exists():
        parser.error("--out must be a new child directory of this experiment")
    if not candidate.is_dir() or not bd.is_file():
        parser.error("candidate directory and bd executable must exist")
    reuse = a.reuse_wiring.resolve() if a.reuse_wiring else None
    if reuse:
        parser.error("P8 changes prior expectations; --reuse-wiring is disabled. Run from scratch.")
    out.mkdir(parents=True)
    h = Harness(candidate, bd, out, reuse)
    try:
        h.execute()
    except Exception:
        h.report["harness_error"] = traceback.format_exc()
        h.report["verdict"] = "REJECT"
        h.flush()
        print(h.report["harness_error"], file=sys.stderr)
        return 2
    print(json.dumps({"verdict": h.report["verdict"], "counts": h.report["counts"], "report": str(out / "verification.json")}))
    return 0 if h.report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
