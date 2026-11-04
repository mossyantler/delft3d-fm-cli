"""Portable public B09 replay on private copies; no engine or guest commands."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): sha(p.read_bytes()) for p in folder.rglob("*") if p.is_file()}


def invoke(arguments):
    assert arguments[:2] == ["boundary", "import"]
    result = subprocess.run([sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)],
                            cwd=ROOT, capture_output=True, timeout=30)
    payload = json.loads(result.stdout)
    assert result.returncode == 0 and payload["ok"], payload
    return payload["result"]


def active_rows(raw):
    """Independent fixture oracle: Decimal times/values, never product parsers."""
    result, current = {}, None
    for line in raw.decode("utf-8-sig").splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("["):
            current = None
        elif "=" in code:
            key, value = code.split("=", 1)
            if key.strip().casefold() == "name":
                current = value.strip(); result[current] = []
        elif current:
            result[current].append(tuple(Decimal(v) for v in code.split()))
    return result


def replay():
    original = snapshot(HERE / "fixture")
    cases = []
    with tempfile.TemporaryDirectory(prefix="B09-portable-") as temporary:
        root = Path(temporary)
        for format in ("bc", "csv"):
            for mode in ("replace", "extend", "overwrite-all"):
                model = root / (format + "-" + mode)
                shutil.copytree(HERE / "fixture", model)
                before = snapshot(model)
                bc = model / "boundaries.bc"; raw = bc.read_bytes()
                arguments = ["boundary", "import", model / "model.mdu", "--boundary", "east",
                             "--source", HERE / ("signal." + format), "--format", format, "--mode", mode]
                if format == "csv":
                    arguments += ["--mapping", HERE / "mapping.json"]
                preview = invoke(arguments)
                assert snapshot(model) == before
                applied = invoke(arguments + ["--apply", "--expect-sha256", preview["input_sha256"]])
                assert applied["receipt_sha256"] == preview["receipt_sha256"]
                actual = bc.read_bytes()
                expected_actions = {"replace": ["replaced", "added", "preserved"],
                                    "extend": ["preserved", "added", "preserved"],
                                    "overwrite-all": ["replaced", "added", "cleared"]}[mode]
                assert [a["action"] for a in preview["actions"]] == expected_actions
                assert sha(actual) == preview["receipt"]["after_sha256"]
                before["boundaries.bc"] = sha(actual)
                assert snapshot(model) == before
                prefix = raw.split(b"[Forcing]\nName = east_0001", 1)[0]
                assert actual.startswith(prefix)
                data = active_rows(actual)
                assert data["east_0002"] == [(Decimal(0), Decimal(0)), (Decimal(60), Decimal(".06")), (Decimal(120), Decimal(".06"))]
                assert ("east_0003" in data) == (mode != "overwrite-all")
                if mode == "extend":
                    assert data["east_0001"] == [(Decimal(0), Decimal(0)), (Decimal(120), Decimal(0))]
                else:
                    assert data["east_0001"] == [(Decimal(0), Decimal(0)), (Decimal(60), Decimal(".12")), (Decimal(120), Decimal(".12"))]
                cases.append({"format": format, "mode": mode, "actions": expected_actions,
                              "receipt_sha256": preview["receipt_sha256"], "before_sha256": preview["receipt"]["before_sha256"],
                              "after_sha256": preview["receipt"]["after_sha256"], "west_prefix_preserved": True})
    assert snapshot(HERE / "fixture") == original
    return {"state": "passed_portable_public_import", "cases": cases, "fixture_sha256": original,
            "native_execution": "not_performed", "gui_execution": "not_performed",
            "scope": "implementation replay of six private-copy cases; independent/native gates remain separate"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Optional NEW evidence file")
    args = parser.parse_args()
    result = replay()
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
