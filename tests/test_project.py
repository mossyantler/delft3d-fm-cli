"""Independent project bridge acceptance; no real console/GUI is launched here.

Portable model data are opaque synthetic files. External-process responses are
injected at the launch boundary; expectations use our independent file/SQLite
oracle and public JSON protocol, never product parsing/verification helpers.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli.cli import main
from research.workflows.verification.verify_project import (
    F34_FILES, boundary_semantics, compare_f34, fingerprints, input_graph, sqlite_project,
)


MDU = """[General]
fileVersion=1.09
fileType=modelDef
Program=D-Flow FM
PathsRelativeToParent=0
[geometry]
NetFile=f34_net.nc
ThinDamFile=f34_thd.pli
DryPointsFile=f34_drypoints_dry.xyz
Kmx=0
[time]
RefDate=20010101
TUnit=S
TZone=0
DtUser=1
StartDateTime=20010101000000
StopDateTime=20010101000200
[external forcing]
ExtForceFile=
ExtForceFileNew=f34_bnd.ext
[output]
OutputDir=output
ObsFile=f34_obs.xyn
CrsFile=f34_crs.pli
HisInterval=10
MapInterval=10
[restart]
RestartFile=
[waves]
WaveModelNr=0
[trachytopes]
TrtRou=N
"""
EXT = """[General]
fileVersion=2.02
fileType=extForce
[Boundary]
quantity=waterlevelbnd
locationFile=f34_001.pli
forcingFile=f34_001.bc
[Meteo]
quantity=windxy
forcingFile=f34.wnd
forcingFileType=uniMagDir
interpolationMethod=linearSpaceTime
operand=O
"""


def portable_model(root):
    root.mkdir()
    (root / "f34.mdu").write_text(MDU, encoding="utf-8")
    (root / "f34_bnd.ext").write_text(EXT, encoding="utf-8")
    (root / "f34_net.nc").write_bytes(b"opaque portable mesh; must never reach native host")
    pli = "L1\n13 2\n" + "".join(f"0 {i * 10}\n" for i in range(13))
    (root / "f34_001.pli").write_text(pli, encoding="utf-8")
    bc = "[General]\nfileVersion=1.01\nfileType=boundConds\n"
    for point, phase in ((1, 0), (7, -17.13), (13, -34.26)):
        bc += (f"[Forcing]\nname=L1_{point:04d}\nfunction=harmonic\n"
               "quantity=harmonic component\nunit=minutes\n"
               "quantity=waterlevelbnd amplitude\nunit=m\n"
               "quantity=waterlevelbnd phase\nunit=deg\n"
               f"0 0 0\n750 1.625 {phase}\n")
    (root / "f34_001.bc").write_text(bc, encoding="utf-8")
    for name, content in {"f34.wnd": "0 2 0\n120 3 0\n", "f34_thd.pli": "dam\n2 2\n20 0\n20 10\n",
                          "f34_drypoints_dry.xyz": "10 10 0\n", "f34_obs.xyn": "5 5 'probe'\n",
                          "f34_crs.pli": "section\n2 2\n5 0\n5 10\n"}.items():
        (root / name).write_text(content, encoding="utf-8")
    assert set(fingerprints(root)) == F34_FILES
    return root / "f34.mdu"


def portable_database(path):
    with contextlib.closing(sqlite3.connect(path)) as db:
        # Small structural stand-in for the observed E001 SQLite tables. This
        # is not claimed to be a real Delta Shell serialization/native fixture.
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, file_format_version TEXT)")
        db.execute("INSERT INTO projects VALUES (1, 'synthetic project', '1.1.0.0')")
        db.execute("CREATE TABLE fm_model (project_item_id INTEGER PRIMARY KEY, Path TEXT)")
        db.execute("INSERT INTO fm_model VALUES (2, '$data$WaterFlowFMModel-00000000-0000-0000-0000-000000000001')")
        db.execute("CREATE TABLE models (project_item_id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO models VALUES (2)")
        db.execute("CREATE TABLE activities (project_item_id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER)")
        db.execute("INSERT INTO activities VALUES (2, 'f34', NULL)")
        db.commit()
    return path


class ProjectOracleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mdu = portable_model(self.root / "input")

    def test_independent_graph_and_boundary_units(self):
        graph = input_graph(self.mdu)
        self.assertEqual(set(graph["files"]), F34_FILES)
        semantics = boundary_semantics(self.mdu.parent / "f34_001.bc")
        self.assertEqual(list(semantics), ["L1_0001", "L1_0007", "L1_0013"])
        self.assertIn(("unit", "minutes"), semantics["L1_0001"]["entries"])

    def test_oracle_accepts_timestamp_order_and_numeric_format_only(self):
        other = self.root / "exported"
        shutil.copytree(self.mdu.parent, other)
        content = self.mdu.read_text().replace("DtUser=1", "DtUser=1.0000d+0")
        content = content.replace("HisInterval=10\nMapInterval=10", "MapInterval=10\nHisInterval=10")
        (other / "f34.mdu").write_text("# regenerated timestamp\n" + content)
        result = compare_f34(self.mdu, other / "f34.mdu")
        self.assertEqual(len(result["non_mdu_byte_identical"]), 9)

    def test_oracle_accepts_boundary_formatting_but_preserves_ordered_columns(self):
        other = self.root / "formatted boundary"
        shutil.copytree(self.mdu.parent, other)
        path = other / "f34_001.bc"
        text = path.read_text().replace("750 1.625", "7.50e2    1.625000")
        text = text.replace("name=L1_0001\nfunction=harmonic", "function=harmonic\nname=L1_0001")
        path.write_text("# format-only normalization\n" + text)
        result = compare_f34(self.mdu, other / "f34.mdu")
        self.assertTrue(result["bc_semantics_equal"])
        self.assertEqual(len(result["non_mdu_byte_identical"]), 8)

    def test_oracle_rejects_changed_signal_unit_mesh_and_clock(self):
        mutations = {"unit": ("f34_001.bc", b"unit=m", b"unit=cm"),
                     "signal": ("f34_001.bc", b"750 1.625", b"750 99.0"),
                     "mesh": ("f34_net.nc", b"opaque", b"damaged"),
                     "clock": ("f34.mdu", b"StopDateTime=20010101000200", b"StopDateTime=20010101000300")}
        for case, (name, before, after) in mutations.items():
            with self.subTest(case=case):
                dest = self.root / case
                shutil.copytree(self.mdu.parent, dest)
                target = dest / name
                target.write_bytes(target.read_bytes().replace(before, after))
                with self.assertRaises(AssertionError):
                    compare_f34(self.mdu, dest / "f34.mdu")

    def test_oracle_rejects_missing_and_escaping_external_reference(self):
        ext = self.mdu.parent / "f34_bnd.ext"
        original = ext.read_bytes()
        for value in ("missing.bc", "../outside.bc", str((self.root / "outside.bc").resolve())):
            with self.subTest(value=value):
                (self.root / "outside.bc").write_bytes(b"external sentinel")
                ext.write_bytes(original.replace(b"f34_001.bc", value.encode()))
                with self.assertRaises(AssertionError):
                    input_graph(self.mdu)

    def test_sqlite_and_companion_are_read_only_and_both_required(self):
        project = portable_database(self.root / "case.dsproj")
        companion = self.root / "case.dsproj_data"
        shutil.copytree(self.mdu.parent, companion / "f34/input")
        before = fingerprints(self.root)
        report = sqlite_project(project)
        self.assertEqual(report["row_counts"], {"projects": 1, "fm_model": 1})
        self.assertEqual(fingerprints(self.root), before)
        companion.rename(self.root / "hidden companion")
        with self.assertRaises(AssertionError):
            sqlite_project(project)


class ProjectPublicFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mdu = portable_model(self.root / "source")
        self.suite = self.root / "suite with spaces"
        (self.suite / "bin").mkdir(parents=True)
        # A fingerprintable placeholder, never an executable native fixture.
        (self.suite / "bin/DeltaShell.Console.exe").write_bytes(b"not a real console")
        plugin = self.suite / "plugins/DeltaShell.Plugins.FMSuite.FlowFM"
        plugin.mkdir(parents=True)
        (plugin / "DeltaShell.Plugins.FMSuite.FlowFM.dll").write_bytes(b"portable plugin placeholder")

    def cli(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(value) for value in arguments])
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["protocol_version"], 2)
        self.assertNotEqual(code, 70, payload)
        return code, payload

    def refuse_before_launch(self, action, source, destination):
        before = fingerprints(self.mdu.parent)
        with patch("subprocess.Popen", side_effect=AssertionError("Rejected request launched a host")):
            code, payload = self.cli("project", action, source, "--out", destination, "--install", self.suite)
        self.assertNotEqual(code, 0, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(fingerprints(self.mdu.parent), before)
        return payload["error"]

    def project_fixture(self, label):
        folder = self.root / label
        folder.mkdir()
        project = portable_database(folder / "case.dsproj")
        shutil.copytree(self.mdu.parent, folder / "case.dsproj_data/f34/input")
        return project


class PublicProjectPreflightTests(ProjectPublicFixture):
    def test_existing_output_files_are_never_overwritten(self):
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                target = self.root / kind
                if kind == "directory":
                    target.mkdir()
                    (target / "keep.txt").write_bytes(b"user sentinel\r\n")
                    before = fingerprints(target)
                else:
                    target.write_bytes(b"user sentinel\r\n")
                    before = target.read_bytes()
                self.refuse_before_launch("import", self.mdu, target)
                self.assertEqual(fingerprints(target) if target.is_dir() else target.read_bytes(), before)

    def test_missing_mesh_external_and_companion_are_refused_without_host(self):
        for name in ("f34_net.nc", "f34_001.bc", "f34_001.pli", "f34.wnd"):
            with self.subTest(missing=name):
                original = self.mdu.parent / name
                hidden = self.root / (name + ".hidden")
                original.rename(hidden)
                self.refuse_before_launch("import", self.mdu, self.root / (name + "-out"))
                hidden.rename(original)
        project = portable_database(self.root / "no-companion.dsproj")
        self.refuse_before_launch("export", project, self.root / "no-companion-out")

    def test_outside_reference_is_not_opened_or_imported(self):
        sentinel = self.root / "outside.bc"
        sentinel.write_bytes(b"external sentinel")
        ext = self.mdu.parent / "f34_bnd.ext"
        ext.write_text(EXT.replace("f34_001.bc", "../outside.bc"), encoding="utf-8")
        self.refuse_before_launch("import", self.mdu, self.root / "escape-out")
        self.assertEqual(sentinel.read_bytes(), b"external sentinel")

    def test_output_inside_input_tree_is_refused(self):
        self.refuse_before_launch("import", self.mdu, self.mdu.parent / "new-output")

    def test_dangling_output_symlink_does_not_claim_its_target(self):
        output, target = self.root / "link", self.root / "absent-target"
        try:
            output.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is unavailable")
        self.refuse_before_launch("import", self.mdu, output)
        self.assertTrue(output.is_symlink())
        self.assertFalse(target.exists())

    def test_active_database_sidecar_is_refused_without_opening_host(self):
        project = self.project_fixture("active database")
        Path(str(project) + "-wal").write_bytes(b"uncommitted database placeholder")
        before = fingerprints(project.parent)
        error = self.refuse_before_launch("export", project, self.root / "active-db-out")
        self.assertEqual(error["code"], "project_active_database")
        self.assertEqual(fingerprints(project.parent), before)

    def test_persisted_external_path_and_extra_companion_script_are_refused(self):
        for case in ("external", "extra-script"):
            with self.subTest(case=case):
                project = self.project_fixture(case)
                if case == "external":
                    with contextlib.closing(sqlite3.connect(project)) as db:
                        db.execute("UPDATE fm_model SET Path=?", (str((self.root / "outside-model").resolve()),))
                        db.commit()
                else:
                    (project.parent / "case.dsproj_data/extra.py").write_text("raise RuntimeError('must not execute')")
                before = fingerprints(project.parent)
                error = self.refuse_before_launch("export", project, self.root / (case + "-out"))
                self.assertEqual(error["code"], "project_external_reference" if case == "external" else "project_unsupported_companion")
                self.assertEqual(fingerprints(project.parent), before)

    def test_hardlinked_input_is_refused_without_targeting_its_alias(self):
        alias = self.root / "alias.mdu"
        try:
            os.link(self.mdu, alias)
        except OSError:
            self.skipTest("Hardlinks are unavailable")
        before = alias.read_bytes()
        error = self.refuse_before_launch("import", self.mdu, self.root / "hardlink-out")
        self.assertEqual(error["code"], "project_unsupported_link")
        self.assertEqual(alias.read_bytes(), before)


def response_inventory(root):
    return [{"relative_path": name, "sha256": sha, "bytes": (root / name).stat().st_size}
            for name, sha in fingerprints(root).items()]


class FakeConsole:
    """External-protocol fixture at the documented transport injection seam.

    silent_exception models E001-E002-export-20261103/console-create-seed:
    result.json has returncode=0, success_marker=false; stdout.txt records
    System.ArgumentException / Parameter name: extension. Native artifacts are
    intentionally not needed by these portable tests.
    """
    def __init__(self, case="success", original=None):
        self.case, self.original, self.calls = case, original, []

    def __call__(self, request_path, evidence_dir, installation, timeout):
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        self.calls.append(request)
        evidence_dir = Path(evidence_dir)
        stderr = evidence_dir / "stderr.log"
        stdout = evidence_dir / "stdout.log"
        stderr.write_bytes(b"")
        stdout.write_text("DFM_PROJECT_BRIDGE_COMPLETED:" + request["run_id"] + "\n", encoding="utf-8")
        transport = {"returncode": 0, "timed_out": False, "termination": {"tree_terminated": True}}
        if self.case == "timeout":
            transport.update(returncode=1, timed_out=True)
            stdout.write_bytes(b"host started; no completion\n")
            return transport
        if self.case == "unconfirmed_cleanup":
            transport["termination"]["tree_terminated"] = False
            return transport
        if request["operation"] == "import":
            source = Path(request["source_mdu"])
            project = Path(request["project_output"])
            portable_database(project)
            saved_inputs = Path(str(project) + "_data") / "f34/input"
            shutil.copytree(source.parent, saved_inputs)
        else:
            project = Path(request["source_project"])
            sources = list(Path(str(project) + "_data").rglob("*.mdu"))
            assert len(sources) == 1
            source = sources[0]
        destination = Path(request["export_mdu"])
        graph = input_graph(source)
        for name in graph["files"]:
            target = destination if name == source.name else destination.parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source.parent / name, target)
        record = {"schema_version": 1, "run_id": request["run_id"], "operation": request["operation"],
                  "success": True, "project_closed": True, "reopened": request["operation"] == "import",
                  "process_name": "DeltaShell.Console", "process_id": 42,
                  "temp_directory": request["temp_directory"],
                  "settings_before": {"persistenceDefault": None, "useNewPersistence": None},
                  "settings_after": {"persistenceDefault": ".dsproj", "useNewPersistence": "false"},
                  "model_count": 1, "model_name": request["model_name"], "grid_vertices": 258, "grid_edges": 479,
                  "completion": "DFM_PROJECT_BRIDGE_COMPLETED",
                  "exports": [{"mdu": str(destination), "result": True,
                               "files": response_inventory(destination.parent)}]}
        if request["operation"] == "import":
            record.update(project=str(project), project_files=response_inventory(project.parent),
                          saved_project_files=response_inventory(project.parent))
        if self.case == "missing_marker":
            stdout.write_bytes(b"host exited zero without success marker\n")
        elif self.case == "embedded_marker":
            stdout.write_text("prefix DFM_PROJECT_BRIDGE_COMPLETED:" + request["run_id"] + " suffix\n")
        elif self.case == "silent_exception":
            stdout.write_bytes(b"System.ArgumentException: extension\n")
            return transport  # Observed E001 failure shape: code zero/no result.
        elif self.case == "missing_result":
            return transport
        elif self.case == "wrong_run_id":
            record["run_id"] = "different invocation"
        elif self.case == "wrong_host":
            record["process_name"] = "DeltaShell.Gui"
        elif self.case == "unclosed_project":
            record["project_closed"] = False
        elif self.case == "not_reopened":
            record["reopened"] = False
        elif self.case == "failed_result":
            record.update(success=False, traceback="Controlled import exception")
        elif self.case == "wrong_export_path":
            record["exports"][0]["mdu"] = str(self.original)
        elif self.case == "wrong_file_hash":
            record["exports"][0]["files"][0]["sha256"] = "0" * 64
        elif self.case == "missing_file":
            (destination.parent / "f34_001.bc").unlink()
        elif self.case == "changed_input":
            self.original.write_bytes(self.original.read_bytes() + b"\n# concurrent source edit\n")
        elif self.case == "missing_companion":
            Path(str(project) + "_data").rename(project.parent / "not-the-companion")
        Path(request["result_path"]).write_text(json.dumps(record), encoding="utf-8")
        return transport


class PublicProjectTransportTests(ProjectPublicFixture):
    def call_fake(self, case="success", destination="result", action="import", source=None):
        fake = FakeConsole(case, self.mdu)
        with patch("dfm_cli.project._launch_console", side_effect=fake):
            code, payload = self.cli("project", action, source or self.mdu, "--out", self.root / destination,
                                     "--install", self.suite)
        self.assertEqual(len(fake.calls), 1, payload)
        return code, payload, fake

    def test_public_import_publishes_sqlite_companion_and_complete_export(self):
        original = fingerprints(self.mdu.parent)
        code, payload, fake = self.call_fake()
        self.assertEqual(code, 0, payload)
        result = payload["result"]
        self.assertEqual(result["state"], "completed")
        saved = Path(result["project"])
        self.assertEqual(sqlite_project(saved)["row_counts"], {"projects": 1, "fm_model": 1})
        export_mdu = Path(result["exports"][0]["mdu"])
        self.assertEqual(compare_f34(self.mdu, export_mdu)["file_count"], 10)
        self.assertEqual(fingerprints(self.mdu.parent), original)
        # The host sees a private input copy, never our original source path.
        self.assertNotEqual(Path(fake.calls[0]["source_mdu"]), self.mdu)
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "completed")

    def test_zero_exit_without_both_marker_and_result_never_succeeds(self):
        for case in ("missing_marker", "embedded_marker", "missing_result", "silent_exception"):
            with self.subTest(case=case):
                original = fingerprints(self.mdu.parent)
                code, payload, _ = self.call_fake(case, case)
                self.assertNotEqual(code, 0, payload)
                self.assertFalse(payload["ok"])
                self.assertFalse((self.root / case).exists())
                self.assertEqual(fingerprints(self.mdu.parent), original)
                evidence = json.loads(Path(payload["error"]["details"]["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual(evidence["native"]["returncode"], 0)
                self.assertEqual(evidence["state"], "failed")

    def test_host_identity_completion_artifacts_and_hash_must_all_match(self):
        for case in ("wrong_run_id", "wrong_host", "unclosed_project", "not_reopened", "failed_result",
                     "wrong_export_path", "wrong_file_hash", "missing_file", "missing_companion"):
            with self.subTest(case=case):
                original = fingerprints(self.mdu.parent)
                code, payload, _ = self.call_fake(case, case)
                self.assertNotEqual(code, 0, payload)
                self.assertFalse((self.root / case).exists())
                evidence = json.loads(Path(payload["error"]["details"]["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual(evidence["state"], "failed")
                self.assertEqual(fingerprints(self.mdu.parent), original)

    def test_timeout_unconfirmed_cleanup_and_concurrent_edits_cannot_publish(self):
        for case in ("timeout", "unconfirmed_cleanup", "changed_input"):
            with self.subTest(case=case):
                code, payload, _ = self.call_fake(case, case)
                self.assertNotEqual(code, 0, payload)
                self.assertFalse((self.root / case).exists())
                evidence = json.loads(Path(payload["error"]["details"]["manifest"]).read_text(encoding="utf-8"))
                expected = "timed_out" if case == "timeout" else "cleanup_failed" if case == "unconfirmed_cleanup" else "failed"
                self.assertEqual(evidence["state"], expected)

    def test_public_export_preserves_project_database_and_companion(self):
        projectdir = self.root / "original project"
        projectdir.mkdir()
        project = portable_database(projectdir / "sample.dsproj")
        shutil.copytree(self.mdu.parent, projectdir / "sample.dsproj_data/f34/input")
        original = fingerprints(projectdir)
        code, payload, fake = self.call_fake(action="export", source=project)
        self.assertEqual(code, 0, payload)
        self.assertEqual(fingerprints(projectdir), original)
        self.assertNotEqual(Path(fake.calls[0]["source_project"]), project)
        self.assertEqual(compare_f34(self.mdu, Path(payload["result"]["exports"][0]["mdu"]))["file_count"], 10)


class ProjectOwnedTimeoutTests(ProjectPublicFixture):
    @unittest.skipUnless(os.name == "nt", "Windows job ownership; never runs Delta Shell")
    def test_real_owned_timeout_keeps_unrelated_same_executable_control_alive(self):
        from dfm_cli.windows_job import OwnedJob
        real_launch, launched = OwnedJob.launch, []
        control = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def harmless_launch(job, command, **kwargs):
            # Exercise the actual bridge timeout and private Windows Job Object;
            # replace only the executable payload, so no console/UI is started.
            process = real_launch(job, [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            launched.append(process)
            return process
        before = fingerprints(self.mdu.parent)
        try:
            with patch.object(OwnedJob, "launch", new=harmless_launch):
                code, payload = self.cli("project", "import", self.mdu, "--out", self.root / "timeout-result",
                                         "--install", self.suite, "--timeout", "0.15")
            self.assertNotEqual(code, 0, payload)
            self.assertEqual(len(launched), 1, payload)
            self.assertIsNotNone(launched[0].poll(), "Owned child still running after bridge timeout")
            self.assertIsNone(control.poll(), "Unrelated same-executable control was killed")
            self.assertFalse((self.root / "timeout-result").exists())
            self.assertEqual(fingerprints(self.mdu.parent), before)
            self.assertEqual(payload["error"]["code"], "project_timeout")
            evidence = json.loads(Path(payload["error"]["details"]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(evidence["state"], "timed_out")
            self.assertTrue(evidence["native"]["termination"]["tree_terminated"])
        finally:
            for process in [*launched, control]:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
