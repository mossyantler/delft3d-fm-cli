"""E012 pre-integration contract and static installation/input planning.

Native calls use explicit preview/apply hashes and local ownership checks.
No service, credential registration, firewall change, remote host, shell launch,
or fallback MPI executable is permitted. Presence/flags do not establish MPI
support. Production registration remains gated on M5-G and E012-I/V/G.

Evidence: Delft3D 5a4649830b1e5072caf019fb4850bbdefd9ad431,
examples/dflowfm/02_dflowfm_parallel/run_parallel.bat:24-33 and dimr_config.xml;
src/engines_gpl/dimr/scripts/generic/win64/run_dimr_parallel.bat:3-4,111-112.
Installed scripts are independently hashed, never inferred from that commit.
FM UM 2026.02 section 8.4.4.2, printed 134-135 / PDF 160-161 documents
dfmoutput mapmerge --infile FILE1 FILE2 --outfile DST (also restart datasets).
History is centralized on rank 0 (section 8.4.4, printed 133 / PDF 159).
Intel Windows MPI reference documents -localonly and shm transport:
https://www.intel.com/content/www/us/en/docs/mpi-library/developer-reference-windows/2021-8/global-hydra-options.html
https://www.intel.com/content/www/us/en/docs/mpi-library/developer-reference-windows/2021-9/communication-fabrics-control.html
These are documentation claims until the pinned installed binaries are replayed.
E012-V-native-20261104-01: the installed mpiexec rejected -noprompt before any
guard started, despite that option appearing in a different Intel reference.
Use only the packaged script's -localonly syntax, closed stdin, and bounded
timeouts. Do not substitute service/remote modes or credential/prompt handling.
E012-V-native-20261104-02: both guards reached their exact Job, but DIMR MPI_Init
could not write PMI_fd. The next targeted worker preserves the single validated
inherited Hydra PMI_FD pipe/socket using STARTUPINFO.handle_list with close_fds
still true. That transport handoff requires a fresh native replay; no broad
inheritance or alternate MPI/service mode is enabled by the implementation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from .common import DfmError, sha, utc_now
from .installation import select
from .model import Mdu, validate_mdu
from .runs import profile


def native_platform():
    if os.name!="nt":
        raise DfmError("unsupported_platform","E012 native profile requires local Windows",3)


def read_json(path, limit=4_000_000):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key]=value
        return result
    try:
        with Path(path).open("rb") as stream:
            raw=stream.read(limit+1)
        if len(raw)>limit:
            raise ValueError("JSON size bound exceeded")
        result=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if not isinstance(result,dict):
            raise ValueError("expected object")
        return result
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise DfmError("mpi_invalid_record","Invalid bounded MPI JSON record",3,{"path":str(path),"reason":str(exc)}) from exc


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def files_unchanged(entries):
    for entry in entries:
        path=Path(entry["path"])
        if not path.is_file() or sha(path)!=entry["sha256"]:
            raise DfmError("mpi_input_changed","MPI input/tool fingerprint changed",4,str(path))


def environment(installation):
    kernels=Path(installation["kernels"])
    env=os.environ.copy()
    removed=[]
    for key in list(env):
        if key.upper().startswith(("I_MPI_","HYDRA_","PMI_","PMIX_","FI_","OMP_","MKL_")) or key.upper() in ("PROJ_DATA","PROJ_LIB"):
            removed.append(key)
            del env[key]
    paths=[kernels/"share",kernels/"lib",kernels/"bin"]
    if os.environ.get("SystemRoot"):
        paths.append(Path(os.environ["SystemRoot"])/"System32")
    overrides={"PATH":os.pathsep.join(map(str,paths)),"D3D_HOME":str(kernels),"I_MPI_ROOT":str(kernels),
               "I_MPI_FABRICS":"shm","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1"}
    if installation["proj_data"]:
        overrides.update(PROJ_DATA=installation["proj_data"],PROJ_LIB=installation["proj_data"])
    env.update(overrides)
    return env,overrides,sorted(removed)


def inspect_install(installation=None):
    found=select(installation)
    kernels=Path(found["kernels"])
    names=("bin/dflowfm-cli.exe","bin/dimr.exe","bin/mpiexec.exe","bin/hydra_pmi_proxy.exe",
           "bin/dfmoutput.exe","lib/dflowfm.dll","lib/dimr.dll","lib/impi.dll",
           "bin/run_dimr_parallel.bat","bin/run_dflowfm.bat","bin/run_dfmoutput.bat")
    tools=[]
    for name in names:
        path=kernels/name
        tools.append({"relative_path":name,"path":str(path),"exists":path.is_file(),"sha256":sha(path) if path.is_file() else None})
    script=kernels/"bin/run_dimr_parallel.bat"
    script_text=script.read_text(errors="replace").lower() if script.is_file() else ""
    _,overrides,removed=environment(found)
    return {"installation":found,"tools":tools,"localonly_script_claim": "-localonly" in script_text and "without the hydra service" in script_text,
            "environment_overrides":overrides,"environment_removed":removed,
            "engine_version":None,"mpi_runtime_version":None,"native_capability":"unverified; no executable invoked",
            "source_reference":"5a4649830b1e5072caf019fb4850bbdefd9ad431; not an installed binary commit"}


def plan(mdu, out, installation=None, ranks=2, timeout=45):
    if type(ranks) is not int or not 2<=ranks<=4:
        raise DfmError("mpi_ranks","E012 profile supports 2..4 local ranks",2)
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0<timeout<=3600:
        raise DfmError("invalid_timeout","MPI timeout must be finite, 0 < seconds <= 3600",2)
    mdu=Mdu(Path(mdu))
    report=validate_mdu(mdu)
    supported=profile(report,mdu,"short")
    for key,suffix in (("output/mapfile","_map.nc"),("output/hisfile","_his.nc")):
        if mdu.get(key,"") not in ("",mdu.path.stem+suffix):
            raise DfmError("mpi_output_profile","MPI v1 requires default rank output filenames",4,key)
    if not mdu.get("geometry/netfile","").endswith("_net.nc"):
        raise DfmError("mpi_partition_profile","Pinned partitioner requires a *_net.nc input grid basename",4)
    if mdu.get("general/pathsrelativetoparent", "0").strip()!="0":
        raise DfmError("mpi_path_profile","MPI v1 requires PathsRelativeToParent=0",4)
    out=Path(out).resolve()
    if out.exists() or out.is_relative_to(mdu.path.parent.resolve()):
        raise DfmError("run_folder_exists","MPI output must be new and outside the source model",4,str(out))
    inspected=inspect_install(installation)
    missing=[e["relative_path"] for e in inspected["tools"] if not e["exists"]]
    if missing or not inspected["localonly_script_claim"]:
        raise DfmError("mpi_installation_unsupported","Selected installation lacks the required local-only layout/script evidence",3,missing)
    kernels=Path(inspected["installation"]["kernels"])
    model=out/"model"/mdu.path.name
    partition=[str(kernels/"bin/dflowfm-cli.exe"),f"--partition:ndomains={ranks}:icgsolver=6",model.name]
    launch=[str(kernels/"bin/mpiexec.exe"),"-n",str(ranks),"-localonly",str(Path(sys.executable).resolve()),
            "-I","-m","dfm_cli.parallel_worker",str(out/"rank-guard.json")]
    entries=report["files"]+[e for e in inspected["tools"] if e["exists"]]
    entries += [{"path":str(p),"sha256":sha(p)} for p in [Path(sys.executable).resolve(),*sorted(Path(__file__).parent.glob('parallel*.py'))]]
    return {"contract_version":1,"stage":"preintegration","operation":"mpi_plan","ranks":ranks,"timeout_seconds":timeout,
            "source_mdu":str(mdu.path),"out":str(out),"profile":supported,"inputs":report["files"],
            "install":inspected,"input_sha256":fingerprint({"files":entries,"ranks":ranks,"timeout":timeout,"out":str(out)}),
            "fingerprints":entries,"partition_argv":partition,"mpi_argv":launch,
            "dimr_argv":[str(kernels/"bin/dimr.exe"),str(out/"dimr_config.xml")],
            "rank_list":list(range(ranks)),"numerical_tolerances":"required explicit comparison JSON; no inferred tolerance",
            "native_execution":"not_performed","ownership":"exact controller Job guard required on every rank before DIMR starts",
            "limitations":["No production MPI support claim before E012/M5 gates","No remote hosts, services, credentials, firewall changes or interactive prompts",
                           "Hydra control channels may still use local sockets; any prompt or bootstrap failure is a failure, never bypassed",
                           "Cold short 2D serial-supported inputs only; no adoption, resume, restart launch, coupling or distributed MPI"]}


def write_config(path, mdu_name, ranks):
    ns="http://schemas.deltares.nl/dimr"
    ET.register_namespace("",ns)
    root=ET.Element(f"{{{ns}}}dimrConfig")
    def child(parent,key,value=None,**attrs):
        e=ET.SubElement(parent,f"{{{ns}}}{key}",attrs);e.text=value;return e
    doc=child(root,"documentation")
    for k,v in (("fileVersion","1.2"),("createdBy","dfm E012 preintegration"),("creationDate",utc_now())):
        child(doc,k,v)
    child(child(root,"control"),"start",name="DFlowFM")
    component=child(root,"component",name="DFlowFM")
    for k,v in (("library","dflowfm"),("process"," ".join(map(str,range(ranks)))),("mpiCommunicator","DFM_COMM_DFMWORLD"),
                ("workingDir","model"),("inputFile",mdu_name)):
        child(component,k,v)
    ET.indent(root)
    ET.ElementTree(root).write(path,encoding="utf-8",xml_declaration=True)
