"""RUN-OPEN-A1-I: reference catalog for IniFieldFile and sediment/morphology files.

Portable tests: every case copies the small synthetic model in
tests/fixtures/open_model into a temporary folder. Nothing here launches an
engine, and nothing reads a user project.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from dfm_cli import model
from dfm_cli.cli import main
from dfm_cli.model import Mdu

FIXTURE = Path(__file__).parent / "fixtures" / "open_model"


def copy_model(test):
    folder = Path(tempfile.mkdtemp(prefix="open_model_"))
    test.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    shutil.copytree(FIXTURE, folder / "model")
    return folder / "model"


def tree_hash(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in argv])
    return code, json.loads(out.getvalue())


def replace(path, old, new):
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new))


class OpenCatalogTests(unittest.TestCase):
    def setUp(self):
        self.folder = copy_model(self)
        self.mdu = self.folder / "FlowFM.mdu"

    def codes(self, report):
        return sorted((i["code"], i.get("setting") or i.get("path", "")) for i in report["issues"])

    def test_base_still_refuses_the_three_uncataloged_files(self):
        # The Python inspect default keeps today's behavior for every other profile.
        report = model.inspect_mdu(Mdu(self.mdu))
        settings = {i["setting"] for i in report["issues"] if i["code"] == "unsupported_reference"}
        self.assertEqual(settings, {"geometry/inifieldfile", "sediment/morfile", "sediment/sedfile"})

    def test_validate_encloses_ini_sediment_and_morphology_files(self):
        before = tree_hash(self.folder)
        report = model.validate(self.mdu)
        self.assertEqual(report["issues"], [])
        names = {f["relative_path"] for f in report["files"]}
        for expected in ("initialFields.ini", "chezy.xyz", "sedfrac.pol", "FlowFM.sed", "FlowFM.mor"):
            self.assertIn(expected, names)
        catalog = report["open_catalog"]
        self.assertEqual([b["quantity"] for b in catalog["ini_field"]["blocks"]],
                         ["initialsedfracSediment_mud", "frictioncoefficient"])
        self.assertEqual(catalog["ini_field"]["blocks"][1]["block"], "Parameter")
        self.assertEqual(catalog["sediment"]["fractions"], [{"name": "Sediment_mud", "type": "mud"}])
        self.assertEqual(catalog["morphology"]["morfac"], "1")
        self.assertEqual(before, tree_hash(self.folder))

    def test_cli_validate_reports_the_graph_closed(self):
        code, payload = cli("model", "validate", self.mdu)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["result"]["issues"], [])
        self.assertTrue(payload["result"]["open_catalog"]["closed"])

    def test_every_catalog_reference_cites_engine_source(self):
        catalog = model.validate(self.mdu)["open_catalog"]
        sources = catalog["sources"]
        for key in ("ini_field_file", "ini_data_file", "ini_resolution", "ini_version", "sed_file", "mor_file"):
            self.assertRegex(sources[key], r"\.f90:[0-9]+", key)

    def test_missing_ini_data_file_is_refused(self):
        (self.folder / "chezy.xyz").unlink()
        report = model.validate(self.mdu)
        self.assertIn(("missing_reference", str(self.folder / "chezy.xyz")), self.codes(report))
        code, payload = cli("model", "validate", self.mdu)
        self.assertEqual(code, 4)

    def test_ini_data_file_outside_the_model_folder_is_refused(self):
        replace(self.folder / "initialFields.ini", "dataFile              = chezy.xyz", "dataFile              = ../outside.xyz")
        (self.folder.parent / "outside.xyz").write_text("x")
        report = model.validate(self.mdu)
        self.assertTrue([i for i in report["issues"] if i["code"] in {"unsupported_path"}], report["issues"])

    def test_unknown_file_naming_key_in_an_ini_block_is_refused(self):
        replace(self.folder / "initialFields.ini", "    frictionType          = Chezy", "    frictionType          = Chezy\n    extraFile             = other.xyz")
        report = model.validate(self.mdu)
        self.assertIn(("unsupported_reference", "initialFields.ini[Parameter#2]/extrafile"), self.codes(report))

    def test_incomplete_or_wrong_ini_blocks_are_refused_not_ignored(self):
        replace(self.folder / "initialFields.ini", "    dataFile              = chezy.xyz\n", "")
        report = model.validate(self.mdu)
        self.assertIn("invalid_ini_field_block", [i["code"] for i in report["issues"]])

    def test_ini_file_version_below_two_is_refused(self):
        replace(self.folder / "initialFields.ini", "fileVersion           = 3.00", "fileVersion           = 1.01")
        report = model.validate(self.mdu)
        self.assertIn("unsupported_input_format", [i["code"] for i in report["issues"]])

    def test_ini_file_must_be_an_iniField_file(self):
        replace(self.folder / "initialFields.ini", "fileType              = iniField", "fileType              = somethingElse")
        report = model.validate(self.mdu)
        self.assertIn("unsupported_input_format", [i["code"] for i in report["issues"]])

    def test_sediment_value_that_names_a_file_is_refused(self):
        replace(self.folder / "FlowFM.sed", "IniSedThick           = 1 ", "IniSedThick           = thickness.xyz ")
        report = model.validate(self.mdu)
        self.assertIn("unsupported_reference", [i["code"] for i in report["issues"]])
        self.assertTrue(any("inisedthick" in i.get("setting", "").casefold() for i in report["issues"]))

    def test_morphology_bc_file_and_sediment_libraries_are_refused(self):
        replace(self.folder / "FlowFM.mor", "MorStt                = 600", "MorStt                = 600\n    BcFil                 = morbound.bcm")
        replace(self.folder / "FlowFM.sed", "SedTyp                = mud", "SedTyp                = mud\n    SettleLib             = settle.dll")
        settings = {i.get("setting", "").rsplit("/", 1)[-1].casefold() for i in model.validate(self.mdu)["issues"]}
        self.assertTrue({"bcfil", "settlelib"} <= settings, settings)

    def test_missing_sediment_file_is_refused(self):
        (self.folder / "FlowFM.sed").unlink()
        self.assertIn("missing_reference", [i["code"] for i in model.validate(self.mdu)["issues"]])

    def test_sediment_file_outside_the_folder_is_refused(self):
        replace(self.mdu, "SedFile = FlowFM.sed", "SedFile = ../FlowFM.sed")
        (self.folder.parent / "FlowFM.sed").write_text("[Sediment]\n")
        self.assertIn("unsupported_path", [i["code"] for i in model.validate(self.mdu)["issues"]])

    def test_other_file_naming_keys_stay_refused(self):
        for line, setting in (("StructureFile = structs.ini", "geometry/structurefile"),
                              ("RestartFile = old_rst.nc", "restart/restartfile"),
                              ("ExtForceFile = legacy.ext", "external forcing/extforcefile"),
                              ("UnknownFile = data.dat", "geometry/unknownfile")):
            with self.subTest(setting=setting):
                folder = copy_model(self)
                mdu = folder / "FlowFM.mdu"
                section = "[" + setting.split("/")[0] + "]"
                mdu.write_text(mdu.read_text().replace(section, section + "\n" + line, 1))
                issues = model.validate(mdu)["issues"]
                self.assertIn(setting, [i.get("setting") for i in issues if i["code"] == "unsupported_reference"], issues)

    def test_parent_relative_ini_paths_resolve_from_the_ini_folder(self):
        replace(self.mdu, "PathsRelativeToParent = 0", "PathsRelativeToParent = 1")
        replace(self.mdu, "IniFieldFile = initialFields.ini", "IniFieldFile = fields/initialFields.ini")
        (self.folder / "fields").mkdir()
        shutil.move(self.folder / "initialFields.ini", self.folder / "fields" / "initialFields.ini")
        shutil.move(self.folder / "chezy.xyz", self.folder / "fields" / "chezy.xyz")
        shutil.move(self.folder / "sedfrac.pol", self.folder / "fields" / "sedfrac.pol")
        # Every other reference also resolves from its parent file's folder in mode 1.
        report = model.validate(self.mdu)
        self.assertEqual(report["issues"], [])
        self.assertIn("fields/chezy.xyz", {f["relative_path"] for f in report["files"]})

    def test_uppercase_and_comment_spellings_are_read_like_the_engine(self):
        replace(self.folder / "initialFields.ini", "dataFile              = chezy.xyz", "DATAFILE=chezy.xyz # comment")
        self.assertEqual(model.validate(self.mdu)["issues"], [])


if __name__ == "__main__":
    unittest.main()
