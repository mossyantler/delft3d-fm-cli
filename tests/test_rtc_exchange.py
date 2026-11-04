"""Independent portable E015 RTC/RR oracle tests; never initialize native code."""
from __future__ import annotations

import copy
import json
import struct
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_rtc_exchange import (
    config_contract, contained, fnm_inputs, lifecycle, lookup, lookup_contract,
    positive_control, read_nc_scalar, read_pi_scalar, rr_oracle, rtc_oracle, synthetic_pairs,
    pe_exports,
    fm_input_clock,
)

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc=np=None


DIMR = b'''<dimrConfig xmlns="http://schemas.deltares.nl/dimr"><control><parallel>
<startGroup><time>0 60 240</time><coupler name="in"/><start name="RTC"/><coupler name="out"/></startGroup><start name="FM"/>
</parallel></control><component name="FM"><library>dflowfm</library><workingDir>fm</workingDir><inputFile>model.mdu</inputFile></component>
<component name="RTC"><library>FBCTools_BMI</library><workingDir>rtc</workingDir><inputFile>.</inputFile></component>
<coupler name="in"><sourceComponent>FM</sourceComponent><targetComponent>RTC</targetComponent><item><sourceName>observations/W1/water_level</sourceName><targetName>input</targetName></item></coupler>
<coupler name="out"><sourceComponent>RTC</sourceComponent><targetComponent>FM</targetComponent><item><sourceName>output</sourceName><targetName>weirs/W1/crestlevel</targetName></item></coupler></dimrConfig>'''


class RtcExchangeOracleTests(unittest.TestCase):
    def setUp(self):
        self.pair=synthetic_pairs()["rtc"]
        self.case=self.pair["positive"]

    def test_independently_constructed_positive_control_has_both_directions_and_effect(self):
        result=positive_control(**self.pair,kind="rtc")
        self.assertEqual(result["state"],"passed")
        self.assertEqual(result["positive"]["expected_crest_m"],[0.,0.,2.5,5.])
        self.assertEqual(result["control"]["expected_crest_m"],[0.]*4)
        self.assertEqual(result["positive"]["phases"]["RTC_output_after_update"], [60,120,180,240])
        self.assertIn("not_established",result["native_acceptance"])

    def test_block_extrapolation_linear_interpolation_and_exact_knots(self):
        knots=self.case["knots"]
        self.assertEqual([lookup(knots,x) for x in [-1,0,1,2,6,10,20,21]], [0,0,0,0,2.5,5,5,5])
        with self.assertRaises(AssertionError):
            lookup([(0,0),(0,5)],1)

    def test_received_input_must_agree_with_fm_observation_not_just_log_label(self):
        self.case["rtc_received"]["values"][2]=7
        with self.assertRaisesRegex(AssertionError,"received input"):
            rtc_oracle(self.case)

    def test_controller_and_actual_fm_applied_crest_are_checked_independently(self):
        for key in ("rtc_output","fm_applied_crest"):
            case=copy.deepcopy(self.case)
            case[key]["values"][2]=3
            with self.subTest(key=key),self.assertRaises(AssertionError):
                rtc_oracle(case)

    def test_no_best_fit_lag_or_time_relabelling(self):
        self.case["rtc_output"]["seconds"]=[0,60,120,180]
        with self.assertRaisesRegex(AssertionError,"schedule/phase"):
            rtc_oracle(self.case)

    def test_native_rtc_step_must_match_group_invocation_step(self):
        self.case["rtc_step_seconds"]=30
        with self.assertRaisesRegex(AssertionError,"native update step"):
            rtc_oracle(self.case)

    def test_wrong_units_ids_and_missing_nan_values_are_refused(self):
        mutations=(lambda c:c["rtc_received"].update(unit="cm"),
                   lambda c:c["endpoints"].update(fm_applied_crest="weirs/OTHER/crestlevel"),
                   lambda c:c["rtc_output"]["values"].__setitem__(2,float("nan")),
                   lambda c:c["rtc_output"]["values"].pop())
        for mutate in mutations:
            case=copy.deepcopy(self.case)
            mutate(case)
            with self.subTest(mutation=mutate),self.assertRaises(AssertionError):
                rtc_oracle(case)

    def test_equal_positive_control_is_not_discriminating(self):
        with self.assertRaises(AssertionError):
            positive_control(self.case,copy.deepcopy(self.case),"rtc")


