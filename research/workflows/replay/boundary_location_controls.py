"""Build two unforced-location controls without importing any CLI editor.

The replacement removes the original west hydraulic boundary. The additional
line is deliberately unbound: its creation must not change engine inputs.
Neither reference generation nor a matching text diff proves an FM result.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def inventory(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


def controls(base, out):
    base = base.resolve(strict=True)
    out = out.resolve()
    before = inventory(base)
    if (out.is_relative_to(base) or base.is_relative_to(out) or len(before) != 9
            or before.get("boundaries.bc") != "e7c6b2b80a976eea870152251c7146c0a8ac2ffbd82257c038b461441108e17a"
            or before.get("model.mdu") != "0259f844558f68bdfb89a4f6d9ff4c06c41adb1ae81f83a33a0322c7c89d2028"
            or any(not p.is_file() or p.is_symlink() for p in base.iterdir())):
        raise ValueError("Expected the dedicated original nine-file M3 channel and a separate fresh destination")
    out.mkdir(parents=True, exist_ok=False)
    incoming = out / "source"
    incoming.mkdir()
    # Distinct labels and filenames; as-is in the native plane of this fixture.
    (incoming / "boundary_west.pli").write_bytes(b"west\r\n3 2\r\n500000 5700000\r\n500000 5700020\r\n500000 5700040\r\n")
    (incoming / "survey.pli").write_bytes(b"survey\r\n2 2\r\n500010 5700010\r\n500020 5700020\r\n")
    for name in ("replace-manual", "add-manual"):
        shutil.copytree(base, out / name)
    replacement = out / "replace-manual"
    (replacement / "boundary_west.pli").write_bytes((incoming / "boundary_west.pli").read_bytes())
    for filename, marker, match, expected in [
        ("boundaries.ext", b"[Boundary]", b"locationFile = boundary_west.pli", 1),
        ("boundaries.bc", b"[Forcing]", b"Name = west_", 2),
    ]:
        path = replacement / filename
        preamble, *blocks = path.read_bytes().split(marker)
        remaining = [block for block in blocks if match not in block]
        if len(blocks) != 2*expected or len(remaining) != expected:
            raise ValueError(f"Unexpected east/west input split in {filename}")
        path.write_bytes(preamble + b"".join(marker + block for block in remaining))
    hand = inventory(replacement)
    changed = sorted(k for k in hand if hand[k] != before[k])
    if changed != ["boundaries.bc", "boundaries.ext", "boundary_west.pli"] or inventory(base) != before:
        raise ValueError("Unexpected change in manual control or original input")
    result = {"state": "controls_prepared_no_product_and_no_engine", "origin": str(base),
              "baseline": before, "replacement_changed": changed, "addition_engine_inputs_unchanged": inventory(out/"add-manual") == before,
              "replacement_expectation": "Only eastern hydraulic forcing stays active; west geometry retained unbound. Comments/sidecar can differ from manual control.",
              "addition_expectation": "survey geometry is recorded as unbound; original input graph and FM results remain unchanged.",
              "numerical_gate": "Run baseline + hand west removal + both CLI copies for 120s; verify four datasets incl final restart against their respective controls. Compare west water level against original to detect an ineffective removal."}
    (out / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(controls(args.baseline, args.out)["state"])
