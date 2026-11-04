"""Read each generated dataset once and derive both verification and partial evidence."""
from datetime import datetime, timedelta
from glob import escape
import importlib
from pathlib import Path

from .common import DfmError, inside, sha, utc_now
from .model import Mdu, decimal


def reader():
    try:
        return importlib.import_module("netCDF4"), importlib.import_module("numpy")
    except ImportError as exc:
        raise DfmError("missing_dependency", "Run verification requires: pip install 'delft3d-fm-cli[run]'", 3) from exc


def output_paths(mdu: Mdu):
    name = mdu.path.stem
    def setting(key, default):
        return mdu.get("output/" + key, default) or default
    folder = inside(mdu.path.parent, setting("outputdir", "DFM_OUTPUT_" + name))
    return {"directory": folder, "history": inside(folder, setting("hisfile", name+"_his.nc")),
            "map": inside(folder, setting("mapfile", name+"_map.nc"))}


def schedules(mdu):
    paths = output_paths(mdu)
    intervals = {paths[kind]: float(decimal(mdu.get(key), key)) for kind, key in
                 (("history", "output/hisinterval"), ("map", "output/mapinterval"))}
    restarts = sorted(paths["directory"].glob(f"{escape(mdu.path.stem)}_*_rst.nc"))
    return paths, intervals, restarts


def read_axis(path, digest, clock, interval, snapshot):
    nc, np = reader()
    try:
        with nc.Dataset(path) as ds:
            candidates = [v for v in ds.variables.values() if v.ndim == 1 and getattr(v, "standard_name", "") == "time"]
            if len(candidates) != 1:
                raise DfmError("output_time", "Expected one rank-one CF time variable", 6, str(path))
            var = candidates[0]
            units, calendar = var.units, getattr(var, "calendar", "standard")
            values = np.ma.asarray(var[:])
            snapshot.update(time_samples=int(values.size), units=units, calendar=calendar)
            if not values.size or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all() or not np.all(values.data[1:] > values.data[:-1]):
                raise DfmError("output_time", "Time axis is empty, masked, non-finite or not increasing", 6, str(path))
            start, stop = [datetime.fromisoformat(clock[k]) for k in ("start", "stop")]
            end = nc.date2num(stop, units, calendar=calendar)
            final = abs(float(values[-1])-float(end)) < 1e-7
            first, last = [nc.num2date(t, units, calendar=calendar).isoformat() for t in (values[0], values[-1])]
            snapshot.update(readable=True, last_time=last, requested_final_time_matches=final)
            if interval is not None:
                count = round((stop-start).total_seconds()/interval) + 1
                expected = nc.date2num([start+timedelta(seconds=i*interval) for i in range(count)], units, calendar=calendar)
                if len(values) != count or not np.allclose(values.data, expected, rtol=0, atol=1e-7) or not final:
                    raise DfmError("incomplete_output", "Output time axis does not cover requested interval/cadence", 6,
                                   {"path": str(path), "first": float(values[0]), "last": float(values[-1]),
                                    "expected_first": float(expected[0]), "expected_last": float(end)})
            return {"path": str(path), "sha256": digest, "samples": int(values.size), "units": units, "calendar": calendar,
                    "first": first, "last": last, "requested_final_time_matches": final}
    except (OSError, ValueError, AttributeError, RuntimeError, TypeError, OverflowError) as exc:
        raise DfmError("unreadable_output", "Cannot read/decode NetCDF output", 6, {"path": str(path), "reason": str(exc)}) from exc


def verified(paths, restarts, axes, *, checkpoint_schedule=None):
    def axis(path):
        result = axes.get(path)
        if result is None:
            raise DfmError("missing_output", "Expected output file is missing", 6, str(path))
        if isinstance(result, DfmError):
            raise result
        return result
    regular = {kind: axis(paths[kind]) for kind in ("history", "map")}
    checkpoints = [axis(path) for path in restarts]
    schedule_check = {}
    if checkpoint_schedule is not None:
        from .checkpoint_schedule import assess
        receipt = assess(checkpoint_schedule, checkpoints)
        if receipt["state"] != "passed":
            raise DfmError("checkpoint_schedule_mismatch", "Observed CF checkpoint times differ from the configured restart schedule", 6, receipt)
        schedule_check["checkpoint_schedule"] = receipt
    elif not any(a["requested_final_time_matches"] for a in checkpoints):
        raise DfmError("missing_final_restart", "No restart dataset has the requested final time", 6)
    return {"verified_at_utc": utc_now(), "state": "passed", "axes": regular, "restart_axes": checkpoints,
            "scientific_validation": "not_performed", "scope": "CF times and cadence only", **schedule_check}


def collect_outputs(folder, manifest, *, verify, digests=None):
    model = folder / "model"
    clock = manifest["profile"]["clock"]
    inputs = {entry["relative_path"] for entry in manifest["inputs"]}
    paths, intervals, restarts = schedules(Mdu(Path(manifest["staged_mdu"]))) if verify else ({}, {}, [])
    axes = {}
    outputs, snapshots = [], []
    manifest.update(outputs=outputs, output_snapshots=snapshots)
    for path in sorted(model.rglob("*")):
        if not path.is_file() or path.relative_to(model).as_posix() in inputs:
            continue
        relative = str(path.relative_to(folder))
        digest = (digests or {}).get(path) or sha(path)
        outputs.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
        if path.suffix.casefold() != ".nc" and path not in intervals:
            continue
        snapshot = {"path": relative, "readable": False}
        snapshots.append(snapshot)
        try:
            axes[path] = read_axis(path, digest, clock, intervals.get(path), snapshot)
        except DfmError as exc:
            snapshot.update(read_error=str(exc), error_code=exc.code)
            axes[path] = exc
    if verify:
        return verified(paths, restarts, axes, checkpoint_schedule=manifest["profile"].get("checkpoint_schedule"))


def verify_outputs(mdu_path, expected_clock):
    """Verify selected datasets without constructing a run inventory (research caller)."""
    paths, intervals, restarts = schedules(Mdu(mdu_path))
    axes = {p: read_axis(p, sha(p), expected_clock, intervals.get(p), {}) for p in set(intervals) | set(restarts) if p.is_file()}
    return verified(paths, restarts, axes)
