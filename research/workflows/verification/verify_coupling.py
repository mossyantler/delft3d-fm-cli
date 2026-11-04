"""Passive independent E015 verifier. This command NEVER starts a native model.

Source audit:
  python -m research.workflows.verification.verify_coupling --source SOURCE_ROOT
Retained numerical controls:
  python -m research.workflows.verification.verify_coupling --plan PLAN.json --root EVIDENCE_ROOT

Plan v1 contains scenario '03'/'07'/'08'/'10', candidate_config/control_config
(retained model inputs), and checks with kind, candidate,
control, variable, units (explicit list), start, stop, interval_seconds. 03 requires
waq_process_effect; 07 wave_height_effect; 08 wave_height_effect+fm_wave_effect+
fm_to_wave_effect;
08 additionally uses schedule_contract='pinned08_before_master_v1': Waves calls
at0/3600s, FM output0..7200s by600s. The plan explicitly declares component
windows and checks nonzero, identical imported windu/windv in all three maps.
No extra final Waves solve or shifted output timestamp is assumed.
10 wave_height_effect+rtc_effect plus rtc_exchange (flow_history, flow_variable,
station, input_file/input_variable, output_file/output_variable,
target_file/target_variable, start/stop of expected 60s logger window). All paths resolve inside --root. Native launch,
installation selection and orchestration remain with the coordinator/product.
"""
import argparse
import json
from pathlib import Path

from .verify_coupling_sources import inspect_receipt
from .verify_coupling_outputs import inspect_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", type=Path)
    mode.add_argument("--plan", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    if args.plan and not args.root:
        parser.error("Retained-output verification requires an explicit --root")
    result = inspect_receipt(args.source) if args.source else inspect_plan(json.loads(args.plan.read_text()), args.root.resolve(strict=True))
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
