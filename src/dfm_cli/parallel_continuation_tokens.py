"""Nonrecursive cold-source and explicit token topology guards for E012-R."""
from __future__ import annotations

from .restart_evidence import fail
from .restart_inputs import profile


def cold(mdu):
    """Run BEFORE model.validate_mdu, which dispatches hot restart receipts.

    Never follow a receipt's source_mdu recursively. Every source is an ordinary
    cold MDU with unambiguous sections/keys and an explicit time/restart layout.
    """
    # Check hot/self sources first, including an otherwise malformed MDU. No
    # graph traversal or model-validation dispatch is safe before this check.
    for key in ("restart/restartfile", "restart/restartdatetime"):
        if mdu.get(key, ""):
            fail("unsupported_restart_chain", "Continuation binding must reference a cold original MDU", key)
    sections = []
    for line in mdu.raw.decode("utf-8-sig").splitlines():
        code = line.split("#",1)[0].strip()
        if code.startswith("[") and code.endswith("]"):
            name = code[1:-1].strip().casefold()
            if name in sections:
                fail("parallel_continuation_tokens", "Repeated MDU sections are outside the token patch contract", name)
            sections.append(name)
    if sections.count("time") != 1 or sections.count("restart") != 1:
        fail("parallel_continuation_tokens", "Require one explicit time and restart section")
    previous_end = 0
    for entry in mdu.records:
        mdu.get(entry.address)  # Refuse duplicate keys everywhere, not only targets.
        if (not 0 <= previous_end <= entry.start <= entry.end <= len(mdu.raw) or
                mdu.raw[entry.start:entry.end] != entry.value.encode("utf-8")):
            fail("parallel_continuation_tokens", "MDU token offsets are inconsistent", entry.address)
        previous_end = entry.end
    for address in ("time/startdatetime", "time/stopdatetime", "time/tstart", "time/tstop"):
        if len(mdu.index.get(address,())) != 1:
            fail("parallel_continuation_tokens", "Require unique explicit absolute/relative clock tokens", address)
    profile(mdu)
