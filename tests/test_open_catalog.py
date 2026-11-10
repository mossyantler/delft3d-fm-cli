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

    def test_a_sediment_fraction_reports_its_transport_formula_when_the_file_sets_one(self):
        # RUN-OPEN-A1-FIX2-I (R10.2): the morphology gate covers TraFrm 2 only, so the catalog must carry it.
        replace(self.folder / "FlowFM.sed", "SedTyp                = mud", "SedTyp                = sand\n    TraFrm                = 2")
        fractions = model.validate(self.mdu)["open_catalog"]["sediment"]["fractions"]
        self.assertEqual(fractions, [{"name": "Sediment_mud", "type": "sand", "trafrm": "2"}])

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

    def test_sediment_value_that_names_a_missing_file_is_refused(self):
        # R8 changed the contract: a file name is enumerated like any reference (was: unsupported_reference),
        # so a missing one is still refused, now as missing_reference.
        replace(self.folder / "FlowFM.sed", "IniSedThick           = 1 ", "IniSedThick           = thickness.xyz ")
        report = model.validate(self.mdu)
        self.assertIn(("missing_reference", str(self.folder / "thickness.xyz")), self.codes(report))

    def test_sediment_libraries_stay_refused_and_morphology_bc_file_is_enumerated(self):
        # R8.2: library keys that load code stay refused. R8.1: BcFil is a data file and is enumerated.
        replace(self.folder / "FlowFM.mor", "MorStt                = 600", "MorStt                = 600\n    BcFil                 = morbound.bcm")
        replace(self.folder / "FlowFM.sed", "SedTyp                = mud", "SedTyp                = mud\n    SettleLib             = settle.dll")
        (self.folder / "morbound.bcm").write_text("x")
        settings = {i.get("setting", "").rsplit("/", 1)[-1].casefold() for i in model.validate(self.mdu)["issues"]}
        self.assertEqual(settings, {"settlelib"})

    def test_missing_sediment_file_is_refused(self):
        (self.folder / "FlowFM.sed").unlink()
        self.assertIn("missing_reference", [i["code"] for i in model.validate(self.mdu)["issues"]])

    def test_sediment_file_outside_the_folder_is_refused(self):
        replace(self.mdu, "SedFile = FlowFM.sed", "SedFile = ../FlowFM.sed")
        (self.folder.parent / "FlowFM.sed").write_text("[Sediment]\n")
        self.assertIn("unsupported_path", [i["code"] for i in model.validate(self.mdu)["issues"]])

    def test_other_file_naming_keys_stay_refused(self):
        for old, new, setting in (("[geometry]", "[geometry]" + chr(10) + "StructureFile = structs.ini", "geometry/structurefile"),
                                  ("RestartFile =", "RestartFile = old_rst.nc", "restart/restartfile"),
                                  ("[external forcing]", "[external forcing]" + chr(10) + "ExtForceFile = legacy.ext", "external forcing/extforcefile"),
                                  ("[geometry]", "[geometry]" + chr(10) + "UnknownFile = data.dat", "geometry/unknownfile")):
            with self.subTest(setting=setting):
                folder = copy_model(self)
                mdu = folder / "FlowFM.mdu"
                replace(mdu, old, new)
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


