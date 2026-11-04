"""Read-only BOM intervention comparator: prior #89, measured #91, new inputs."""
from pathlib import Path
import hashlib
import json

from .verify_boundary_import_fixture import ROOT,require,save,sha,snapshot,signals
from .verify_boundary_import_native import CASES,read_raw

OLD=ROOT/"research/experiments/B09-V-public-portable-04/native-preparation"
PROOF=ROOT/"research/experiments/B09-G-BC-BOM-01"


def qualify(new_root):
    new_root=Path(new_root)
    proof=json.loads((PROOF/"verification.json").read_text())
    require(proof["state"]=="measured" and proof["native_slot"]==91
            and proof["pairs"]["bom"]["engine_rc"]==1 and proof["pairs"]["no-bom"]["engine_rc"]==0,
            "Require measured exact BOM A/B proof")
    bom,canonical=snapshot(PROOF/"bom"),snapshot(PROOF/"no-bom")
    require(set(bom)==set(canonical) and [k for k in bom if bom[k]!=canonical[k]]==["boundaries.bc"],
            "Parent A/B changed more than BC")
    require(bom["boundaries.bc"].startswith(b"\xef\xbb\xbf") and bom["boundaries.bc"][3:]==canonical["boundaries.bc"],
            "Parent A/B was not exactly leading three BOM bytes")
    raw=read_raw(PROOF/"no-bom-run")
    result={"state":"passed_BOM_only_input_intervention","native_launches_by_this_comparator":0,
            "original_preparation":str(OLD),"measured_parent_proof_sha256":sha(PROOF/"verification.json"),
            "parent_read_only_confirmation":{"clocks":raw["clocks"],"raw_hashes":raw["raw_hashes"],
                "near_east_late_mean_m":float(raw["history"][9:13,0].mean())},
            "new_V_native_trial":"NOT RUN; requires a new explicit slot; parent control is not imported-case evidence",
            "cases":{},"source_intervention":{}}
    for name in CASES:
        old=snapshot(OLD/name);new=snapshot(new_root/name)
        require(set(old)==set(new),"Model file inventory changed across intervention")
        engine=[k for k in old if k not in {"create-spec.json","create-provenance.json"}]
        require(old["boundaries.bc"].startswith(b"\xef\xbb\xbf") and old["boundaries.bc"][3:]==new["boundaries.bc"],
                "Prepared candidate differs by more than the leading BC BOM: "+name)
        require(not new["boundaries.bc"].startswith(b"\xef\xbb\xbf"),"Native candidate still has BOM")
        require(all(new[k]==old[k] for k in engine if k!="boundaries.bc"),"Geometry/clock/stations/other native inputs changed")
        old_signals,new_signals=signals(old["boundaries.bc"]),signals(new["boundaries.bc"])
        require(set(old_signals)==set(new_signals) and all(old_signals[k]["rows"]==new_signals[k]["rows"]
                and old_signals[k]["fields"]==new_signals[k]["fields"] for k in old_signals),"Signal/units changed")
        digest={k:hashlib.sha256(new[k]).hexdigest() for k in engine}
        result["cases"][name]={"engine_inputs_sha256":hashlib.sha256(json.dumps(digest,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "original_BC_sha256":hashlib.sha256(old["boundaries.bc"]).hexdigest(),"canonical_BC_sha256":hashlib.sha256(new["boundaries.bc"]).hexdigest(),
            "only_engine_input_change":"leading EF BB BF removed before import preparation; all other engine file bytes identical",
            "geometry_MDU_clock_stations_byte_identical":True,"support_signals_units_metadata_identical":True,
            "non_engine_provenance_files_changed":[k for k in old if old[k]!=new[k] and k not in engine],"engine_file_hashes":digest}
    for relative in ("base/boundaries.bc","oracle.bc","authoring/incoming.bc"):
        old=(OLD/relative).read_bytes();new=(new_root/relative).read_bytes()
        require(old.startswith(b"\xef\xbb\xbf") and old[3:]==new,"Authored base/oracle/source normalization changed more than BOM")
        result["source_intervention"][relative]={"old_sha256":sha(OLD/relative),"new_sha256":sha(new_root/relative),"only_change":"remove leading EF BB BF BEFORE import"}
    for relative in ("authoring/incoming.csv","authoring/mapping.json","authoring/independent48_net.nc"):
        require((OLD/relative).read_bytes()==(new_root/relative).read_bytes(),"Source signals/mapping/geometry changed")
        result["source_intervention"][relative]={"sha256":sha(new_root/relative),"bytes_identical":True}
    save(new_root/"intervention-vs-original-89.json",result)
    return result