class RrExchangeOracleTests(unittest.TestCase):
    def setUp(self):
        self.pair=synthetic_pairs()["rr"]
        self.case=self.pair["positive"]

    def test_both_sender_receiver_and_signed_integrated_volume_match(self):
        report=positive_control(**self.pair,kind="rr")
        self.assertEqual(report["positive"]["expected_signed_volume_m3"],240.)
        self.assertEqual(report["control"]["expected_signed_volume_m3"],0.)

    def test_reversed_sign_is_detected_before_volume_check(self):
        self.case["fm_lateral"]["C1"]["values"]=[0.,-1.,-2.,-1.]
        with self.assertRaisesRegex(AssertionError,"value/sign"):
            rr_oracle(self.case)

    def test_unit_conversion_is_never_guessed(self):
        self.case["rr_outflow"]["C1"]["unit"]="L/s"
        with self.assertRaisesRegex(AssertionError,"physical units"):
            rr_oracle(self.case)

    def test_id_mapping_cannot_silently_select_first_lateral(self):
        self.case["fm_lateral"]["C2"]=self.case["fm_lateral"].pop("C1")
        with self.assertRaisesRegex(AssertionError,"IDs differ"):
            rr_oracle(self.case)

    def test_actual_volume_and_rr_internal_clock_are_separate_requirements(self):
        self.case["fm_integrated_lateral"]["value"]=4.
        with self.assertRaisesRegex(AssertionError,"Signed RR volume"):
            rr_oracle(self.case)
        self.case["rr_step_seconds"]=120
        with self.assertRaisesRegex(AssertionError,"internal step"):
            rr_oracle(self.case)