def write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class SedMorFileNameTests(unittest.TestCase):
    """RUN-OPEN-A1-FIX-I (Contract R8): file names inside .sed/.mor are resolved, enumerated and refused like references."""

    def setUp(self):
        self.folder = copy_model(self)
        self.mdu = self.folder / "FlowFM.mdu"
        self.sed = self.folder / "FlowFM.sed"
        self.mor = self.folder / "FlowFM.mor"

    def issues(self):
        return model.validate(self.mdu)["issues"]

    def pairs(self):
        return [(i["code"], i.get("path")) for i in self.issues()]

    def references(self, report, kind):
        return {r["key"]: r for r in report["open_catalog"][kind]["references"]}

    def set_bcfil(self, value):
        replace(self.mor, "MorStt                = 600", f"MorStt                = 600\n    BcFil                 = {value}")

    def test_bcfil_is_resolved_enumerated_and_cites_the_engine_line(self):
        self.set_bcfil("morbound.bcm")
        write(self.folder / "morbound.bcm")
        before = tree_hash(self.folder)
        report = model.validate(self.mdu)
        self.assertEqual(report["issues"], [])
        self.assertIn("morbound.bcm", {f["relative_path"] for f in report["files"]})
        ref = self.references(report, "morphology")["bcfil"]
        self.assertEqual((ref["value"], ref["path"], ref["exists"]), ("morbound.bcm", str(self.folder / "morbound.bcm"), True))
        self.assertIn("rdmor.f90:725", ref["source"])
        self.assertEqual(before, tree_hash(self.folder))

    def test_missing_bcfil_is_refused_through_the_cli(self):
        self.set_bcfil("morbound.bcm")
        self.assertIn(("missing_reference", str(self.folder / "morbound.bcm")), self.pairs())
        code, payload = cli("model", "validate", self.mdu)
        self.assertEqual(code, 4)

    def test_outside_and_absolute_bcfil_are_refused(self):
        write(self.folder.parent / "morbound.bcm")
        for value in ("../morbound.bcm", str(self.folder.parent / "morbound.bcm"), "C:/elsewhere/morbound.bcm"):
            with self.subTest(value=value):
                folder = copy_model(self)
                write(folder.parent / "morbound.bcm")
                replace(folder / "FlowFM.mor", "MorStt                = 600", f"MorStt                = 600\n    BcFil                 = {value}")
                self.assertIn("unsupported_path", [i["code"] for i in model.validate(folder / "FlowFM.mdu")["issues"]])

    def test_number_stays_a_number_and_a_logical_word_is_not_a_file(self):
        for token in ("1", "0.25", "1e-3", "2.5D0", "-1", "true", "no"):
            with self.subTest(token=token):
                folder = copy_model(self)
                replace(folder / "FlowFM.sed", "IniSedThick           = 1 ", f"IniSedThick           = {token} ")
                report = model.validate(folder / "FlowFM.mdu")
                self.assertEqual(report["issues"], [])
                self.assertEqual(report["open_catalog"]["sediment"]["references"], [])

    def test_file_form_of_every_number_or_file_key_is_enumerated_with_its_source_line(self):
        cases = [  # (file, block, line, key, engine source)
            ("sed", "[SedimentOverall]", "MudCnt = mudcnt.xyz", "mudcnt", "rdsed.f90:507"),
            ("sed", "[SedimentOverall]", "PmCrit = pmcrit.xyz", "pmcrit", "rdsed.f90:544"),
            ("sed", "[Sediment]", "SedD50 = d50.xyz", "sedd50", "rdsed.f90:680"),
            ("sed", "[Sediment]", "SedDia = dia.xyz", "seddia", "rdsed.f90:685"),
            ("sed", "[Sediment]", "SdBUni = sdbuni.xyz", "sdbuni", "rdsed.f90:869"),
            ("sed", "[Sediment]", "IniFluffMass = fluff.xyz", "inifluffmass", "rdmor.f90:2197"),
            ("mor", "[Morphology]", "MorFac = morfac.mft", "morfac", "rdmor.f90:178"),
            ("mor", "[Morphology]", "ThetSD = thetsd.xyz", "thetsd", "rdmor.f90:498"),
            ("mor", "[Morphology]", "BcFil = bc.bcm", "bcfil", "rdmor.f90:725"),
            ("mor", "[FluffLayer]", "BurFluff0 = bur0.xyz", "burfluff0", "rdmor.f90:2221"),
            ("mor", "[FluffLayer]", "BurFluff1 = bur1.xyz", "burfluff1", "rdmor.f90:2221"),
            ("mor", "[FluffLayer]", "DepFac = depfac.xyz", "depfac", "rdmor.f90:2270"),
        ]
        for kind, block, line, key, source in cases:
            with self.subTest(key=key):
                folder = copy_model(self)
                mdu, path = folder / "FlowFM.mdu", folder / ("FlowFM.sed" if kind == "sed" else "FlowFM.mor")
                if block == "[FluffLayer]":
                    path.write_text(path.read_text() + "[FluffLayer]\n")
                    if key != "depfac":
                        path.write_text(path.read_text() + "    DepFac = 0.5\n")
                    else:
                        path.write_text(path.read_text() + "    BurFluff0 = 0.1\n    BurFluff1 = 0.2\n")
                replace(path, block, block + "\n    " + line)
                name = line.split("=")[1].strip()
                self.assertIn("missing_reference", [i["code"] for i in model.validate(mdu)["issues"]], key)
                write(folder / name)
                report = model.validate(mdu)
                self.assertEqual(report["issues"], [], key)
                ref = self.references(report, "sediment" if kind == "sed" else "morphology")[key]
                self.assertEqual(ref["path"], str(folder / name))
                self.assertIn(source, ref["source"])
                self.assertIn(name, {f["relative_path"] for f in report["files"]})

    def test_names_resolve_from_the_folder_of_the_sed_or_mor_file(self):
        # Engine: prop_get_value_or_filename joins the name to the .sed/.mor path (properties.f90:3229), so a
        # file kept in a sub-folder resolves from that sub-folder; PathsRelativeToParent plays no part.
        for mode in ("0", "1"):
            with self.subTest(mode=mode):
                folder = copy_model(self)
                mdu = folder / "FlowFM.mdu"
                replace(mdu, "PathsRelativeToParent = 0", f"PathsRelativeToParent = {mode}")
                (folder / "sed").mkdir()
                shutil.move(folder / "FlowFM.sed", folder / "sed" / "FlowFM.sed")
                replace(mdu, "SedFile = FlowFM.sed", "SedFile = sed/FlowFM.sed")
                replace(folder / "sed" / "FlowFM.sed", "IniSedThick           = 1 ", "IniSedThick           = thick.xyz ")
                write(folder / "thick.xyz")  # next to the MDU only: the engine would not find it
                self.assertIn(("missing_reference", str(folder / "sed" / "thick.xyz")),
                              [(i["code"], i.get("path")) for i in model.validate(mdu)["issues"]])
                write(folder / "sed" / "thick.xyz")
                report = model.validate(mdu)
                self.assertEqual(report["issues"], [])
                self.assertIn("sed/thick.xyz", {f["relative_path"] for f in report["files"]})

    def test_ini_fluff_mass_in_the_sed_file_resolves_from_the_mor_file_folder(self):
        # rdmor.f90:2197 passes filmor as the reference even for a key of the .sed file (its own TODO says so).
        (self.folder / "sed").mkdir()
        (self.folder / "mor").mkdir()
        shutil.move(self.sed, self.folder / "sed" / "FlowFM.sed")
        shutil.move(self.mor, self.folder / "mor" / "FlowFM.mor")
        replace(self.mdu, "SedFile = FlowFM.sed", "SedFile = sed/FlowFM.sed")
        replace(self.mdu, "MorFile = FlowFM.mor", "MorFile = mor/FlowFM.mor")
        replace(self.folder / "sed" / "FlowFM.sed", "[Sediment]", "[Sediment]\n    IniFluffMass = fluff.xyz")
        write(self.folder / "sed" / "fluff.xyz")
        self.assertIn(("missing_reference", str(self.folder / "mor" / "fluff.xyz")), self.pairs())
        write(self.folder / "mor" / "fluff.xyz")
        self.assertEqual(self.issues(), [])

    def test_library_keys_stay_refused_even_when_the_file_exists(self):
        for kind, key in (("sed", "SettleLib"), ("sed", "TranspLib"), ("sed", "DLL"), ("sed", "InputFile"), ("mor", "InputFile")):
            with self.subTest(key=key, file=kind):
                folder = copy_model(self)
                block = "[Sediment]" if kind == "sed" else "[Morphology]"
                replace(folder / ("FlowFM.sed" if kind == "sed" else "FlowFM.mor"), block, f"{block}\n    {key} = lib.dll")
                write(folder / "lib.dll")
                issues = model.validate(folder / "FlowFM.mdu")["issues"]
                self.assertIn(key.casefold(), [i.get("setting", "").rsplit("/", 1)[-1] for i in issues if i["code"] == "unsupported_reference"], issues)

    def test_file_naming_keys_the_engine_does_not_open_as_data_stay_refused(self):
        write(self.folder / "bc.bcm")
        write(self.folder / "other.dat")
        replace(self.sed, "[Sediment]", "[Sediment]\n    BcFil = bc.bcm\n    OtherFile = other.dat")  # BcFil is read in .mor [Morphology] only
        settings = {i.get("setting", "").rsplit("/", 1)[-1] for i in self.issues() if i["code"] == "unsupported_reference"}
        self.assertEqual(settings, {"bcfil", "otherfile"})

    def test_an_empty_value_is_not_a_reference(self):
        self.set_bcfil("")
        report = model.validate(self.mdu)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["open_catalog"]["morphology"]["references"], [])

    def test_quoted_name_with_a_space_is_one_reference(self):
        self.set_bcfil("#bed load.bcm#   free text")
        write(self.folder / "bed load.bcm")
        report = model.validate(self.mdu)
        self.assertEqual(report["issues"], [])
        self.assertEqual(self.references(report, "morphology")["bcfil"]["value"], "bed load.bcm")


if __name__ == "__main__":
    unittest.main()
