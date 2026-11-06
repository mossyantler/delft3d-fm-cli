"""Independent rev3 verifier; frozen verifier files remain byte-for-byte unchanged."""
from __future__ import annotations

import argparse
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

sys.dont_write_bytecode = True
OWNED = Path(__file__).resolve().parent
PIN = "428a2e2"
PINS = {"verify_viewer.py":"dfe8d1525f3ce4cba1a7b64a148b81c8a9b90967e98f2526dcff420e6417ad70",
        "verify_viewer_rev2.py":"eef42a73ae9326916c5a645f22f187415313faafd85156c5d2b39297acb37ce6"}
spec = importlib.util.spec_from_file_location("prior_verifier",OWNED/"verify_viewer_rev2.py")
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
base = prior.frozen
for name,digest in PINS.items(): assert base.digest(OWNED/name)==digest
prior.CANDIDATE = PIN
base.SHA = PIN


FUNCTION_PROBE = '''import json,ntpath,os,pathlib,sys
sys.path.insert(0,sys.argv[1])
from research.workflows.graph import dashboard
request=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
env=request["environment"] if request.get("already_child") else dashboard.viewer_env(request["environment"])
entries=[]
for entry in env.get("PATH","").split(os.pathsep):
 if not entry: continue
 drive,tail=ntpath.splitdrive(entry)
 absolute=bool(drive) and (tail.startswith(("\\\\","/")) or drive.startswith("\\\\\\\\"))
 result={"entry":entry,"absolute":absolute,"listable":False,"trackers":[]}
 try:
  with os.scandir(entry) as iterator:
   files=list(iterator)
  result["listable"]=True
  result["trackers"]=[x.name for x in files if x.is_file() and ntpath.splitext(x.name)[0].casefold() in ("bd","br")]
 except OSError as exc: result["error"]={"type":type(exc).__name__,"winerror":getattr(exc,"winerror",None)}
 entries.append(result)
data={"environment":env,"entries":entries,"path_keys":[k for k in env if k.upper()=="PATH"]}
pathlib.Path(sys.argv[3]).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
'''