class SourceAndLifecycleTests(unittest.TestCase):
    def test_fm_clock_keeps_absolute_override_relative_units_timezone_and_output_step_distinct(self):
        raw=b"[time]\nRefDate=20010101\nTZone=9\nTUnit=M\nTStart=999\nTStop=1000\nStartDateTime=20010101090000\nStopDateTime=20010101090400\nDtUser=60\n[output]\nHisInterval=60\nMapInterval=60\n"
        c=fm_input_clock(raw)
        self.assertEqual(c["start_UTC"],"2001-01-01T00:00:00")
        self.assertEqual(c["duration_seconds"],240.)
        self.assertEqual(c["step_output_intervals_SI"]["time/dtuser_seconds"],60.)
        with self.assertRaisesRegex(AssertionError,"ambiguous"):
            fm_input_clock(raw.replace(b"TZone=9",b"TZone=9\nTZone=0"))

    def test_static_pe_reader_uses_export_names_not_function_code_addresses(self):
        data=bytearray(1024)
        data[:2]=b"MZ"
        struct.pack_into("<I",data,0x3c,0x80)
        data[0x80:0x84]=b"PE\0\0"
        struct.pack_into("<HH",data,0x84,0x8664,1)
        struct.pack_into("<H",data,0x94,240)
        optional=0x98
        struct.pack_into("<H",data,optional,0x20b)
        struct.pack_into("<II",data,optional+112,0x1000,200)
        section=optional+240
        struct.pack_into("<IIII",data,section+8,512,0x1000,512,512)
        struct.pack_into("<I",data,512+24,1)
        struct.pack_into("<I",data,512+28,0x1060) # Function address table is not a string table.
        struct.pack_into("<I",data,512+32,0x1080)
        struct.pack_into("<I",data,512+0x80,0x10a0)
        data[512+0xa0:512+0xa0+11]=b"initialize\0"
        with tempfile.TemporaryDirectory(prefix="dfm-rtc-pe-") as temp:
            path=Path(temp)/"fake.dll"
            path.write_bytes(data)
            result=pe_exports(path)
            self.assertEqual(result["exports"],["initialize"])
            self.assertEqual(result["machine"],"0x8664")
            self.assertIn("update",result["required_BMI_exports_missing"])

    def test_control_order_is_read_from_control_not_component_declaration(self):
        result=config_contract(DIMR)
        self.assertEqual(result["master"],"FM")
        self.assertEqual(result["groups"][0]["sequence"],[("coupler","in"),("start","RTC"),("coupler","out")])
        self.assertEqual(result["couplers"]["in"]["source"],"FM")

    def test_unresolved_component_or_invalid_clock_is_not_accepted(self):
        for raw in (DIMR.replace(b'<start name="RTC"/>',b'<start name="MISSING"/>'), DIMR.replace(b"0 60 240",b"0 nan 240")):
            with self.assertRaises(AssertionError):
                config_contract(raw)

    def test_exact_controller_table_parser_does_not_execute_or_guess_rule(self):
        raw=b'''<rtcToolsConfig><lookupTable><table><record x="0" y="0"/><record x="2" y="1"/></table>
<interpolationOption>LINEAR</interpolationOption><extrapolationOption>BLOCK</extrapolationOption>
<input><x ref="IMPLICIT">input</x></input><output><y>output</y></output></lookupTable></rtcToolsConfig>'''
        self.assertEqual(lookup_contract(raw)["knots"],[(0.,0.),(2.,1.)])
        with self.assertRaises(AssertionError):
            lookup_contract(raw.replace(b"LINEAR",b"CUBIC"))

    def test_rr_input_slots_distinguish_empty_missing_and_output_names(self):
        with tempfile.TemporaryDirectory(prefix="dfm-rr-fnm-") as temp:
            p=Path(temp)
            (p/"valid.ini").write_text("nonempty")
            (p/"nodes.tp").write_bytes(b"")
            raw=b"'valid.ini' * 1. control I\n'nodes.tp' * 2. nodes I\n'missing.tp' * 3. links I\n'future.out' * 4. output O\n"
            result=fnm_inputs(raw,p)
            self.assertEqual([v["state"] for v in result],["present_nonempty","empty","missing_or_unconfined"])

    def test_paths_cannot_escape_or_use_windows_drive_relative_names(self):
        with tempfile.TemporaryDirectory(prefix="dfm-rtc-path-") as temp:
            p=Path(temp)
            for value in ("C:ambient.xml","C:/outside.xml","../escape.xml"):
                with self.subTest(value=value),self.assertRaises((AssertionError,FileNotFoundError)):
                    contained(p,p,value,exists=False)

    def test_terminal_clock_finalization_and_all_member_handles_required(self):
        record={"state":"completed","returncode":0,"components":{name:{"final_model_seconds":240,"finalized":True} for name in ("FM","RTC")},
                "ownership":{"assigned_before_resume":True,"job_empty":True,"member_exit_confirmations":{"root":True,"child":True}}}
        self.assertEqual(lifecycle(record,240,["FM","RTC"])["state"],"passed")
        for mutate in (lambda r:r["components"]["RTC"].update(finalized=False),
                       lambda r:r["components"]["RTC"].update(final_model_seconds=180),
                       lambda r:r["ownership"]["member_exit_confirmations"].update(child=None),
                       lambda r:r.update(state="cancelled")):
            bad=copy.deepcopy(record); mutate(bad)
            with self.assertRaises(AssertionError):
                lifecycle(bad,240,["FM","RTC"])


