"""B04 coordinator gate: compare standalone collections with raw input and FM.

First differentiate all four groupings using a third (file-only) quantity. For
the numerical check use only the separately verified two-quantity 3D channel.
Reconnect the exported signals/positions by hand in *another* copy, never by
using the producer's manifest or rewriting the source model.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil

from .boundary_import_modes import check, public, save


MODES = ("all", "boundary", "process", "quantity")
PROCESSES = {"waterlevelbnd": "flow", "temperaturebnd": "transport", "salinitybnd": "transport"}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snap(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in folder.rglob("*") if p.is_file()}


def signals(raw):
    blocks = re.split(br"(?im)^(?=\[forcing\]\s*$)", raw)[1:]
    result = {}
    for block in blocks:
        point, = re.findall(br"(?im)^name\s*=\s*(\w+)\s*$", block)
        quantities = set(re.findall(br"(?im)^quantity\s*=\s*(\w+)\s*$", block)) - {b"time"}
        quantity, = quantities
        key = (point.decode(), quantity.decode())
        check(key not in result, f"Duplicate signal {key}")
        result[key] = block
    return result


def group(key, mode):
    point, quantity = key
    return {"all": "all", "boundary": point.split("_")[0], "process": PROCESSES[quantity], "quantity": quantity}[mode]


def collect(folder, tag, mode, out):
    before = snap(folder)
    dest = out / f"collection-{tag}-{mode}"
    cmd = ["boundary", "export", folder / "model.mdu", "--out", dest, "--group-by", mode]
    original = signals((folder / "boundaries.bc").read_bytes())
    mapping = {q: {"process": PROCESSES[q], "basis": "explicit coordinator grouping"} for _, q in original}
    if mode == "process":
        spec = out / (tag + "-process-map.json")
        save(spec, {"version": 1, "quantities": mapping})
        cmd += ["--process-map", spec]
    preview = public(out, f"{tag}-{mode}-preview", *cmd)
    check(not dest.exists() and before == snap(folder), "Preview changed inputs/destination")
    public(out, f"{tag}-{mode}-apply", *cmd, "--apply", "--expect-sha256", preview["input_sha256"])
    exported = {}
    groups = set()
    for file in dest.rglob("*.bc"):
        observed = signals(file.read_bytes())
        partitions = {group(key, mode) for key in observed}
        check(len(partitions) == 1 and partitions.isdisjoint(groups), "Empty, mixed, or duplicate partition")
        groups.update(partitions)
        for key, block in observed.items():
            # Exported collection may add separators, but no source byte can
            # disappear or move within a block, including vertical indices.
            check(key not in exported and key in original and block.startswith(original[key])
                  and not block[len(original[key]):].strip(), f"Changed forcing bytes: {key}")
            exported[key] = file
    check(exported.keys() == original.keys() and groups == {group(k, mode) for k in original}, "Missing groups/signals")
    positions = {p.read_bytes(): p for p in dest.rglob("*.pli")}
    check(len(positions) == 2 and set(positions) == {p.read_bytes() for p in folder.glob("boundary_*.pli")}, "PLI changed")
    check(before == snap(folder), "Export changed its source")
    return exported, positions, dict(Counter(group(k, mode) for k in original))


def reconnect(source, folder, exported, positions):
    shutil.copytree(source, folder)
    text = (folder / "boundaries.ext").read_bytes()
    chunks = re.split(br"(?im)^(?=\[boundary\]\s*$)", text)
    for i, chunk in enumerate(chunks[1:], 1):
        quantity, = re.findall(br"(?im)^quantity *= *(\w+)", chunk)
        pli, = re.findall(br"(?im)^locationFile *= *([^\s]+)", chunk)
        src_pli = folder / pli.decode()
        label = src_pli.read_bytes().splitlines()[0].decode()
        src_pli.write_bytes(positions[src_pli.read_bytes()].read_bytes())
        group_file = exported[(label + "_0001", quantity.decode())]
        check(group_file == exported[(label + "_0002", quantity.decode())], "One EXT block needs multiple signal files")
        name = "roundtrip-" + sha(group_file) + ".bc"
        (folder / name).write_bytes(group_file.read_bytes())
        check(chunk.count(b"forcingFile = boundaries.bc") == 1, "Unexpected reference")
        chunks[i] = chunk.replace(b"forcingFile = boundaries.bc", ("forcingFile = " + name).encode())
    (folder / "boundaries.ext").write_bytes(b"".join(chunks))
    # Deliberately remove the now unreferenced shared BC from the new copy:
    # the engine cannot accidentally find the original data under its old name.
    (folder / "boundaries.bc").unlink()


def run(args):
    base, out = args.baseline.resolve(strict=True), args.out.resolve()
    check(not out.is_relative_to(base) and not base.is_relative_to(out), "Overlapping paths")
    if args.install:
        lease = json.loads((Path(__file__).resolve().parents[3] / "research/experiments/roadmap-coordinator-20261104/dispatch.json").read_bytes())["native_slot"]
        check(lease["owner"] == "B04-EXPORT-G" and lease["sequence"] == args.native_slot, "Wrong native lease")
    baseline = snap(base)
    check(baseline["boundaries.bc"] == "3eec8b091fefe6b57ddd5de92c60f258b8c43b57104d6466aa505a637fadd617"
          and baseline["model.mdu"] == "c7dd028f4917d420cbc68942bbab2a7cc9b5fc12875d0a8525f96d7d2f4b8d52"
          and baseline["boundaries.ext"] == "d888b7648b28a4aad82ebe578a3ac88041eb254c43ee935b456f6a9387c4be8c", "Wrong 3D fixture")
    out.mkdir(parents=True, exist_ok=False)
    richer = out / "three-quantity-file-only"
    shutil.copytree(base, richer)
    ext, bc = richer / "boundaries.ext", richer / "boundaries.bc"
    chunks = re.split(br"(?im)^(?=\[boundary\]\s*$)", ext.read_bytes())
    ext.write_bytes(ext.read_bytes() + b"".join(x.replace(b"salinitybnd", b"temperaturebnd") for x in chunks if b"salinitybnd" in x))
    originals = signals(bc.read_bytes())
    bc.write_bytes(bc.read_bytes() + b"".join(b.replace(b"salinitybnd", b"temperaturebnd").replace(b"Unit = ppt", b"Unit = degC")
                                             for (_, q), b in originals.items() if q == "salinitybnd"))
    report = {"group_counts": {}, "numerical_comparisons": {}, "native_slot": args.native_slot, "gui_run": False}
    for mode in MODES:
        _, _, report["group_counts"][mode] = collect(richer, "mixed", mode, out)
    check([sorted(d.values()) for d in report["group_counts"].values()] == [[12], [6,6], [4,8], [4,4,4]], "Four modes not distinct")
    if args.install:
        from research.workflows.verification.verify_serial_experiment import dataset_comparison
        original_nc = None
        names = {"model_his.nc", "model_map.nc", "model_20010101_000000_rst.nc", "model_20010101_000020_rst.nc"}
        for mode in ("original", *MODES):
            inputs = base
            if mode != "original":
                exported, positions, _ = collect(base, "layers", mode, out)
                inputs = out / ("reconnected-" + mode)
                reconnect(base, inputs, exported, positions)
            native = out / ("run-" + mode)
            r = public(out, mode + "-run", "run", "start", inputs / "model.mdu", "--profile", "layers", "--route", "direct",
                       "--install", args.install, "--timeout", 60, "--out", native)
            nc = {p.name:p for p in (native / "model/output").glob("*.nc")}
            check(r["state"] == "completed" and nc.keys() == names, "3D run or final restart missing")
            if original_nc is None:
                original_nc = nc
            else:
                pairs = {name: dataset_comparison(original_nc[name], nc[name]) for name in sorted(names)}
                check(all(not p["variable_attribute_differences"] for p in pairs.values()), "Variable attributes changed")
                save(out / (mode + "-arrays.json"), pairs)
                report["numerical_comparisons"][mode] = sum(len(p["variable_results"]) for p in pairs.values())
    check(snap(base) == baseline, "Historical baseline changed")
    save(out / "verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("baseline", "out"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot", type=int)
    args = parser.parse_args()
    if bool(args.install) != bool(args.native_slot):
        parser.error("Pass both --install and --native-slot for real FM")
    print(json.dumps(run(args), indent=2))
