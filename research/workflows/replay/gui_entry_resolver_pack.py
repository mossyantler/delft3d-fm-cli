"""Export additive resolver scripts and exact read-only transfer-validator dependency.

No suite, Framework, profile, target assembly or settings files are copied/changed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode=True
if __package__:
    from . import gui_entry_resolver as resolver
    from . import gui_entry_resolver_windows as windows
else:
    import gui_entry_resolver as resolver
    import gui_entry_resolver_windows as windows


def pack(out):
    here=Path(__file__).resolve()
    assets=here.parents[2]/"assets/gui-entry-resolver"
    out=resolver.no_links(out).resolve()
    for source in (here.parent,assets):
        resolver.require(not out.is_relative_to(source) or source==assets,"output_overlap","Destination overlaps resolver source")
    dependency=resolver.no_links(here.with_name("gui_guest_controller_proof.py"))
    resolver.require(resolver.sha(dependency)==windows.CONTROLLER_PROOF_SHA,"dependency_changed","Frozen controller validator differs")
    out.mkdir(parents=True,exist_ok=False);(out/"scripts").mkdir()
    for path in sorted(here.parent.glob("gui_entry_resolver*.py")):
        shutil.copyfile(path,out/"scripts"/path.name)
    shutil.copyfile(dependency,out/"scripts/gui_guest_controller_proof.py")
    for name in ("README.md","requirements.txt","I_V_CONTRACT.json"):
        shutil.copyfile(assets/name,out/name)
    files={p.relative_to(out).as_posix():{"sha256":resolver.sha(p),"bytes":p.stat().st_size} for p in sorted(out.rglob("*")) if p.is_file()}
    resolver.write_new(out/"package.json",{"schema":1,"purpose":"unsigned read-only resolver code package, not controller authority",
                       "files":files,"native_ready":False,"controller_proof_emitted":False,
                       "frozen_dependency_sha256":windows.CONTROLLER_PROOF_SHA})
    return {"state":"packed","path":str(out),"sha256":resolver.sha(out/"package.json"),"native_ready":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path,required=True)
    print(json.dumps(pack(parser.parse_args().out),indent=2))
