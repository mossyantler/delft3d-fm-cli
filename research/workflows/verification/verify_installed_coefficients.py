"""Public installed B11 edits: byte controls and optional manual/native output equality."""
import argparse
import json
from pathlib import Path
import shutil

from .verify_observation_public import Commands, DISPATCH, dispatch, installed_identity, inventory, natural, need, save
from .verify_boundary_line_coefficients import OUTPUTS, compare_dataset


def invoke(commands, args, label, *arguments):
    obj = json.loads(commands.raw(label, [args.dfm, *arguments]))
    need(obj.get("ok") is True and obj["protocol_version"] == 2, label)
    return obj["result"]


def inserted_offset(raw):
    parts = raw.split(b"[Forcing]")
    ids = set()
    for i in range(1,len(parts)):
        names = [line[7:] for line in parts[i].splitlines() if line.startswith(b"Name = ")]
        need(len(names)==1, "Incorrect support fixture")
        if names[0] not in (b"east_0001", b"east_0002"):
            continue
        need(names[0] not in ids and parts[i].count(b"Quantity = time\n") == 1 and b"Offset =" not in parts[i],
             "Implicit control changed")
        parts[i] = parts[i].replace(b"Quantity = time\n", b"Offset = 0.125\nQuantity = time\n")
        ids.add(names[0])
    need(len(ids)==2, "Missing east support controls")
    return b"[Forcing]".join(parts)


def run(args):
    args.out.mkdir(parents=True,exist_ok=False)
    commands = Commands(args.out)
    report = {"state":"preparing", "cases":{}, "native_started":False}
    try:
        package = installed_identity(args, commands); report["wheel_sha256"] = package["wheel_sha256"]
        edits = (("explicit-factor","default","east_factor2",["--factor","2"]),
                 ("explicit-offset","default","east_offset0125",["--offset","0.125","--unit","m"]),
                 ("implicit-offset","east_implicit_defaults","east_offset0125",["--offset","0.125","--unit","m"]))
        for label, source, reference, change in edits:
            folder = args.out/"cases"/label
            shutil.copytree(args.inputs/source,folder)
            before = inventory(folder,mtimes=True)
            common = ("boundary","coefficients",folder/"model.mdu","--boundary","east","--quantity","waterlevelbnd")
            invoke(commands,args,label+"-read",*common)
            preview = invoke(commands,args,label+"-preview",*common,*change)
            need(preview["applied"] is False and preview["active_count"]==2 and inventory(folder,mtimes=True)==before,"Preview wrote or missed supports")
            applied = invoke(commands,args,label+"-apply",*common,*change,"--apply","--expect-sha256",preview["input_sha256"])
            need(applied["applied"] is True and applied["input_sha256"]==preview["input_sha256"],"Consent mismatch")
            after = inventory(folder,mtimes=True)
            need(before.keys()==after.keys() and {k for k in after if before[k]!=after[k]}=={"boundaries.bc"}, "Other model input changed")
            path = folder/"boundaries.bc"
            expected = (args.inputs/reference/"boundaries.bc").read_bytes() if source=="default" else inserted_offset((args.inputs/source/"boundaries.bc").read_bytes())
            need(path.read_bytes()==expected, "BC differs from independent byte control")
            row = report["cases"][label] = {"before_sha256":before[path.name]["sha256"],"after_sha256":after[path.name]["sha256"],
                                            "active_supports":2,"exact_expected_BC":True,"other_files_preserved":len(before)-1}
            if args.execute:
                dispatch(args); report["native_started"]=True
                save(args.out/"verification.json",report)
                run_dir = args.out/"runs"/label
                manual_dir = args.manual_runs/(reference+"_manual")
                manual = natural(manual_dir)
                commands.cli(args,label+"-run","run","start",folder/"model.mdu","--route","direct","--install",
                             args.install,"--out",run_dir,"--timeout","60",timeout=100)
                row["terminal"] = natural(run_dir,version=package["version"],executable_sha=manual["executable_sha256"])
                row["datasets"] = {k:compare_dataset(run_dir/"model/output"/name,manual_dir/"model/output"/name,k)["every_variable_exact"]
                                   for k,name in OUTPUTS.items()}
                need(inventory(folder,mtimes=True)==after,"Run modified source")
        report["state"] = "passed_installed_edits_and_native_outputs" if args.execute else "passed_installed_edits"
    except Exception as exc:
        report.update(state="failed",error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        save(args.out/"verification.json",report)
    print(report["state"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for opt in ("dfm","install","inputs","out","manual-runs"):
        parser.add_argument("--"+opt,type=lambda s:Path(s).resolve(),required=True)
    parser.add_argument("--execute",action="store_true")
    parser.add_argument("--native-slot-granted",type=int)
    parser.add_argument("--lease-owner")
    parser.add_argument("--dispatch",type=Path,default=DISPATCH)
    run(parser.parse_args())