@unittest.skipIf(nc is None,"optional netCDF4 required")
class RawScalarReaderTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="dfm-rtc-raw-")
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.path=self.root/"history.nc"
        with nc.Dataset(self.path,"w") as ds:
            ds.createDimension("time",3); ds.createDimension("station",2)
            time=ds.createVariable("time","f8",("time",))
            time.units="minutes since 2001-01-01 00:00:00 +00:00"
            time[:]=[0,1,2]
            ids=ds.createVariable("station_id",str,("station",));ids[:]=np.array(["W2","W1"],dtype=object)
            level=ds.createVariable("waterlevel","f8",("time","station"),fill_value=-999.)
            level.units="m"; level[:]=[[20,1],[30,2],[40,3]]

    def test_actual_cf_dates_and_exact_identity_ignore_storage_order(self):
        r=read_nc_scalar(self.path,"waterlevel",("station_id","W1"))
        self.assertEqual(r["values"],[1.,2.,3.])
        self.assertEqual(r["iso"][-1],"2001-01-01T00:02:00")

    def test_fixed_width_masked_trailing_padding_and_encoding_are_allowed(self):
        with nc.Dataset(self.path,"r+") as ds:
            ds.createDimension("width",8)
            ids=ds.createVariable("char_id","S1",("station","width"))
            ids[:]=np.array([list(b"W2\x00\x00\x00\x00\x00\x00"),list(b"W1\x00\x00\x00\x00\x00\x00")],dtype="u1").view("S1")
            ids.setncattr("_Encoding","ascii")
        self.assertEqual(read_nc_scalar(self.path,"waterlevel",("char_id","W1"))["values"],[1.,2.,3.])
        with nc.Dataset(self.path,"r+") as ds:
            ds["waterlevel"][0,1]=-999.
        with self.assertRaisesRegex(AssertionError,"masked/nonfinite"):
            read_nc_scalar(self.path,"waterlevel",("char_id","W1"))

    def test_fixed_width_interior_missing_character_is_not_padding(self):
        with nc.Dataset(self.path,"r+") as ds:
            ds.createDimension("width",4)
            ids=ds.createVariable("char_id","S1",("station","width"))
            ids[:]=np.array([list(b"W2\x00\x00"),list(b"W\x001\x00")],dtype="u1").view("S1")
        with self.assertRaisesRegex(AssertionError,"embedded-NUL|interior"):
            read_nc_scalar(self.path,"waterlevel",("char_id","W1"))

    def test_ambiguous_missing_ids_and_masked_data_are_refused(self):
        with self.assertRaises(AssertionError):
            read_nc_scalar(self.path,"waterlevel",("station_id","MISSING"))
        with nc.Dataset(self.path,"r+") as ds:
            ds["station_id"][:]=np.array(["W1","W1"],dtype=object)
        with self.assertRaisesRegex(AssertionError,"ambiguous"):
            read_nc_scalar(self.path,"waterlevel",("station_id","W1"))
        with nc.Dataset(self.path,"r+") as ds:
            ds["station_id"][:]=np.array(["W2","W1"],dtype=object)
            ds["waterlevel"][1,1]=-999.
        with self.assertRaisesRegex(AssertionError,"masked/nonfinite"):
            read_nc_scalar(self.path,"waterlevel",("station_id","W1"))

    def pi(self,series_count=1):
        series='''<series><header><locationId>weir</locationId><parameterId>crest_level</parameterId><units>m</units><missVal>-999</missVal></header>
<event date="2001-01-01" time="09:00:00" value="1"/><event date="2001-01-01" time="09:01:00" value="2"/></series>'''
        path=self.root/"output.xml"
        path.write_text('<TimeSeries xmlns="http://www.wldelft.nl/fews/PI"><timeZone>9</timeZone>'+series*series_count+'</TimeSeries>')
        return path

    def test_pi_timezone_units_and_series_identity_are_explicit(self):
        r=read_pi_scalar(self.pi(),"weir","crest_level","m")
        self.assertEqual(r["iso"],["2001-01-01T00:00:00","2001-01-01T00:01:00"])
        with self.assertRaisesRegex(AssertionError,"units"):
            read_pi_scalar(self.pi(),"weir","crest_level","cm")
        with self.assertRaisesRegex(AssertionError,"ambiguous"):
            read_pi_scalar(self.pi(2),"weir","crest_level","m")


if __name__=="__main__":
    unittest.main()
