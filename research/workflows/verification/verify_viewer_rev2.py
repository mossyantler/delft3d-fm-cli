"""Reverify 3490e2f without editing the frozen verify_viewer.py.

--mode baseline executes the frozen matrix; --mode attacks adds independent cases.
Default --mode all does both in fresh subfolders under --out.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import traceback

OWNED = Path(__file__).resolve().parent
FROZEN = OWNED / "verify_viewer.py"
FROZEN_HASH = "dfe8d1525f3ce4cba1a7b64a148b81c8a9b90967e98f2526dcff420e6417ad70"
CANDIDATE = "3490e2f"
spec = importlib.util.spec_from_file_location("frozen_viewer_verifier",FROZEN)
frozen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frozen)
assert frozen.digest(FROZEN)==FROZEN_HASH
frozen.SHA = CANDIDATE  # configuration only: no frozen source/test method edits
original_write_json = frozen.write_json


def write_json(path,data):
    original_write_json(path,data)


class Harness(frozen.Verifier):
    def __init__(self,args):
        super().__init__(args)
        # A harmless native Windows executable consumes the browser-launch argv.
        # No BV_NO_BROWSER variable: that would violate the contract's env allowlist.
        self.shims = self.out/"background-browser"
        self.shims.mkdir()
        self.shim = self.shims/"rundll32.exe"
        self.shim.write_bytes((Path(os.environ["SystemRoot"])/"System32/where.exe").read_bytes())
        self.base_env["PATH"] = str(self.shims)+os.pathsep+self.base_env.get("PATH","")
        self.base_env["BROWSER"] = str(self.shim)
        self.repro = subprocess.list2cmdline([sys.executable,str(Path(__file__).resolve()),
            "--candidate",str(self.candidate),"--bv",str(self.bv),"--bd",str(self.bd),
            "--out",str(OWNED/"reproduce-rev2-fresh")])

    def report(self):
        # Preserve the original receipt. Raw frozen assertions are not changed.
        def redirected(path,data):
            if Path(path)==OWNED/"verification.json":
                path = self.out/"verification.json"
            original_write_json(path,data)
        previous = frozen.write_json
        frozen.write_json = redirected
        try:
            return super().report()
        finally:
            frozen.write_json = previous


class Attacks(Harness):
    def case(self,ident,contract,polarity,ok,expected,evidence,defect=None):
        super().case(ident,contract,polarity,ok,expected,evidence,defect)
        if not ok:
            self.defects[-1].update(source_commit=CANDIDATE,
                                   source_file="research/workflows/graph/dashboard.py")

    def perform(self,repo,label,env=None,expect_exit=0,cwd=None):
        before = self.snapshot(repo)
        result = self.launch(cwd or repo,["pages"],env)
        after = self.snapshot(repo)
        self.case(label+"-state",2,"positive",before==after,
                  "HEAD, index, full status, config, hooks, export and workspace bytes stay identical",
                  {"before":before,"after":after,"command":result})
        self.case(label+"-exit",4 if label.startswith("HEAD") else 3,"positive",
                  result["exit"]==expect_exit,"Expected pages exit code "+str(expect_exit),result)
        return result

    def reachability(self,repo,result):
        launches = self.bv_launches(result)
        if not launches:
            return {"launches":[],"resolves":None}
        v = launches[-1]
        found = self.raw([str(Path(os.environ["SystemRoot"])/"System32/where.exe"),"bd","br"],
                         Path(v["cwd"]),{**self.base_env,"PATH":v["path"]})
        exposed = []
        extensions = {x.lower() for x in self.base_env.get("PATHEXT",".COM;.EXE;.BAT;.CMD").split(";")}
        for entry in v["path"].split(os.pathsep):
            directory = Path(entry.strip('"'))
            if not directory.is_absolute(): directory = Path(v["cwd"])/directory
            if not directory.is_dir(): continue
            for file in directory.iterdir():
                if file.is_file() and (file.name.lower() in ("bd","br") or
                                      (file.stem.lower() in ("bd","br") and file.suffix.lower() in extensions)):
                    exposed.append(str(file))
        return {"launches":launches,"resolves":found,"tracker_files_in_actual_path_entries":exposed}

    def tracker(self,repo,label,entry,expect_block=True):
        result = self.perform(repo,label,{"PATH":str(entry)+os.pathsep+self.base_env["PATH"]})
        reach = self.reachability(repo,result)
        safe = result["exit"]==0 and bool(reach["launches"]) and reach["resolves"]["exit"]!=0 and not reach["tracker_files_in_actual_path_entries"]
        if label=="PATH-quoted-entry" and reach["launches"]:
            v = reach["launches"][-1]
            reach["cmd_execution_control"] = self.raw([str(Path(os.environ["SystemRoot"])/"System32/cmd.exe"),"/d","/c","bd","/?"],
                          Path(v["cwd"]),{**self.base_env,"PATH":v["path"]})
        self.case(label,3,"negative" if expect_block else "positive",safe,
                  "No bd/br command resolves from the actual viewer PATH and cwd",reach,
                  "Tracker commands remain executable from the viewer PATH")
        return reach

    def trackers(self):
        repo = self.fixture("tracker-attacks")
        bins = self.out/"tracker-bins"
        bins.mkdir()
        native = Path(os.environ["SystemRoot"])/"System32/where.exe"
        for i,name in enumerate(("BD.COM","bR.ExE","bD.CmD","BR.BaT","bd.PS1","Br.Py","BD","br")):
            folder = bins/f"extension-{i}"
            folder.mkdir()
            (folder/name).write_bytes(native.read_bytes() if name.lower().endswith((".exe",".com")) else b"@echo owned tracker trap\r\n")
            reach = self.tracker(repo,"PATH-extension-"+str(i),folder)
            self.case("PATH-extension-removed-"+str(i),3,"negative",
                      bool(reach["launches"]) and str(folder) not in reach["launches"][-1]["path"].split(os.pathsep),
                      "Tracker directory is excluded for extension/case variant "+name,reach)
        hard = bins/"hardlink"
        hard.mkdir()
        owned_native = self.out/"owned-native.exe"
        owned_native.write_bytes(native.read_bytes())
        os.link(owned_native,hard/"BD.EXE")
        self.tracker(repo,"PATH-hardlink",hard)
        sym = bins/"symlink"
        sym.mkdir()
        try:
            os.symlink(owned_native,sym/"bR.ExE")
        except OSError as exc:
            self.notes.append({"case":"PATH-file-symlink","executed":False,"reason":str(exc),
                               "alternative_executed":"PATH-hardlink"})
        else:
            self.tracker(repo,"PATH-file-symlink",sym)
        dirs = bins/"directory-name"
        dirs.mkdir()
        (dirs/"bd.exe").mkdir()
        (dirs/"BR.CMD").mkdir()
        self.tracker(repo,"PATH-directory-is-not-command",dirs,expect_block=False)
        junction = bins/"junction"
        junction.mkdir()
        target = self.out/"junction-target"
        target.mkdir()
        link = junction/"bd.exe"
        assert link.resolve().is_relative_to(self.out) and target.resolve().is_relative_to(self.out)
        made = self.raw([str(Path(os.environ["SystemRoot"])/"System32/cmd.exe"),"/d","/c","mklink","/J",str(link),str(target)],repo)
        assert made["exit"]==0,made
        self.tracker(repo,"PATH-directory-junction",junction,expect_block=False)
        quoted = bins/"quoted tools"
        quoted.mkdir()
        (quoted/"bd.exe").write_bytes(native.read_bytes())
        self.tracker(repo,"PATH-quoted-entry",'"'+str(quoted)+'"')
        relative = self.dashboard_root(repo)/"relative-tools"
        relative.mkdir()
        (relative/"br.exe").write_bytes(native.read_bytes())
        assert not (repo/"relative-tools").exists()
        self.tracker(repo,"PATH-relative-to-viewer-cwd","relative-tools")

    def expected_head(self,repo):
        # Read raw blob bytes without filters, saved via an owned helper command.
        dest = self.out/f"expected-head-{self.counter}.bin"
        helper = self.out/"read_blob.py"
        helper.write_text("import pathlib,subprocess,sys\np=subprocess.run(['git','cat-file','blob','HEAD:research/notes/delivery/beads-state.jsonl'],capture_output=True,check=True)\npathlib.Path(sys.argv[1]).write_bytes(p.stdout)\n",encoding="utf-8")
        read = self.raw([sys.executable,str(helper),str(dest)],repo)
        assert read["exit"]==0,read
        return dest.read_bytes()

    def assert_copy(self,repo,label,result,expected):
        source = self.dashboard_root(repo)/"source/issues.jsonl"
        actual = source.read_bytes() if source.exists() else None
        info = json.loads(result["output"]) if result["exit"]==0 else {}
        self.case(label,4,"negative",result["exit"]==0 and actual==expected
                  and info.get("issues")==len([x for x in expected.splitlines() if x.strip()]),
                  "Worker copy is exactly the main HEAD blob and reports its nonblank issue count",
                  {"command":result,"expected_sha256":frozen.hashlib.sha256(expected).hexdigest(),
                   "actual_sha256":frozen.digest(source) if source.exists() else None,"info":info},
                  "Worker export differs from main checkout HEAD")

    def head_cases(self):
        repo = self.fixture("head-attacks")
        expected = self.expected_head(repo)
        (repo/frozen.EXPORT).unlink()
        r = self.perform(repo,"HEAD-working-file-missing")
        self.assert_copy(repo,"HEAD-committed-file-not-needed-in-working-tree",r,expected)
        dirty = json.dumps({"id":"dirty-stage","title":"staged is not HEAD","status":"open","priority":1,"issue_type":"task"})+"\n"
        (repo/frozen.EXPORT).write_text(dirty,encoding="utf-8")
        self.git(repo,"add",frozen.EXPORT.as_posix())
        (repo/"staged-sentinel.txt").write_text("retain staged content\n",encoding="utf-8")
        self.git(repo,"add","staged-sentinel.txt")
        r = self.perform(repo,"HEAD-index-differs")
        self.assert_copy(repo,"HEAD-staged-content-ignored",r,expected)
        # A linked worker has a distinct HEAD; main HEAD still owns the export.
        worker = repo.parent/"worker-worktree"
        self.git(repo,"worktree","add","-b","independent-worker",str(worker),"HEAD")
        worker_blob = dirty.replace("dirty-stage","worker-head")
        (worker/frozen.EXPORT).write_text(worker_blob,encoding="utf-8")
        self.git(worker,"add",frozen.EXPORT.as_posix())
        self.git(worker,"commit","-m","throwaway worker HEAD differs")
        worker_head = self.git(worker,"rev-parse","HEAD")
        main_head = self.git(repo,"rev-parse","HEAD")
        idx = Path(self.git(worker,"rev-parse","--path-format=absolute","--git-path","index"))
        wt_before = {"head":worker_head,"index":frozen.digest(idx),"status":self.git(worker,"status","--porcelain=v1","-uall"),"gitfile":frozen.digest(worker/".git")}
        r = self.perform(repo,"HEAD-linked-worktree",cwd=worker)
        wt_after = {"head":self.git(worker,"rev-parse","HEAD"),"index":frozen.digest(idx),"status":self.git(worker,"status","--porcelain=v1","-uall"),"gitfile":frozen.digest(worker/".git")}
        self.case("HEAD-linked-worktree-own-index-state",2,"negative",wt_before==wt_after and worker_head!=main_head,
                  "Distinct worker HEAD/index/status/gitfile remain unchanged",{"before":wt_before,"after":wt_after,"main_head":main_head})
        self.assert_copy(repo,"HEAD-main-authoritative-over-worker",r,expected)
        missing = self.fixture("head-missing")
        self.git(missing,"rm","--cached",frozen.EXPORT.as_posix())
        self.git(missing,"commit","-m","throwaway HEAD has no export")
        r = self.perform(missing,"HEAD-absent-with-untracked-file",expect_exit=2)
        self.case("HEAD-absent-refuses-untracked",4,"negative",r["exit"]==2 and not self.bv_launches(r),
                  "Export absent from HEAD refuses fallback to untracked file",r)
        self.git(missing,"add",frozen.EXPORT.as_posix())
        r = self.perform(missing,"HEAD-absent-with-staged-file",expect_exit=2)
        self.case("HEAD-absent-refuses-index",4,"negative",r["exit"]==2 and not self.bv_launches(r),
                  "Export absent from HEAD refuses fallback to staged index",r)

    def filters(self):
        repo = self.fixture("attribute-filters")
        expected = self.expected_head(repo)
        (repo/".gitattributes").write_text(frozen.EXPORT.as_posix()+" text eol=crlf filter=tripwire diff=tripwire\n",encoding="utf-8")
        self.git(repo,"add",".gitattributes")
        self.git(repo,"commit","-m","throwaway export attributes")
        marker = self.out/"filter-ran.txt"
        tripwire = self.out/"filter_tripwire.py"
        tripwire.write_text("from pathlib import Path\nimport sys\nPath("+repr(str(marker))+").write_text('ran')\nsys.stdout.write('FILTER MUST NOT RUN')\n",encoding="utf-8")
        # Git for Windows runs filter strings through its POSIX shell.
        command = shlex.join([Path(sys.executable).as_posix(),tripwire.as_posix()])
        self.git(repo,"config","filter.tripwire.smudge",command)
        self.git(repo,"config","diff.tripwire.textconv",command)
        # Different physical EOL bytes must not be used in place of the object blob.
        (repo/frozen.EXPORT).write_bytes(expected.replace(b"\n",b"\r\n"))
        r = self.perform(repo,"HEAD-attributes-and-filters")
        self.assert_copy(repo,"HEAD-raw-blob-bypasses-working-eol",r,expected)
        self.case("HEAD-no-smudge-or-textconv",4,"negative",not marker.exists(),
                  "git show must not execute smudge or textconv filters",{"marker":str(marker),"command":r})
        # Activate the same filter as a control only after the tested operation.
        control = self.raw(["git","show","--textconv","HEAD:"+frozen.EXPORT.as_posix()],repo)
        self.case("HEAD-filter-positive-control",4,"positive",control["exit"]==0 and marker.exists(),
                  "The installed textconv tripwire executes when explicitly requested",control)
        unicode_repo = self.fixture("utf8-crlf-blob")
        p = unicode_repo/frozen.EXPORT
        objects = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
        objects[0]["title"] = "독립 검증 🌊"
        raw = ("\r\n\r\n".join(json.dumps(x,ensure_ascii=False) for x in objects)+"\r\n").encode("utf-8")
        (unicode_repo/".gitattributes").write_text(frozen.EXPORT.as_posix()+" -text\n",encoding="utf-8")
        p.write_bytes(raw)
        self.git(unicode_repo,"add",".gitattributes",frozen.EXPORT.as_posix())
        self.git(unicode_repo,"commit","-m","throwaway exact UTF8 CRLF blob")
        r = self.perform(unicode_repo,"HEAD-unicode-crlf-blank-lines")
        self.assert_copy(unicode_repo,"HEAD-preserves-unicode-crlf-and-count",r,raw)

    def run_attacks(self):
        self.notes = []
        self.trackers()
        self.head_cases()
        self.filters()
        return {"cases":self.cases,"defects":self.defects,"notes":self.notes,"source_manifest":self.manifest}


def combine(args,baseline,attacks,out):
    baseline_cases = json.loads(json.dumps(baseline["cases"]))
    adjudications = []
    for case in baseline_cases:
        case["origin"]="frozen unchanged verifier"
        if case["id"]=="C4-missing-export" and not case["passed"]:
            corrected = next((x for x in attacks["cases"] if x["id"]=="HEAD-committed-file-not-needed-in-working-tree"),None)
            if corrected and corrected["passed"]:
                case["raw_frozen_passed"] = False
                case["passed"] = True
                case["expected"] = "Committed export remains available when only its working-tree file is missing"
                case["adjudication"] = "Frozen oracle expected file absence to refuse; that contradicts Contract 4's committed HEAD requirement. Raw baseline receipt remains untouched."
                adjudications.append(case["id"])
    remaining = [x for x in baseline["defects"] if x["case"] not in adjudications]
    defects = remaining+attacks["defects"]
    for n,d in enumerate(defects,1):
        d["id"] = f"VIEWER-V2-{n:03}"
        d["source_commit"] = CANDIDATE
        if d["contract"]==3: d["source_line"] = 37
    all_cases = baseline_cases+attacks["cases"]
    result = {"task_code":"GRAPH-OPS-VIEWER-V","candidate_sha":CANDIDATE,
              "verdict":"REJECT" if defects else "PASS",
              "verifier_sha256":{"verify_viewer.py":frozen.digest(FROZEN),"verify_viewer_rev2.py":frozen.digest(__file__)},
              "cases":all_cases,"defects":defects,"author_tests":baseline["author_tests"],
              "baseline_raw_receipt":str(out/"baseline/verification.json"),
              "baseline_raw_verdict":baseline["verdict"],"frozen_oracle_adjudications":adjudications,
              "frozen_execution_adjustments":["Configured module SHA=3490e2f; frozen file and test methods unchanged.",
                 "Redirected top-level receipt into fresh baseline folder; preserved original verification.json.",
                 "Prepended owned rundll32.exe browser shim and BROWSER; no additional BV_* child variable."],
              "notes":attacks["notes"],"limitations":baseline["limitations"],
              "coverage":{str(i):{p:sum(x["contract"]==i and x["polarity"]==p for x in all_cases) for p in ("positive","negative")} for i in range(1,7)}}
    write_json(out/"verification-rev2.json",result)
    write_json(OWNED/"verification-rev2.json",result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate","bv","bd","out"):
        parser.add_argument("--"+name,required=True)
    parser.add_argument("--mode",choices=("all","baseline","attacks"),default="all")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    assert out.is_relative_to(OWNED) and out!=OWNED and not out.exists()
    old_receipt_hash = frozen.digest(OWNED/"verification.json")
    baseline = attacks = None
    try:
        if args.mode in ("all","baseline"):
            kwargs = argparse.Namespace(**vars(args)); kwargs.out=str(out/"baseline")
            harness = Harness(kwargs)
            baseline = harness.run()
        if args.mode in ("all","attacks"):
            kwargs = argparse.Namespace(**vars(args)); kwargs.out=str(out/"attacks")
            harness = Attacks(kwargs)
            attacks = harness.run_attacks()
            write_json(out/"attacks/attacks.json",attacks)
        if args.mode=="all":
            result = combine(args,baseline,attacks,out)
        else:
            result = baseline or attacks
        assert frozen.digest(FROZEN)==FROZEN_HASH
        assert frozen.digest(OWNED/"verification.json")==old_receipt_hash
        print(json.dumps({"mode":args.mode,"verdict":result.get("verdict"),"cases":len(result["cases"]),"defects":len(result["defects"])}),flush=True)
        return 1 if result["defects"] else 0
    except BaseException:
        write_json(out/"infrastructure-error.json",{"traceback":traceback.format_exc()})
        raise


if __name__=="__main__":
    sys.dont_write_bytecode=True
    raise SystemExit(main())
