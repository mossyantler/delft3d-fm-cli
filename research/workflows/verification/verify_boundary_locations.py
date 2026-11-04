"""Portable B04-PLI-V independent subprocess CLI replay with raw evidence.

python -B -m research.workflows.verification.verify_boundary_locations --out NEW
Never invokes a GUI, native engine, console bridge, VM, or install operation.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import sys
import traceback
import unittest

from .verify_boundary_locations_fixture import ARTIFACT_ROOT, ROOT, PublicAPI, fingerprints, save, sha


AS_IS_FILES = {"src/dfm_cli/boundary_locations" + suffix + ".py"
               for suffix in ("", "_contract", "_graph", "_write")}
INTEGRATED_FILES = AS_IS_FILES | {"src/dfm_cli/boundary_location_crs.py",
                                "src/dfm_cli/boundary_location_projection.py"}


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({"test": test.id(), "status": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append({"test": test.id(), "status": "failed", "traceback": "".join(traceback.format_exception(*err))})

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append({"test": test.id(), "status": "error", "traceback": "".join(traceback.format_exception(*err))})


def sources():
    paths = [*sorted((ROOT / "src/dfm_cli").glob("boundary_locations*.py")),
             *(ROOT / name for name in sorted(INTEGRATED_FILES - AS_IS_FILES) if (ROOT / name).is_file()),
             *(ROOT / "src/dfm_cli" / name for name in ("cli.py", "common.py", "model.py", "__main__.py", "__init__.py")),
             *sorted((ROOT / "tests").glob("test_boundary_locations*.py")),
             *sorted(Path(__file__).parent.glob("verify_boundary_locations*.py"))]
    return {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in paths}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Fresh B04-PLI-V evidence directory")
    parser.add_argument("--producer-freeze", type=Path, help="Faraday's explicit final as-is freeze JSON; requires its external SHA256")
    parser.add_argument("--expect-producer-freeze-sha256", help="Expected exact bytes of --producer-freeze")
    args = parser.parse_args(argv)
    if bool(args.producer_freeze) != bool(args.expect_producer_freeze_sha256):
        parser.error("--producer-freeze and --expect-producer-freeze-sha256 must be paired")
    out = args.out.absolute()
    if out.exists():
        parser.error("--out must be fresh; previous evidence is never overwritten")
    before = sources()
    producer = None
    producer_raw = None
    if args.producer_freeze:
        producer_raw = args.producer_freeze.read_bytes()
        if sha(producer_raw) != args.expect_producer_freeze_sha256.lower():
            parser.error("Producer freeze byte hash differs from externally supplied hash")
        producer = json.loads(producer_raw)
        expected = producer.get("product_files")
        if not isinstance(expected, dict) or set(expected) not in (AS_IS_FILES, INTEGRATED_FILES):
            parser.error("Producer freeze must identify exactly the four as-is modules or all six integrated import/CRS/projection modules")
        if any(before.get(name) != digest for name, digest in expected.items()):
            parser.error("Live producer source differs from explicit producer freeze; no replay performed")
    out.mkdir(parents=True, exist_ok=False)
    if producer_raw is not None:
        (out / "producer-freeze.json").write_bytes(producer_raw)
    # Retain tested source bytes before subprocess work. A later producer edit
    # cannot silently turn this receipt into evidence for different bytes.
    for name, expected in before.items():
        raw = (ROOT / name).read_bytes()
        if sha(raw) != expected:
            raise ValueError("Source changed while capturing freeze: " + name)
        target = out / "source-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    started = datetime.now(timezone.utc).isoformat()
    contract_cli = PublicAPI(out / "public-contract-raw")
    contract_before = contract_cli.invoke(["schema", "inspect"])
    if (producer is not None and contract_before.get("ok") and
            "transform" in contract_before["result"]["boundary_location_import"]["supported_coordinates"] and
            set(producer["product_files"]) != INTEGRATED_FILES):
        parser.error("Integrated public transform contract requires a freeze binding all six producer/dependency modules")
    test_path = ROOT / "tests/test_boundary_locations_public.py"
    spec = importlib.util.spec_from_file_location("b04_pli_v_public", test_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stream = io.StringIO()
    token = ARTIFACT_ROOT.set(out)
    try:
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=EvidenceResult).run(suite)
    finally:
        ARTIFACT_ROOT.reset(token)
    (out / "tests.txt").write_text(stream.getvalue(), encoding="utf-8")
    contract_after = contract_cli.invoke(["schema", "inspect"])
    contract_stable = (contract_before["ok"] and contract_after["ok"] and
                       contract_before["result"]["boundary_location_import"] == contract_after["result"]["boundary_location_import"])
    if contract_stable:
        save(out / "public-contract.json", contract_after["result"]["boundary_location_import"])
    after = sources()
    producer_stable = (producer is None or
                       args.producer_freeze.read_bytes() == producer_raw and
                       all(after.get(name) == digest for name, digest in producer["product_files"].items()))
    manual = ROOT / "research/manuals/D-Flow_FM_User_Manual.pdf"
    report = {"gate": "B04-PLI-V", "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
              "passed": result.wasSuccessful() and result.testsRun > 0 and not result.skipped and before == after and contract_stable and producer_stable, "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
              "cases": result.cases, "sources_before": before, "sources_after": after,
              "prior_inventory_regression": {"cases": [c for c in result.cases if ".test_prior_inventory_" in c["test"]],
                  "basis": "Real public-CLI prior copies; adversarial sidecar edit after valid second preview; exact exit3/no internal error, no output, complete existing bytes/directories unchanged; canonical forward-slash reimport positive"},
              "raw_BC_retirement_gate": {"required": "Exact original BC bytes minus independently authored selected block slices; no semantic/comment normalization; complete originals archived",
                  "counterexample": "research/experiments/B04-PLI-G-east-contrast-02/verification.json",
                  "target_last_control": "east at BC/EXT EOF, west active, source EOF without newline retained in before-image",
                  "native_validity_claim": False},
              "sources_stable": before == after, "python": sys.executable,
              "public_contract_stable": contract_stable,
              "explicit_producer_freeze": {"path": str(args.producer_freeze.absolute()), "sha256": sha(producer_raw),
                  "product_files": producer["product_files"], "stable_through_replay": producer_stable} if producer is not None else None,
              "public_contract_sha256": sha((out / "public-contract.json").read_bytes()) if contract_stable else None,
              "oracle_sensitivity": "test_oracle_* outputs are deliberately corrupted AFTER a successful independent check; they are not valid producer output fixtures",
              "interface": "bounded subprocess sys.executable -B -m dfm_cli; actual public parser/execute/schema; no product imports by verifier",
              "manual": {"path": str(manual), "sha256": sha(manual.read_bytes()) if manual.exists() else None,
                         "section": "7.4.8.3", "PDF_page": 130, "printed_page": 104,
                         "basis": "matching basename AND label replaces geometry and clears all forcing; new label adds without forcing; explicit as-is/transform choice"},
              "scope": "file-level only; independently authored opaque mesh sentinel is deliberately not an engine-ready model",
              "GUI_execution": "not_performed", "native_execution": "not_performed", "lease_used": None,
              "remaining": ["GUI import/dialog/project roundtrip parity", "engine initialization and scientific behavior not tested by this verifier", "horizontal transform numerical/mesh validation belongs to the separate public CRS verifier; this replay checks as-is behavior and declaration refusals", "multiline/vertical PLI unsupported and refused"]}
    save(out / "verification.json", report)
    if report["passed"]:
        save(out / "freeze.json", {"gate": "B04-PLI-V", "status": "passed_independent_public_CLI_file_level",
             "tests_run": result.testsRun, "failures": 0, "errors": 0, "skipped": 0,
             "verification_sha256": sha((out / "verification.json").read_bytes()),
             "sources": before, "source_snapshot": "source-snapshot/<repository-relative-path>",
             "public_contract_sha256": report["public_contract_sha256"],
             "explicit_producer_freeze": report["explicit_producer_freeze"],
             "independent_fixture": {"boundaries": 2, "points_per_line": 3, "quantities": 3,
                 "shared_BC_files": 1, "active_forcing_blocks_before": 21, "target_blocks_cleared": 11,
                 "active_forcing_blocks_after": 10, "EXT_edges_before": 6, "EXT_edges_after_replacement": 3,
                 "EXT_edges_after_new_addition": 6},
             "reproduce": ".venv/Scripts/python.exe -B -m research.workflows.verification.verify_boundary_locations --out research/experiments/B04-PLI-V-<FRESH>",
             "source_scope": "Observed tested source snapshot; future edits require a new verification, never upgrading this receipt",
             "oracle": "Own active-block reader and exact byte checks; no producer imports or producer change report as oracle",
             "oracle_sensitivity": report["oracle_sensitivity"],
             "product_or_shared_files_edited_by_verifier": False,
             "GUI_console_engine_VM_launches": 0, "remaining": report["remaining"]})
    save(out / "evidence-files.json", fingerprints(out))
    print(stream.getvalue(), end="")
    print(f"B04-PLI-V: {'PASS' if report['passed'] else 'FAIL'}; {out / 'verification.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
