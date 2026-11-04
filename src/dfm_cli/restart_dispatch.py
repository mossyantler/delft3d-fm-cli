"""Select the verified parent type; never reinterpret MPI provenance as serial."""
from . import restart, parallel_continuation


def augment(report, mdu):
    if parallel_continuation.handles(mdu):
        return parallel_continuation.augment_report(report, mdu)
    if (mdu.path.parent / "restart-preparation.json").is_file():
        return restart.augment_report(report, mdu)
    return report


def backend(info):
    return parallel_continuation if info.get("kind") == parallel_continuation.KIND else restart


def state_name(info):
    if backend(info) is parallel_continuation:
        return parallel_continuation.adapter.STATE_NAME
    return "restart-state_rst.nc"
