"""Independent public-contract tests for explicit mixed component clocks.

Generated dummy reference inputs are NEVER launched. Native-looking NetCDFs are
synthetic reader tests; the pinned failed inclusive receipt remains read-only.
"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_coupling_oracles import fixture
from research.workflows.verification.verify_coupling_prepare import public


class MixedSamplingContract(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dfm-sampling-independent-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        config = fixture(self.root / "source", "08")
        fm = config.parent / "fm/flow.mdu"
        fm.write_text(fm.read_text().replace("20010101010000", "20010101020000"))
        self.mdw = config.parent / "wave/wave.mdw"
        self.mdw.write_text(self.mdw.read_text() + "[Output]\nMapWriteInterval=-1\n")
        self.data = {"schema_version": 1, "name": "independent_mixed_sampling", "profile": "fm_waves",
                     "source": {"root": str(config.parent), "files": ["fm/flow.mdu", "wave/wave.mdw", "wave/wave.grd", "wave/wave.dep"]},
                     "clock": {"reference": "2001-01-01T00:00:00Z", "start": "2001-01-01T00:00:00Z", "stop": "2001-01-01T02:00:00Z"},
                     "components": [{"name": name, "library": lib, "working_dir": work, "input_file": input_, "process": [0], "settings": [], "parameters": []}
                                    for name, lib, work, input_ in (("Flow", "dflowfm", "fm", "flow.mdu"), ("Waves", "wave", "wave", "wave.mdw"))],
                     "control": [{"kind": "parallel", "children": [{"kind": "start_group", "time": {"start": 0, "step": 3600, "stop": 7200, "unit": "s"}, "children": [{"kind": "start", "name": "Waves"}]}, {"kind": "start", "name": "Flow"}]}],
                     "couplers": [], "patches": [],
                     "observables": [{"component": name, "path": path, "format": "netcdf", "variable": var, "unit": "m", "time_variable": "time", "interval": {"value": step, "unit": "s"}, "nonzero": True}
                                     for name, path, var, step in (("Flow", "fm/flow_map.nc", "s1", 600), ("Waves", "wave/wavm-wave.nc", "hsign", 3600))]}
        self.data["observables"][1]["sample_semantics"] = "interval_start_hold"

    def preview(self, data, label):
        spec = self.root / (label + ".json")
        spec.write_text(json.dumps(data))
        target = self.root / (label + "-prepared")
        code, payload = public(["coupling", "prepare", spec, "--out", target], self.root, label)
        self.assertFalse(target.exists(), "Preview or rejected input created output")
        return code, payload, spec, target

    def test_public_positive_explicit_and_default_preserved(self):
        code, payload, spec, target = self.preview(self.data, "explicit")
        self.assertEqual(code, 0, payload)
        code, payload = public(["coupling", "prepare", spec, "--out", target, "--apply", "--expect-sha256", payload["result"]["input_sha256"]], self.root, "apply")
        self.assertEqual(code, 0, payload)
        saved = json.loads((target / "coupling-spec.json").read_text())
        self.assertEqual(saved["observables"][1]["sample_semantics"], "interval_start_hold")
        self.assertNotIn("sample_semantics", saved["observables"][0])
        for action in ("inspect", "validate"):
            code, payload = public(["coupling", action, target / "dimr_config.xml"], self.root, action)
            self.assertEqual(code, 0, payload)
        default = copy.deepcopy(self.data)
        default["observables"][1].pop("sample_semantics")
        code, payload, spec, target = self.preview(default, "default")
        self.assertEqual(code, 0, payload)  # Inclusive is valid authoring, still needs its terminal sample.
        code, payload = public(["coupling", "prepare", spec, "--out", target, "--apply", "--expect-sha256", payload["result"]["input_sha256"]], self.root, "default-apply")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("sample_semantics", json.loads((target / "coupling-spec.json").read_text())["observables"][1])

    def test_public_unsupported_schedules_components_and_modes_refuse_without_output(self):
        variants = []
        for name, value in (("unknown", "drop_last"), ("null", None), ("bool", True)):
            d = copy.deepcopy(self.data); d["observables"][1]["sample_semantics"] = value; variants.append((name, d))
        d = copy.deepcopy(self.data); d["observables"][0]["sample_semantics"] = "interval_start_hold"; variants.append(("flow-hold", d))
        for component in ("RTC", "@flow2rtc"):
            d = copy.deepcopy(self.data); d["observables"][1]["component"] = component; variants.append((component.replace("@", ""), d))
        for key, value in (("start", 3600), ("step", 1800), ("stop", 3600)):
            d = copy.deepcopy(self.data); d["control"][0]["children"][0]["time"][key] = value; variants.append(("group-" + key, d))
        d = copy.deepcopy(self.data); d["control"][0]["children"].reverse(); variants.append(("after-master", d))
        d = copy.deepcopy(self.data); d["control"][0]["children"][0]["children"].append({"kind": "start", "name": "Flow"}); variants.append(("mixed-group", d))
        d = copy.deepcopy(self.data); d["observables"][1]["interval"]["value"] = 1800; variants.append(("wrong-output-cadence", d))
        d = copy.deepcopy(self.data); d["observables"][1]["path"] = "wave/wavh-wave.nc"; variants.append(("history-is-not-map", d))
        d = copy.deepcopy(self.data); d["observables"][1].update(format="pi_xml", time_variable="event_date_time"); variants.append(("pi-is-not-map", d))
        d = copy.deepcopy(self.data); d["profile"] = "waves"; d["components"] = d["components"][1:]; d["observables"] = d["observables"][1:]; d["control"] = [{"kind": "start", "name": "Waves"}]; variants.append(("standalone-hold", d))
        for label, data in variants:
            with self.subTest(label=label):
                code, payload, _, _ = self.preview(data, label)
                self.assertEqual(code, 4, payload)
                self.assertNotEqual(payload.get("error", {}).get("code"), "internal_error")

    def test_public_native_model_mode_reference_cadence_guards(self):
        original = self.mdw.read_text()
        for label, changed in (("nonstationary", original.replace("SimMode=stationary", "SimMode=non-stationary")),
                               ("not-each-solve", original.replace("MapWriteInterval=-1", "MapWriteInterval=60")),
                               ("no-map", original.replace("MapWriteNetCDF=true", "MapWriteNetCDF=false")),
                               ("different-reference", original.replace("ReferenceDate=2001-01-01", "ReferenceDate=2001-01-02"))):
            with self.subTest(label=label):
                self.mdw.write_text(changed)
                code, payload, _, _ = self.preview(self.data, label)
                self.assertEqual(code, 4, payload)
        self.mdw.write_text(original)
        fm = self.root / "source/fm/flow.mdu"
        original = fm.read_text()
        for label, start, stop in (("start-not-reference", "20010101010000", "20010101020000"), ("nondivisible", "20010101000000", "20010101013000")):
            data = copy.deepcopy(self.data)
            data["clock"]["start"] = "2001-01-01T01:00:00Z" if "start" in label else "2001-01-01T00:00:00Z"
            data["clock"]["stop"] = "2001-01-01T01:30:00Z" if label == "nondivisible" else "2001-01-01T02:00:00Z"
            fm.write_text(original.replace("StartDateTime=20010101000000", "StartDateTime=" + start).replace("StopDateTime=20010101020000", "StopDateTime=" + stop))
            code, payload, _, _ = self.preview(data, label)
            self.assertEqual(code, 4, payload)

    @unittest.skipUnless(importlib.util.find_spec("netCDF4"), "optional NetCDF extra")
    def test_product_raw_reader_exact_times_default_rejects_hold_explicit_no_terminal_fabrication(self):
        import netCDF4 as nc
        from dfm_cli.common import DfmError
        from dfm_cli.coupling import guard
        from dfm_cli.coupling_run import observe
        code, payload, spec, target = self.preview(self.data, "raw")
        self.assertEqual(code, 0, payload)
        code, payload = public(["coupling", "prepare", spec, "--out", target, "--apply", "--expect-sha256", payload["result"]["input_sha256"]], self.root, "raw-apply")
        self.assertEqual(code, 0, payload)
        case = guard(target)
        obs = case["spec"]["observables"][1]
        clock = case["spec"]["clock"]
        def output(label, times, unit="m", time_unit="seconds since 2001-01-01", calendar="standard"):
            path = self.root / (label + ".nc")
            with nc.Dataset(path, "w") as ds:
                ds.createDimension("time", len(times))
                t = ds.createVariable("time", "f8", ("time",)); t.units = time_unit; t.calendar = calendar; t[:] = times
                v = ds.createVariable("hsign", "f8", ("time",)); v.units = unit; v[:] = 1
            return path
        correct = output("correct", [0, 3600])
        result = observe(correct, obs, clock, case)
        self.assertEqual(result["samples"], 2)
        self.assertFalse(result["terminal_sample_present"])
        self.assertEqual(result["observed_time_range"]["last"], "2001-01-01T01:00:00+00:00")
        self.assertEqual(result["requested_model_interval"]["stop"], "2001-01-01T02:00:00+00:00")
        self.assertFalse(result["declared_hold_coverage"]["cf_interval_mean"])
        self.assertEqual(result["declared_hold_coverage"]["exchange_or_hold_physics"], "not_verified")
        self.assertEqual(observe(output("minutes", [0, 60], time_unit="minutes since 2001-01-01"), obs, clock, case)["samples"], 2)
        for semantics in (None, "inclusive"):
            inclusive = copy.deepcopy(obs)
            if semantics is None: inclusive.pop("sample_semantics")
            else: inclusive["sample_semantics"] = semantics
            with self.assertRaises(DfmError) as failure:
                observe(correct, inclusive, clock)
            self.assertEqual(failure.exception.code, "coupling_output_time")
            self.assertEqual(failure.exception.details["expected_numeric_times"], [0, 3600, 7200])
            self.assertEqual(failure.exception.details["observed_numeric_times"], [0, 3600])
        with self.assertRaises(DfmError): observe(correct, obs, clock)
        for label, times in (("missing", [0]), ("no-initial", [3600]), ("extra-terminal", [0, 3600, 7200]), ("shifted", [1, 3601]), ("duplicate", [0, 0]), ("nonfinite", [0, float("nan")])):
            with self.subTest(label=label), self.assertRaises(DfmError):
                observe(output(label, times), obs, clock, case)
        for label, unit, calendar in (("wrong-units", "cm", "standard"), ("wrong-calendar", "m", "360_day")):
            with self.subTest(label=label), self.assertRaises(DfmError):
                observe(output(label, [0, 3600], unit=unit, calendar=calendar), obs, clock, case)
