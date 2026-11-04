"""Compare warm CLI processing on immutable f34 inputs and completed outputs; no native launch."""
import argparse
from collections import Counter
from contextlib import ExitStack
import inspect
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import patch

from dfm_cli import __version__, model, runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="completed CLI workflow containing prepared/ and direct/")
    parser.add_argument("--failure-run", type=Path, help="retained native failure for diagnostic scans")
    args = parser.parse_args()
    root = args.fixture.resolve(strict=True)
    folder = root / "direct"
    record = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    mdu = folder / "model/f34.mdu"
    nc, _ = runs.reader()
    def validate():
        model.validate(root / "prepared/f34.mdu")
    def outputs():
        if hasattr(runs, "collect_outputs"):
            runs.collect_outputs(folder, record, verify=True)
        else:  # v0.2 comparison
            runs.verify_outputs(mdu, record["profile"]["clock"])
            runs.collect_artifacts(folder, record)
    jobs = [("validation", validate), ("outputs", outputs)]
    if args.failure_run:
        failed = args.failure_run.resolve(strict=True)
        failure_record = json.loads((failed / "manifest.json").read_text(encoding="utf-8"))
        def diagnostics():
            # v0.2 read logs before testing the return code and again in its error handler.
            for _ in range(1 if hasattr(runs, "collect_outputs") else 2):
                runs.collect_diagnostics(failed, failure_record)
        jobs.append(("native_failure_diagnostics", diagnostics))
    result = {}
    for name, measure in jobs:
        measure()
        times = []
        for _ in range(15):
            start = perf_counter()
            measure()
            times.append(1000*(perf_counter()-start))
        counts = Counter()
        def track(key, fn):
            def counted(path, *args, **kwargs):
                counts[key] += 1
                if key.endswith("read") or key.endswith("digest"):
                    counts["bytes_" + key] += path.stat().st_size
                if key == "parse" and path == mdu_bytes:
                    counts["mdu_parses"] += 1
                if key == "output_digest" and path.suffix == ".nc":
                    counts["netcdf_digests"] += 1
                    counts["bytes_netcdf_digest"] += path.stat().st_size
                return fn(path, *args, **kwargs)
            return counted
        mdu_bytes = (root / "prepared/f34.mdu").read_bytes()
        with ExitStack() as stack:
            for obj, attr, key in [(model, "parse", "parse"), (Path, "read_bytes", "input_read"),
                                   (model, "sha", "input_digest"), (nc, "Dataset", "netcdf_opens")]:
                stack.enter_context(patch.object(obj, attr, track(key, getattr(obj, attr))))
            if name == "native_failure_diagnostics":
                stack.enter_context(patch.object(Path, "open", track("log_read", Path.open)))
            module = inspect.getmodule(getattr(runs, "collect_outputs", runs.verify_outputs))
            stack.enter_context(patch.object(module, "sha", track("output_digest", module.sha)))
            measure()
        result[name] = {"median_ms": round(median(times), 3), "warm_samples": len(times), "counts": dict(counts)}
    print(json.dumps({"cli": __version__, "fixture": root.name, "failure_run": args.failure_run.name if args.failure_run else None, "measurements": result}, indent=2))


if __name__ == "__main__":
    main()
