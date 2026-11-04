"""Explicit pinned06 dt1 lifecycle study, never a chemistry acceptance route.

The native timer is ddhhmmss: 00000001 is one second, 00000100 one minute.
Only the timestep differs from a standard 3600s prepared case of the same role.
Expected intervals are input intent, not observed native timer/process counts.
No sleep, pause, injected helper or work amplification outside the solver.

Slots65/66/70 established natural completion and active owned cancel/timeout
with same-executable peer survival for this fixture. Completed controls retained
13 MAP/HIS samples and 3601 process evaluations versus 3600 advances. These
observations do not validate chemistry or make a new invocation completed.
"""
import hashlib
import re

from .common import DfmError
from .water_quality_offline_contract import PIN, SOURCE_DIGEST

CHEMISTRY_PROFILE = "pinned06-offline-ecoli"
LIFECYCLE_PROFILE = "pinned06-lifecycle-dt1-v1"
PURPOSE = "lifecycle_stress_only"
SOURCE_INP_SHA256 = "fefdfa445d0d9c13ff2face2bbcb481800c397efe64e22072f9dee9b550c801c"
LIFECYCLE_POLICY = {"purpose": PURPOSE, "chemistry_comparison": "unsupported_for_dt1",
                    "scientific_validation": "not_performed"}
LIFECYCLE_EVIDENCE = {
    "state": "verified_pinned06_dt1_lifecycle_profile",
    "profile": LIFECYCLE_PROFILE, "purpose": PURPOSE,
    "source_commit": PIN, "source_sha256": SOURCE_DIGEST,
    "native_execution": "not_established_by_preparation",
    "basis": "retained natural run, independent lifecycle replay and coordinator G; not this invocation",
    "experiments": [
        {"id": "WAQ-G-dt1-natural-01", "slot": 65, "artifact": "coordinator-raw.json",
         "sha256": "a554161aabd8e8003e139c9014de21b6c9567752c46fc2fb1c4e57f4714e7c2a"},
        {"id": "WAQ-offline-V-dt1-slot66-20261104-205104-ce305fb5", "slot": 66,
         "artifact": "verification.json",
         "sha256": "c1a259e6bae2c73e7b890e20c5d515fbf3defcc4337ac75512747b4f9be63208"},
        {"id": "WAQ-G-dt1-stops-01", "slot": 70, "artifact": "verification.json",
         "sha256": "a5a7d8b3a64dbd44803a5333a0f3f3a017ffb313e1b841cb599593f9acbee041"},
    ],
    "clock": {"start_tick": 45000, "stop_tick": 48600, "time_step_seconds": 1,
              "output_interval_seconds": 300, "timezone": "not_encoded_in_source"},
    "verified_scope": [
        "Natural completion; 13 native MAP/HIS samples ending at48600",
        "Active forced cancel and timeout in separate pairs; owned member exits and empty Jobs confirmed",
        "Same-executable peers live at target stop, then naturally completed the full output clock",
        "At least3 independent live samples spanning0.2s plus both public statuses before trigger",
    ],
    "observed_completed_control_counts": {"process_evaluations": 3601, "advances": 3600,
                                           "scope": "completed controls; not terminated target completion"},
    "limits": ["Explicit lifecycle study only; dt60 chemistry gate does not validate dt1",
               "3600 expected regular intervals; initialization/final process evaluations are separate",
               "No runtime-duration, cancellation-window or timeout guarantee",
               "Forced termination does not establish graceful finalization or usable continuation/chemical state",
               "No general model, installation or lifecycle coverage beyond the recorded fixture",
               "No chemistry comparator, full flux-ledger or scientific validation claim"],
}


def fail(message, details=None):
    raise DfmError("waq_offline_lifecycle", message, 4, details)


def receipt_profile(receipt):
    """Version and explicit markers define scope, never infer it from dt alone."""
    version = receipt.get("schema_version")
    if type(version) is int and version == 1 and receipt.get("kind") == "dfm_waq_offline_case":
        return CHEMISTRY_PROFILE
    if (type(version) is int and version == 2 and
            receipt.get("kind") == "dfm_waq_offline_lifecycle_case" and
            receipt.get("profile") == LIFECYCLE_PROFILE and receipt.get("purpose") == PURPOSE):
        return LIFECYCLE_PROFILE
    fail("Unsupported case version/profile/purpose; dt1 requires explicit lifecycle opt-in")


def audit_input(raw):
    """Require every source counter/timer token exactly once; bind actual bytes."""
    checks = {}
    def one(name, expression):
        matches = list(re.finditer(expression, raw, re.M))
        if len(matches) != 1:
            fail("Lifecycle native timer/counter token missing, altered or repeated", name)
        checks[name] = {"occurrences": 1, "native_token": matches[0][0].strip().decode("ascii")}
    one("clock_format", rb"^[ \t]*86400[ \t]+'ddhhmmss'[ \t]+'ddhhmmss'[ \t]*;[^\r\n]*$")
    one("integration_scheme", rb"^[ \t]*16\.72[ \t]+ANTICREEP[ \t]*; integration option[^\r\n]*$")
    one("start", rb"^[ \t]*1990/08/05-12:30:00[ \t]*; start time[^\r\n]*$")
    one("stop", rb"^[ \t]*1990/08/05-13:30:00[ \t]*; stop time[^\r\n]*$")
    one("constant_step", rb"^[ \t]*0[ \t]*; constant timestep[^\r\n]*$")
    one("solver_step", rb"^[ \t]*00000001[ \t]*; time step[^\r\n]*$")
    for label in ("monitoring", "map, dump", "history"):
        one(label, rb"^[ \t]*1990/08/05-12:30:00[ \t]+1990/08/05-13:30:00[ \t]+00000500[ \t]*; " + label.encode() + rb"[ \t]*\r?$")
    for name, expression in (
        ("substances", rb"^[ \t]*3[ \t]+0[ \t]*; number of active and inactive substances[^\r\n]*$"),
        ("stations", rb"^[ \t]*20[ \t]*; number of monitoring points/areas[^\r\n]*$"),
        ("segments", rb"^[ \t]*1130[ \t]*; number of segments[^\r\n]*$"),
        ("exchange_1", rb"^[ \t]*1130[ \t]*; exchanges in direction 1[^\r\n]*$"),
        ("exchange_2", rb"^[ \t]*1020[ \t]*; exchanges in direction 2[^\r\n]*$"),
        ("exchange_3", rb"^[ \t]*904[ \t]*; exchanges in direction 3[^\r\n]*$"),
    ):
        one(name, expression)
    return {"input_sha256": hashlib.sha256(raw).hexdigest(), "tokens": checks,
            "expected_regular_intervals": 3600, "dt60_regular_intervals": 60,
            "interval_count_ratio": 60, "expected_output_samples": 13,
            "counts_scope": "declared input intent; not native execution evidence",
            "pinned_source_files": 28, "consumed_references": 9,
            "hydro_records": 51, "segments": 1130, "exchanges": 3054}
