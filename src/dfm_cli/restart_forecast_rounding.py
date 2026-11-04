"""Exact inverse IEEE rounding cells, not independent pointwise error budgets.

One shared additive origin must explain ALL saved pairs, including the cut.
Existence proves compatibility with this model only. No representative fitted
origin is selected and no native/derived value is changed to the control value.
"""
from fractions import Fraction

from .restart_evidence import fail


def _cell(value, dtype, np):
    dtype = np.dtype(dtype)
    if dtype not in (np.dtype("f4"), np.dtype("f8")):
        fail("restart_forecast_precision", "Counter must have IEEE binary32/64 storage")
    x = np.asarray(value, dtype=dtype)[()]
    before = np.nextafter(x, np.asarray(-np.inf, dtype=dtype))
    after = np.nextafter(x, np.asarray(np.inf, dtype=dtype))
    if not all(np.isfinite(v) for v in (before, x, after)):
        fail("restart_forecast_precision", "Nonfinite or extremal counter storage cell is unsupported")
    rational = lambda v: Fraction.from_float(float(v))
    even = not (np.asarray(x).view("u4" if dtype.itemsize == 4 else "u8").item() & 1)
    return ((rational(before) + rational(x)) / 2,
            (rational(x) + rational(after)) / 2, even, even)


def _difference(a, b):
    return a[0] - b[1], a[1] - b[0], a[2] and b[3], a[3] and b[2]


def _intersection(a, b):
    low, high = max(a[0], b[0]), min(a[1], b[1])
    low_closed = (a[2] if low == a[0] else True) and (b[2] if low == b[0] else True)
    high_closed = (a[3] if high == a[1] else True) and (b[3] if high == b[1] else True)
    return low, high, low_closed, high_closed


def check(continuous, resumed, np):
    """Report exact joint feasibility AND retain exact interval-reset failures."""
    a, b = np.ma.asarray(continuous), np.ma.asarray(resumed)
    if (a.shape != b.shape or a.ndim != 1 or a.size < 2 or a.size > 10001 or
            a.dtype != b.dtype or np.ma.getmaskarray(a).any() or np.ma.getmaskarray(b).any()):
        fail("restart_forecast_precision", "Require matching unmasked bounded scalar counter traces")
    feasible = None
    residuals = []
    exact = lambda v: Fraction.from_float(float(v))
    for x, y in zip(a.data, b.data):
        candidate = _difference(_cell(x, a.dtype, np), _cell(y, b.dtype, np))
        feasible = candidate if feasible is None else _intersection(feasible, candidate)
        residuals.append((exact(x) - exact(a.data[0])) - (exact(y) - exact(b.data[0])))
    low, high, lc, hc = feasible
    compatible = low < high or (low == high and lc and hc)
    return {
        "consistent_with_one_shared_origin_and_stored_precision": compatible,
        "feasible_offset_interval_exact": [str(low), str(high)],
        "interval_endpoint_inclusive": [lc, hc],
        "interval_reset_residual_exact": [str(v) for v in residuals],
        "interval_reset_residual": [float(v) for v in residuals],
        "interval_reset_exact": all(v == 0 for v in residuals),
        "interval_reset_max_abs_residual": float(max(map(abs, residuals))),
        "native_equality_proven": False, "acceptance_tolerances_changed": False,
        "method": "Joint intersection of exact midpoint storage cells with ties-to-even; no fitted origin",
    }
