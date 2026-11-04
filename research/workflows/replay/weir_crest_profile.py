"""Closed G16 modern-weir profile for Nash's shared research serial executor.

File-only prepare/validate and explicit coordinator execution use the same data
profile. There is no native launcher, custom callback or product modification.
See PROFILE below; all CLI operations delegate to research_serial_cases.run_cli.
"""
from pathlib import Path

from research.workflows.replay import research_serial_cases as executor

ROOT = Path(__file__).resolve().parents[3]
PRODUCER_SHA256 = "80554bf921c0ca19e1f4ce3b322e2e2d1ab1b32afaa770cf15fd9b5f89baa05c"
CASES = ("constant_high", "constant_low", "tim_high", "tim_low", "tim_high_to_low")
TIM_SHA256 = {
    "tim_high": "2d7eb98dba8991da9e63e4c71ab33dc94d22264e2e1f2aebae4ac40af7ebd50c",
    "tim_low": "e98258b771d039598a0be05350a4b2da7598b1b466205cf1e793c662946a1f4d",
    "tim_high_to_low": "7b93f1c6bd81bc1b555b666785a1ecd81a0b572f2b5c078dcbf9ced9d5881139",
}
MDU = {
    "general/fileversion": "1.09", "general/filetype": "modelDef", "general/program": "D-Flow FM",
    "general/pathsrelativetoparent": "0", "geometry/netfile": "mesh_net.nc",
    "geometry/structurefile": "structures.ini", "geometry/kmx": "0", "geometry/bedlevtype": "3",
    "geometry/waterlevini": "0", "time/refdate": "20010101", "time/tzone": "0", "time/tunit": "S",
    "time/tstart": "0", "time/tstop": "120", "time/startdatetime": "20010101000000",
    "time/stopdatetime": "20010101000200", "time/dtuser": "1", "time/dtmax": "1", "time/dtinit": "1",
    "numerics/cflmax": "0.7", "numerics/tlfsmo": "0", "physics/salinity": "0", "physics/temperature": "0",
    "physics/uniffricttype": "1", "physics/uniffrictcoef": "0.023", "waves/wavemodelnr": "0",
    "trachytopes/trtrou": "N", "external forcing/extforcefile": "",
    "external forcing/extforcefilenew": "boundaries.ext", "restart/restartfile": "",
    "output/outputdir": "output", "output/obsfile": "observations.xyn", "output/crsfile": "fixed_sections.pli",
    "output/hisfile": "model_his.nc", "output/mapfile": "model_map.nc", "output/hisinterval": "1",
    "output/mapinterval": "1", "output/rstinterval": "120 0 120", "output/mapformat": "4", "output/ncformat": "3",
    "output/wrihis_structure_weir": "1", "output/wrihis_crs_flow": "1", "output/wrihis_balance": "1",
    "output/wrimap_flow_flux_q1": "1", "output/wrimap_waterlevel_s1": "1",
    "output/wrimap_waterdepth": "1", "output/wrimap_volume1": "1",
}
STRUCTURE = {
    "general/fileversion": "3.01", "general/filetype": "structure", "structure/type": "weir",
    "structure/id": "blocking_weir", "structure/locationfile": "blocking_weir.pli",
    "structure/crestwidth": "40", "structure/corrcoeff": "1", "structure/usevelocityheight": "false",
    "structure/allowedflowdir": "both",
}
REFS = [
    {"from": "model.mdu", "setting": "geometry/netfile", "target": "mesh_net.nc"},
    {"from": "model.mdu", "setting": "geometry/structurefile", "target": "structures.ini"},
    {"from": "model.mdu", "setting": "external forcing/extforcefilenew", "target": "boundaries.ext"},
    {"from": "model.mdu", "setting": "output/obsfile", "target": "observations.xyn"},
    {"from": "model.mdu", "setting": "output/crsfile", "target": "fixed_sections.pli"},
    {"from": "structures.ini", "setting": "structure/locationfile", "target": "blocking_weir.pli"},
    {"from": "boundaries.ext", "setting": "boundary/locationfile", "occurrence": 0, "target": "boundary_west.pli"},
    {"from": "boundaries.ext", "setting": "boundary/forcingfile", "occurrence": 0, "target": "boundaries.bc"},
    {"from": "boundaries.ext", "setting": "boundary/locationfile", "occurrence": 1, "target": "boundary_east.pli"},
    {"from": "boundaries.ext", "setting": "boundary/forcingfile", "occurrence": 1, "target": "boundaries.bc"},
]

PROFILE = executor.CaseProfile(
    node="G16-CREST-RUNNER-I", case_ids=CASES,
    producer_schema="G16-CREST-I-preparation-1", producer_prefix="G16-CREST-I-",
    producer_sha256=PRODUCER_SHA256, science_inputs_key="csv_inputs",
    engine_sha256="78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2",
    oracle_producer_sha256_key="inputs.producer_preparation_sha256",
    oracle_frozen_state="frozen_before_new_native_outputs", oracle_case_key="cases",
    oracle_native_inputs_key=None,
    prepared_names=("prepared-final",),
    wrapper_path=Path(__file__).resolve(),
    oracle_path=ROOT / "research/workflows/verification/verify_weir_crest_series.py",
    oracle_prefix="G16-CREST-V-", oracle_version="G16-CREST-V-1",
    oracle_success_states=("passed_file_forcing_and_mapped_hydraulics",),
    receipt_schema="G13-PUMP-RUNNER-1",
    public_expected_missing=("structures.ini", "blocking_weir.pli"),
    requested_clock={"start_utc": "2001-01-01T00:00:00Z", "stop_utc": "2001-01-01T00:02:00Z",
                     "duration_seconds": 120, "history_interval_seconds": 1, "map_interval_seconds": 1,
                     "restart_seconds": [0, 120]},
    case_data={case: {
        "required": {"model.mdu": dict(MDU), "structures.ini": {
            **STRUCTURE, "structure/crestlevel": "crest.tim" if case in TIM_SHA256 else "-0.5" if case == "constant_low" else "0.5"},
            "boundaries.ext": {"general/fileversion": "2.02", "general/filetype": "extForce"}},
        "refs": [dict(ref) for ref in REFS] + ([{"from": "structures.ini", "setting": "structure/crestlevel", "target": "crest.tim"}] if case in TIM_SHA256 else []),
        "shared_targets": ["boundaries.bc"],
        "scalar_roles": {"structures.ini": ["structure/allowedflowdir"]},
        "output_roles": ["output/outputdir", "output/hisfile", "output/mapfile"],
    } for case in CASES},
    mutation_rules={
        "constant_high": [],
        "constant_low": [{"kind": "field", "file": "structures.ini", "address": "structure/crestlevel", "before": "0.5", "after": "-0.5"}],
        **{case: [{"kind": "field", "file": "structures.ini", "address": "structure/crestlevel", "before": "0.5", "after": "crest.tim"},
                  {"kind": "image", "file": "crest.tim", "before_sha256": None, "after_sha256": digest}]
           for case, digest in TIM_SHA256.items()},
    },
)


def main(argv=None):
    return executor.run_cli(PROFILE, argv)


if __name__ == "__main__":
    raise SystemExit(main())