class Attacks(prior.Harness):
    def __init__(self,args):
        super().__init__(args)
        self.notes=[]
        self.probe = self.out/"probe_environment.py"
        self.probe.write_text(FUNCTION_PROBE,encoding="utf-8")
        self.repro=subprocess.list2cmdline([sys.executable,str(Path(__file__).resolve()),
            "--candidate",str(self.candidate),"--bv",str(self.bv),"--bd",str(self.bd),
            "--out",str(OWNED/"reproduce-rev3-fresh")])

    def case(self,ident,contract,polarity,ok,expected,evidence,defect=None):
        super().case(ident,contract,polarity,ok,expected,evidence,defect)
        if not ok:
            self.defects[-1].update(id=f"VIEWER-V3-{len(self.defects):03}",source_commit=PIN,
                                   source_file="research/workflows/graph/dashboard.py",source_line=44)

    def function(self,repo,label,environment,blocked=(),keep=(),polarity="negative",already_child=False):
        request=self.out/(label+"-input.json")
        output=self.out/(label+"-output.json")
        base.write_json(request,{"environment":environment,"already_child":already_child})
        command=self.raw([sys.executable,str(self.probe),str(repo),str(request),str(output)],repo)
        data=json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        entries=data.get("entries",[])
        kept=[x["entry"] for x in entries]
        special={k:v for k,v in data.get("environment",{}).items() if k.upper().startswith(base.PREFIXES)}
        safe=command["exit"]==0 and data.get("path_keys")==["PATH"] and special=={"BV_NO_UPDATE_CHECK":"1"}
        safe=safe and all(x["absolute"] and x["listable"] and not x["trackers"] for x in entries)
        safe=safe and all(x not in kept for x in blocked) and all(x in kept for x in keep)
        self.case(label,3,polarity,safe,
                  "One PATH; kept entries are absolute, listable and tracker-free; required prefixes are stripped",
                  {"command":command,"input":str(request),"probe":data,"blocked":list(blocked),"required_kept":list(keep)})
        return data

    def actual(self,repo,label,path):
        before=self.snapshot(repo)
        result=self.launch(repo,["pages"],{"PATH":path})
        after=self.snapshot(repo)
        self.case(label+"-state",2,"positive",before==after,"All protected bytes and Git state stay unchanged",
                  {"before":before,"after":after,"command":result})
        launches=self.bv_launches(result)
        probes=[]
        for child in launches:
            data=self.function(repo,label+"-child-environment",{"PATH":child["path"],**child["special_env"]},polarity="positive",already_child=True)
            probes.append(data)
        self.case(label,3,"negative",result["exit"]==0 and bool(launches) and all(
                  x["special_env"]=={"BV_NO_UPDATE_CHECK":"1"} and Path(x["cwd"])==self.dashboard_root(repo)
                  and x["argv"][1:3]==["--db",str(self.dashboard_root(repo)/"source/issues.jsonl")] for x in launches),
                  "Real pages starts pinned bv with only the copied db and restricted environment",{"command":result,"probes":probes})
        return result

    def paths(self):
        repo=self.fixture("path-boundaries")
        bins=self.out/"path-fixtures"
        bins.mkdir()
        safe=bins/"safe dir"; safe.mkdir()
        evil=bins/"tracker dir"; evil.mkdir()
        (evil/"bD.CmD").write_text("@echo owned trap\n",encoding="ascii")
        file=bins/"not-a-directory"; file.write_text("regular file",encoding="ascii")
        missing=bins/"absent"
        suffix=os.pathsep+self.base_env["PATH"]
        variants=[
          ("plain-safe",str(safe),(),(str(safe),),"positive"),
          ("plain-tracker",str(evil),(str(evil),),(),"negative"),
          ("spaces-safe","  "+str(safe)+"  ",(),(str(safe),),"positive"),
          ("spaces-tracker","  "+str(evil)+"  ",(str(evil),),(),"negative"),
          ("quoted-spaces-safe",'  " '+str(safe)+' "  ',(),(str(safe),),"positive"),
          ("quoted-spaces-tracker",'  " '+str(evil)+' "  ',(str(evil),),(),"negative"),
          ("opening-quote-safe",'"'+str(safe),(),(),"negative"),
          ("opening-quote-tracker",'"'+str(evil),(str(evil),),(),"negative"),
          ("closing-quote-safe",str(safe)+'"',(),(),"negative"),
          ("closing-quote-tracker",str(evil)+'"',(str(evil),),(),"negative"),
          ("repeated-quotes-safe",'""'+str(safe)+'""',(),(),"negative"),
          ("repeated-quotes-tracker",'""'+str(evil)+'""',(str(evil),),(),"negative"),
          ("embedded-quote",str(safe/'in"valid'),(),(),"negative"),
          ("trailing-text-after-quote",'"'+str(evil)+'"junk',(),(),"negative"),
          ("root-relative",str(evil)[2:],(str(evil)[2:],),(),"negative"),
          ("drive-relative",repo.drive+"relative-tools",(repo.drive+"relative-tools",),(),"negative"),
          ("dot-relative",".",(".",),(),"negative"),
          ("parent-relative","..",("..",),(),"negative"),
          ("empty","",(),(),"negative"),
          ("whitespace","   ",(),(),"negative"),
          ("missing",str(missing),(str(missing),),(),"negative"),
          ("regular-file",str(file),(str(file),),(),"negative"),
          ("extended-safe","\\\\?\\"+str(safe),(),("\\\\?\\"+str(safe),),"positive"),
          ("extended-tracker","\\\\?\\"+str(evil),("\\\\?\\"+str(evil),),(),"negative"),
          ("variable-only","%VIEWER_TOOLS%",("%VIEWER_TOOLS%",),(),"negative"),
          ("variable-suffix",str(bins/"%VIEWER_LEAF%"),(str(bins/"%VIEWER_LEAF%"),),(),"negative"),
          ("tilde","~\\tools",("~\\tools",),(),"negative"),
        ]
        (repo/"relative-tools").mkdir()
        (repo/"relative-tools/br.exe").write_bytes(b"trap")
        self.dashboard_root(repo).mkdir(parents=True,exist_ok=True)
        (self.dashboard_root(repo)/"relative-tools").mkdir()
        (self.dashboard_root(repo)/"relative-tools/br.exe").write_bytes(b"trap")
        for label,entry,blocked,keep,polarity in variants:
            self.function(repo,"RULE-"+label,{"Path":entry,"BD_TEST":"x","bEaDs_TEST":"x","bV_TEST":"x","dFm_TEST":"x",
                           "VIEWER_TOOLS":str(evil),"VIEWER_LEAF":"tracker dir"},blocked,keep,polarity)
        # Loopback administrative UNC aliases point only at owned fixture paths.
        for label,target in (("safe",safe),("tracker",evil)):
            unc="\\\\localhost\\"+target.drive[0]+"$"+str(target)[2:]
            try:
                with os.scandir(unc) as entries: list(entries)
                listable=True
            except OSError as exc:
                listable=False
                self.notes.append({"case":"UNC-"+label,"listable":False,"reason":str(exc)})
            self.function(repo,"RULE-unc-"+label,{"PATH":unc},blocked=(unc,) if label=="tracker" or not listable else (),
                          keep=(unc,) if label=="safe" and listable else (),polarity="positive" if listable and label=="safe" else "negative")
        self.function(repo,"RULE-duplicate-path-keys",{"Path":str(evil),"PATH":str(safe),"PaTh":"relative-tools", "pAtH":str(missing),
                      "BEADS_TEST":"x","BV_NO_UPDATE_CHECK":"0"},blocked=(str(evil),"relative-tools",str(missing)),keep=(str(safe),))
        self.function(repo,"RULE-empty-duplicate-keys",{"Path":"","PATH":".","PaTh":str(evil)},blocked=(str(evil),"."))
        # Representative end-to-end commands preserve real environment and Git state.
        for label,entry in (("quoted",'  "'+str(evil)+'"  '),("root-relative",str(evil)[2:]),
                            ("drive-relative",repo.drive+"relative-tools"),("extended","\\\\?\\"+str(evil)),
                            ("missing",str(missing)),("variable","%VIEWER_TOOLS%")):
            self.actual(repo,"REAL-"+label,entry+suffix)
        self.acl(repo,bins)
        self.reduced(repo)

    def acl(self,repo,bins):
        directory=bins/"denied-list"
        directory.mkdir()
        (directory/"br.cmd").write_text("@echo forbidden",encoding="ascii")
        principal=os.environ.get("USERDOMAIN","")+"\\"+os.environ["USERNAME"]
        icacls=str(Path(os.environ["SystemRoot"])/"System32/icacls.exe")
        setup=self.raw([icacls,str(directory),"/deny",principal+":(RD)"],repo)
        established=False
        try:
            try:
                with os.scandir(directory) as entries: list(entries)
            except PermissionError:
                established=True
            if setup["exit"]==0 and established:
                self.function(repo,"RULE-denied-list-directory",{"PATH":str(directory)},blocked=(str(directory),))
                self.actual(repo,"REAL-denied-list",str(directory)+os.pathsep+self.base_env["PATH"])
            else:
                self.notes.append({"case":"RULE-denied-list-directory","executed":False,"fixture_setup":setup,"denial_observed":established})
        finally:
            restored=self.raw([icacls,str(directory),"/remove:d",principal],repo)
            with os.scandir(directory) as entries: list(entries)
            self.case("RULE-acl-restored",3,"positive",restored["exit"]==0,"Owned temporary deny ACL is removed",restored)

    def reduced(self,repo):
        git=shutil.which("git",path=self.base_env["PATH"])
        assert git
        minimal=os.pathsep.join([str(self.shims),str(Path(git).parent),str(Path(os.environ["SystemRoot"])/"System32")])
        dirty=self.out/"path-fixtures/tracker dir"
        requested='.;C:relative-tools;"'+str(dirty)+'";'+minimal
        before=self.snapshot(repo)
        r=self.launch(repo,["pages"],{"PATH":requested})
        after=self.snapshot(repo)
        launches=self.bv_launches(r)
        self.case("REDUCED-pages",3,"positive",r["exit"]==0 and bool(launches) and all(x["path"]==minimal for x in launches),
                  "Pages works with exactly shim, Git and System32 after unsafe entries are dropped",r)
        self.case("REDUCED-pages-state",2,"positive",before==after,"Reduced PATH pages preserves protected state",{"before":before,"after":after})
        self.preview(repo,"REDUCED",{"PATH":requested})
        before=self.snapshot(repo)
        r=self.launch(repo,["tui"],{"PATH":requested},timeout=3)
        after=self.snapshot(repo)
        launches=self.bv_launches(r)
        self.case("REDUCED-tui-startup",3,"positive",bool(launches) and all(x["path"]==minimal and x["special_env"]=={"BV_NO_UPDATE_CHECK":"1"} for x in launches),
                  "TUI reaches pinned bv startup with the reduced PATH; interactive terminal behavior is outside scope",r)
        self.case("REDUCED-tui-state",2,"positive",before==after,"Reduced PATH TUI startup preserves protected state",{"before":before,"after":after})

    def run_new(self):
        self.paths()
        remaining=self.port9000()
        self.case("REV3-final-port",5,"negative",not remaining,"No listener remains on port 9000",remaining)
        return {"cases":self.cases,"defects":self.defects,"notes":self.notes,"source_manifest":self.manifest}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("candidate","bv","bd","out"): parser.add_argument("--"+key,required=True)
    parser.add_argument("--mode",choices=("all","attacks"),default="all")
    args=parser.parse_args()
    out=Path(args.out).resolve()
    assert out.is_relative_to(OWNED) and out!=OWNED and not out.exists()
    old={name:base.digest(OWNED/name) for name in ("verification.json","verification-rev2.json")}
    previous=None
    try:
        if args.mode=="all":
            original=prior.write_json
            def routed(path,data):
                if Path(path)==OWNED/"verification-rev2.json": path=out/"previous/verification-rev2.json"
                original(path,data)
            prior.write_json=routed
            saved=sys.argv
            sys.argv=[str(OWNED/"verify_viewer_rev2.py"),"--candidate",args.candidate,"--bv",args.bv,"--bd",args.bd,"--out",str(out/"previous")]
            try: prior.main()
            finally:
                sys.argv=saved
                prior.write_json=original
            previous=json.loads((out/"previous/verification-rev2.json").read_text(encoding="utf-8"))
        kwargs=argparse.Namespace(**vars(args)); kwargs.out=str(out/"new-cases")
        runner=Attacks(kwargs)
        additional=runner.run_new()
        base.write_json(out/"new-cases/cases.json",additional)
        all_cases=(previous["cases"] if previous else [])+additional["cases"]
        defects=(previous["defects"] if previous else [])+additional["defects"]
        for n,d in enumerate(defects,1): d.update(id=f"VIEWER-V3-{n:03}",source_commit=PIN)
        hashes={name:base.digest(OWNED/name) for name in (*PINS,"verify_viewer_rev3.py")}
        for name,pin in PINS.items(): assert hashes[name]==pin
        assert all(base.digest(OWNED/name)==value for name,value in old.items())
        result={"task_code":"GRAPH-OPS-VIEWER-V","candidate_sha":PIN,"verdict":"REJECT" if defects else "PASS",
                "verifier_sha256":hashes,"cases":all_cases,"defects":defects,
                "author_tests":previous["author_tests"] if previous else {"executed":False},
                "notes":additional["notes"],"previous_run_receipt":str(out/"previous/verification-rev2.json") if previous else None,
                "execution_adjustments":["Both frozen scripts and test methods unchanged; configured prior.CANDIDATE and frozen.SHA=428a2e2.",
                    "Redirected earlier top-level receipts into fresh run folders; old receipts preserved.",
                    "Old rev2 raw execution_adjustments contains a static 3490e2f message; actual candidate and source manifests use 428a2e2.",
                    "Accepted C4-missing-export adjudication retained from rev2."],
                "limitations":["TUI covers startup with redirected streams, not interactive editing.",
                    "UNC keep/drop assertions depend on observed loopback SMB listability; no external share is accessed.",
                    "Real Beads is not read or written. Only owned throwaway repositories/workspaces are exercised."],
                "coverage":{str(i):{p:sum(c["contract"]==i and c["polarity"]==p for c in all_cases) for p in ("positive","negative")} for i in range(1,7)}}
        base.write_json(out/"verification-rev3.json",result)
        if args.mode=="all": base.write_json(OWNED/"verification-rev3.json",result)
        print(json.dumps({"verdict":result["verdict"],"cases":len(all_cases),"defects":len(defects)}),flush=True)
        return 1 if defects else 0
    except BaseException:
        base.write_json(out/"infrastructure-error.json",{"traceback":traceback.format_exc()})
        raise


if __name__=="__main__": raise SystemExit(main())
