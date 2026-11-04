"""Coordinator's freeze and review of the independently authored B11 predicates."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import shutil

from . import verify_boundary_line_coefficients as oracle


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def signature(*, previous_manifest_key=False):
    # The independent checker may acquire other entry points after the freeze.
    # Include all code before the public prepare/review orchestration.
    source = Path(oracle.__file__).read_bytes()
    text = source.decode("utf-8-sig")
    # Use the actual last predicate's complete source line count (not a text search).
    lines, start = inspect.getsourcelines(oracle.response)
    predicates = "".join(text.splitlines(keepends=True)[:start-1+len(lines)])
    if previous_manifest_key:
        line = '    cmd = m.get("argv")'
        oracle.need(predicates.count(line) == 1, "Unexpected manifest argv reader")
        predicates = predicates.replace(line, '    cmd = m.get("command")')
    return hashlib.sha256(predicates.encode()).hexdigest()


def freeze(args):
    inputs = oracle.check_inputs(args.inputs.resolve(strict=True))
    args.out.mkdir(parents=True, exist_ok=False)
    save(args.out/"predeclared.json", {"checker": signature(), "plan": oracle.PLAN, "inputs": inputs,
         "engine_sha256": oracle.sha(args.engine), "engine": str(args.engine.resolve()), "native_outputs_read": False})
    (args.out/"frozen-reader.py").write_bytes(Path(oracle.__file__).read_bytes())
    print(oracle.sha(args.out/"predeclared.json"))


def verify(args):
    oracle.need(oracle.sha(args.freeze) == args.expect_sha256, "Frozen gate changed")
    frozen = json.loads(args.freeze.read_bytes())
    previous = (frozen["checker"] == "7005dc5dadcef37476fc161d9e76f462657f906037552348ceb19c41c4a21c56"
                and signature(previous_manifest_key=True) == frozen["checker"])
    oracle.need((signature() == frozen["checker"] or previous) and oracle.PLAN == frozen["plan"], "Predicates or criteria changed")
    oracle.need(oracle.check_inputs(Path(frozen["inputs"]["root"])) == frozen["inputs"], "Frozen inputs changed")
    index = json.loads(args.runs.read_bytes())
    rows = index["runs"]
    oracle.need(index["version"] == 1 and len(rows) == len(oracle.CASES) and
                {r["case_id"] for r in rows} == set(oracle.CASES), "Incomplete run inventory")
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"state": "checking", "checker": signature(), "predeclared_sha256": args.expect_sha256,
              "manifest_key_correction": "command -> argv; original v3 file unchanged" if previous else None,
              "runs": {}, "equivalences": [], "responses": {}}
    try:
        for row in rows:
            case = row["case_id"]
            report["runs"][case] = oracle.load_run(Path(row["path"]), case, frozen)
            oracle.need(Path(report["runs"][case]["command"][0]).resolve(strict=True) == Path(frozen["engine"]),
                        "Executable path does not match frozen installation")
        def dataset(case, role):
            return Path(report["runs"][case]["outputs"][role]["path"])
        for left, right in oracle.PLAN["pairs_exact"]:
            diff = {role: oracle.compare_dataset(dataset(left,role), dataset(right,role), role)
                    for role in oracle.OUTPUTS}
            report["equivalences"].append({"cases":[left,right], "datasets": diff})
        for case in oracle.PLAN["response"]["cases"]:
            report["responses"][case] = {role:oracle.response(dataset("default",role),dataset(case,role), role)
                                         for role in ("history","map","restart_final")}
        report["state"] = "passed_raw_files_clocks_equivalences_and_responses"
    except Exception as exc:
        report.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        save(args.out/"verification.json", report)
    print(report["state"], len(report["runs"]))


def challenge(args):
    """Reject isolated changes that would invalidate exact physical equivalence."""
    import netCDF4 as nc
    import numpy as np
    source = oracle.ordinary(args.history)
    original = oracle.sha(source)
    args.out.mkdir(parents=True, exist_ok=False)
    checks = {}
    for kind, wanted in (("value", "Native raw storage differs: waterlevel"),
                         ("unit", "Native variable attributes/units differ: waterlevel"),
                         ("mask", "Native CF mask differs: waterlevel")):
        copy = args.out/(kind+".nc")
        shutil.copyfile(source, copy)
        with nc.Dataset(copy, "r+") as ds:
            v = ds["waterlevel"]
            value = v[1,0]
            oracle.need(not np.ma.is_masked(value) and np.isfinite(value), "Missing challenge sample")
            if kind == "value":
                v[1,0] = np.nextafter(value, np.array(np.inf,dtype=v.dtype))
            elif kind == "unit":
                v.units = "cm"
            else:
                v[1,0] = np.ma.masked
        try:
            oracle.compare_dataset(source,copy,"history")
        except ValueError as exc:
            oracle.need(str(exc) == wanted, f"Wrong rejection for {kind}: {exc}")
            checks[kind] = {"reason":str(exc), "mutated_sha256":oracle.sha(copy)}
        else:
            raise ValueError(f"Accepted deliberately altered {kind}")
    oracle.need(oracle.sha(source)==original, "Challenge touched original")
    save(args.out/"verification.json",{"state":"rejected_corrupt_copies","source":str(source),
                                      "source_sha256":original,"checks":checks})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action",required=True)
    prep = sub.add_parser("freeze"); check = sub.add_parser("verify")
    for word in ("inputs","engine","out"):
        prep.add_argument("--"+word,required=True,type=Path)
    for word in ("freeze","runs","out"):
        check.add_argument("--"+word,required=True,type=Path)
    check.add_argument("--expect-sha256",required=True)
    neg = sub.add_parser("challenge")
    for word in ("history","out"):
        neg.add_argument("--"+word,required=True,type=Path)
    args = parser.parse_args()
    {"freeze":freeze,"verify":verify,"challenge":challenge}[args.action](args)
