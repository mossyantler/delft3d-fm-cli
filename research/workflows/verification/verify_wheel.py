"""Build a snapshot, install its wheel in an empty venv, and call dfm outside the checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from email.parser import BytesParser
from zipfile import ZipFile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root, out):
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / "snapshot"
    snapshot.mkdir()
    for file in ("README.md", "pyproject.toml"):
        shutil.copy2(root / file, snapshot / file)
    source = snapshot / "src/dfm_cli"
    shutil.copytree(root / "src/dfm_cli", source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    inputs = {p.relative_to(snapshot).as_posix(): digest(p) for p in snapshot.rglob("*") if p.is_file()}
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    calls = []

    def run(label, *args):
        argv = list(map(str, args))
        p = subprocess.run(argv, cwd=out, env=env, capture_output=True, timeout=240)
        (out / (label + ".stdout")).write_bytes(p.stdout)
        (out / (label + ".stderr")).write_bytes(p.stderr)
        calls.append({"label": label, "argv": argv, "exit_code": p.returncode})
        (out / "commands.json").write_text(json.dumps(calls, indent=2), encoding="utf-8")
        if p.returncode:
            raise RuntimeError(f"{label} returned {p.returncode}; see its stdout and stderr in {out}")
        return p.stdout

    wheels = out / "wheels"
    run("build", sys.executable, "-m", "pip", "--disable-pip-version-check", "wheel", "--no-deps",
        "--wheel-dir", wheels, snapshot)
    wheel, = wheels.glob("*.whl")
    with ZipFile(wheel) as z:
        registry = z.read("dfm_cli/fields_registry.json")
        expected = {k.removeprefix("src/"): v for k, v in inputs.items() if k.startswith("src/dfm_cli/")}
        shipped = {k: hashlib.sha256(z.read(k)).hexdigest() for k in z.namelist()
                   if k.startswith("dfm_cli/") and not k.endswith("/")}
        if shipped != expected:
            raise ValueError("Packaged modules/data differ from the build snapshot")
        metadata, = [name for name in z.namelist() if name.endswith(".dist-info/METADATA")]
        message = BytesParser().parsebytes(z.read(metadata))
        extras = message.get_all("Provides-Extra", [])
        requirements = message.get_all("Requires-Dist", [])
        if "geo" not in extras or any("extra ==" not in req for req in requirements):
            raise ValueError("Optional dependencies declared incorrectly in wheel")
    if registry != (source / "fields_registry.json").read_bytes():
        raise ValueError("The packaged field registry differs from the source snapshot")
    venv = out / "venv"
    run("venv", sys.executable, "-m", "venv", venv)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    dfm = scripts / ("dfm.exe" if os.name == "nt" else "dfm")
    run("install", python, "-m", "pip", "--disable-pip-version-check", "install", "--no-index", "--no-deps", wheel)
    version = run("version", dfm, "--version").decode().strip()
    meta = json.loads(run("metadata", python, "-c",
        "import importlib.metadata as m, importlib.util as u, json;"
        "print(json.dumps([m.version('delft3d-fm-cli'), u.find_spec('netCDF4') is None, u.find_spec('pyproj') is None]))"))
    schema = json.loads(run("schema", dfm, "schema", "inspect"))["result"]
    if meta != [version, True, True] or schema["cli_version"] != version:
        raise ValueError("Wheel version, command version or optional dependency boundary disagrees")
    mdu = out / "field-probe.mdu"
    mdu.write_bytes(b"[physics]\r\nUnifFrictType = 1\r\nUnifFrictCoef = 0.023\r\n[unknown]\r\nExtra = retained\r\n")
    fields = json.loads(run("fields", dfm, "model", "fields", mdu))["result"]["fields"]
    by_key = {f["setting"]: f for f in fields}
    if not by_key["physics/uniffrictcoef"]["engine_reads"] or by_key["unknown/extra"]["registry_status"] != "unindexed_unknown":
        raise ValueError("Installed reader did not resolve known and unknown fields independently")
    # Author unbound geometry without importing a NetCDF/PROJ dependency.
    model = out / "dedicated-model"
    model.mkdir()
    model_file = model / "portable.mdu"
    model_file.write_bytes(b"[General]\r\nPathsRelativeToParent = 0\r\n")
    incoming = out / "survey.pli"
    incoming.write_bytes(b"survey\r\n2 2\r\n1.25 2.5\r\n2.25 4.5\r\n")
    dest = out / "authored-model"
    cmd = [dfm, "boundary", "location-import", model_file, "--source", incoming, "--out", dest,
           "--coordinates", "as-is"]
    preview = json.loads(run("location-preview", *cmd))["result"]
    if dest.exists():
        raise ValueError("Installed preview wrote an output folder")
    applied = json.loads(run("location-apply", *cmd, "--apply", "--expect-sha256", preview["input_sha256"]))["result"]
    geometry = dest / ".dfm-boundary-locations/objects/survey/survey.pli"
    if (geometry.read_bytes() != incoming.read_bytes() or (dest / model_file.name).read_bytes() != model_file.read_bytes()
            or applied["imported_object"]["status"] != "unbound"):
        raise ValueError("Installed base CLI did not preserve unbound geometry and model bytes")
    # These file operations must work before installing any NetCDF/PROJ extra.
    spatial = {}
    if "observation export" in schema["commands"]:
        sample = out / "standalone-points"
        sample.mkdir()
        mdu, xyn, exported = sample / "case.mdu", sample / "stations.xyn", out / "exported.xyn"
        mdu.write_bytes(b"[geometry]\nNetFile=unavailable.nc\n[output]\nObsFile=stations.xyn\n")
        raw = b"12.2500 43.25 'north gate'\r\n"
        xyn.write_bytes(raw)
        argv = [dfm, "observation", "export", mdu, "--out", exported]
        receipt = json.loads(run("observation-export-preview", *argv))["result"]
        if exported.exists():
            raise ValueError("Observation preview created its destination")
        run("observation-export-apply", *argv, "--apply", "--expect-sha256", receipt["input_sha256"])
        if exported.read_bytes() != raw or xyn.read_bytes() != raw:
            raise ValueError("Dependency-free standalone XYN export changed bytes")
        spatial["observation_export_without_mesh"] = True
    if "section reverse" in schema["commands"]:
        sample = out / "standalone-sections"
        sample.mkdir()
        mdu, pli = sample / "case.mdu", sample / "sections.pli"
        mdu.write_bytes(b"[General]\nPathsRelativeToParent=0\n[output]\nCrsFile=sections.pli\n")
        raw = b"west\r\n2 2\r\n12.25 45.0\r\n12.25 50.00\r\n"
        pli.write_bytes(raw)
        argv = [dfm, "section", "reverse", mdu, "--id", "west"]
        receipt = json.loads(run("section-preview", *argv))["result"]
        if pli.read_bytes() != raw:
            raise ValueError("Section preview changed its input")
        run("section-apply", *argv, "--apply", "--expect-sha256", receipt["input_sha256"])
        if pli.read_bytes() != b"west\r\n2 2\r\n12.25 50.00\r\n12.25 45.0\r\n":
            raise ValueError("Dependency-free section reversal changed unexpected bytes")
        spatial["section_reverse_without_observation_points"] = True
    report = {"state": "passed", "version": version, "protocol": schema["protocol_version"],
              "wheel": wheel.name, "wheel_sha256": digest(wheel), "no_netcdf": True,
              "registry_addresses": len(json.loads(registry)["records"]),
              "registry_sha256": hashlib.sha256(registry).hexdigest(), "commands": schema["commands"],
              "source_snapshot": inputs, "matched_package_files": len(shipped), "no_pyproj": True,
              "base_as_is_preview_apply": True, "base_spatial_checks": spatial, "declared_requirements": requirements}
    (out / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Fresh evidence folder outside src")
    out = parser.parse_args().out.resolve()
    root = Path(__file__).resolve().parents[3]
    if out.is_relative_to(root / "src"):
        parser.error("Choose a new output folder outside src")
    result = verify(root, out)
    print(json.dumps({k: result[k] for k in ("state", "version", "wheel_sha256", "registry_sha256")}))
