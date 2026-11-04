"""Explicit derived continuity, never a replacement for raw native evidence.

No continuous-control samples are used to construct the join. All fields remain:
the earlier segment owns the single cut row; only source-confirmed segment totals
are rebased by first[-1] - resumed[0]. No raw file, manifest, tolerance, or field
set is changed. Float64 arithmetic does not recover discarded float32 mantissas.
"""
from .restart_policy import field_kind


def _summary(value, np):
    data = np.ma.asarray(value)
    good = data.compressed()
    result = {"shape": list(data.shape), "masked_values": int(np.ma.getmaskarray(data).sum())}
    if good.size and data.dtype.kind in "fiu":
        result.update(minimum=float(good.min()), maximum=float(good.max()))
    if data.size <= 16:
        result["values"] = data.tolist()
    return result


def _rounding_cells(control, head, tail, joined, np):
    """A diagnostic consistency bound, NOT a widened acceptance tolerance."""
    if any(np.ma.asarray(a).dtype != np.dtype("float32") for a in (control, head, tail)):
        return {"available": False, "reason": "This diagnostic is bounded only for stored float32 fields"}
    def radius(values):
        data = np.ma.asarray(values).astype("float32")
        up = np.nextafter(data.data, np.float32(np.inf)).astype("float64")
        down = np.nextafter(data.data, np.float32(-np.inf)).astype("float64")
        center = data.data.astype("float64")
        return np.ma.array(np.maximum(up-center,center-down)/2,mask=np.ma.getmaskarray(data))
    # Each stored float lies in its independent binary32 rounding cell. This
    # tests compatibility of the additive model with quantized observations;
    # it cannot establish unseen native double accumulator equality.
    error = abs(np.ma.asarray(control).astype("float64") - joined)
    allowance = radius(control) + radius(head[-1]) + radius(tail) + radius(tail[0])
    mask = np.ma.getmaskarray(error) | np.ma.getmaskarray(allowance)
    covered = np.ma.array(error <= allowance, mask=mask)
    return {"available": True, "consistent_with_independent_rounding_cells": bool(covered.compressed().all()),
            "compared_values": int(covered.count()), "max_residual": float(error.max()) if error.count() else None,
            "max_storage_rounding_bound": float(allowance.max()) if allowance.count() else None,
            "acceptance_tolerances_changed": False, "proves_native_accumulator_identity": False}


def field(control, head, tail, name, axis, np, compare_array, rtol, atol):
    av,bv,cv = [np.ma.asarray(v) for v in (control,head,tail)]
    kind = field_kind(name)
    rebased = cv
    operation = {"kind": "retain_first_segment_cut", "field_kind": kind,
                 "cut_source": "first_segment_last_sample", "resumed_duplicate_retained_in_raw_report": True,
                 "uses_continuous_values_for_construction": False}
    if kind in ("segment_cumulative_balance", "segment_relative_storage"):
        if axis != 0 or av.ndim != 1 or av.dtype.kind != "f":
            operation["offset_applied"] = False
            operation["reason"] = "Unverified cumulative field rank/type; kept unchanged"
        else:
            offset = bv[-1].astype("float64") - cv[0].astype("float64")
            rebased = cv.astype("float64") + offset
            operation.update(kind="rebase_recorded_segment_total", offset_applied=True,
                             formula="joined_tail(t) = resumed(t) + first(cut) - resumed(cut)",
                             offset=_summary(offset,np), first_cut=_summary(bv[-1],np), resumed_cut=_summary(cv[0],np),
                             arithmetic="float64; no casting/rounding back to force a match", exact_native_state_restoration=False)
    combined = np.ma.concatenate((bv, np.take(rebased,range(1,rebased.shape[axis]),axis=axis)),axis=axis)
    comparison = compare_array(av,combined,np,rtol,atol)
    comparison["final_full_field"] = compare_array(np.take(av,-1,axis=axis),np.take(rebased,-1,axis=axis),np,rtol,atol)
    comparison["passed"] &= comparison["final_full_field"]["passed"]
    if operation.get("offset_applied"):
        cut = bv.shape[axis]-1
        operation["quantization_diagnostic"] = _rounding_cells(np.take(av,range(cut,av.shape[axis]),axis=axis), bv, cv, rebased,np)
    comparison["operation"] = operation
    return comparison
