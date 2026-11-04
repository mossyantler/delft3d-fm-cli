"""Portable f152 candidate/identity/read-predicate tests; no native processes."""
from __future__ import annotations

import copy
from pathlib import Path
import struct
import tempfile
import unittest

from research.workflows.verification.verify_rtc_exchange import synthetic_pairs
from research.workflows.verification.verify_rtc_exchange_rr import (
    fm_clock, matching_exchanges, optional_classification, rain_contract,
    rr_bidirectional_oracle, rr_clock, rr_topology,
)


NODES=b"NODE id 'unp' mt 1 '2' nt 44 node\nNODE id 'lat_1209' mt 1 '6' nt 78 node\nNODE id 'orphan' mt 1 '6' nt 78 node\n"
LINKS=b"BRCH id '1' bn 'unp' en 'lat_1209' bt 17 brch\n"


class RrMatchingCandidateTests(unittest.TestCase):
    def test_authoritative_internal_mt_type_used_and_orphan_boundary_preserved_without_link_invention(self):
        graph=rr_topology(NODES,LINKS)
        self.assertEqual(graph["internal_type_counts"],{"2":1,"6":2})
        self.assertEqual(graph["nodes"]["unp"]["external_nt"],44)
        self.assertEqual(graph["boundary_nodes_without_links"],["orphan"])
        self.assertEqual(len(graph["links"]),1)

    def test_absent_link_endpoint_and_disconnected_runoff_node_are_refused(self):
        with self.assertRaisesRegex(AssertionError,"absent/self"):
            rr_topology(NODES,LINKS.replace(b"en 'lat_1209'",b"en 'invented'"))
        with self.assertRaisesRegex(AssertionError,"active runoff node"):
            rr_topology(NODES+b"NODE id 'unp2' mt 1 '2' nt 44 node\n",LINKS)

    def test_same_external_nt_does_not_override_engine_internal_node_type(self):
        raw=NODES.replace(b"mt 1 '2' nt 44",b"mt 1 '21' nt 44")
        self.assertEqual(rr_topology(raw,LINKS)["nodes"]["unp"]["internal_type"],21)

    def mappings(self):
        graph=rr_topology(NODES.replace(b"NODE id 'orphan' mt 1 '6' nt 78 node\n",b""),LINKS)
        contract={"components":{"FM":{"library":"dflowfm"},"RR":{"library":"rr_dll"}},
                  "groups":[{"sequence":[("coupler","flow2rr"),("start","RR"),("coupler","rr2flow")]}],
                  "couplers":{"flow2rr":{"source":"FM","target":"RR","items":[("laterals/lat_1209/water_level","catchments/lat_1209/water_level")]},
                              "rr2flow":{"source":"RR","target":"FM","items":[("catchments/lat_1209/water_discharge","laterals/lat_1209/water_discharge")]}}}
        ext=b"[Lateral]\nid=lat_1209\ntype=discharge\nlocationType=1d\nbranchId=real_branch\nchainage=10\ndischarge=REALTIME\n"
        bc=b"[Boundary]\nname=lat_1209\nquantity=water_level\nunit=m\nfunction=constant\n0\n"
        return contract,graph,ext,bc

    def test_both_directions_match_actual_graph_boundary_and_realtime_fm_lateral(self):
        result=matching_exchanges(*self.mappings())
        self.assertEqual(result["exchange_ids"],["lat_1209"])
        self.assertEqual(set(result["directions"]),{"water_level","water_discharge"})

    def test_borrowed_c11_id_unpaired_mapping_and_wrong_water_unit_are_refused(self):
        c,g,e,b=self.mappings()
        c["couplers"]["rr2flow"]["items"]=[("catchments/10634/water_discharge","laterals/10634/water_discharge")]
        with self.assertRaisesRegex(AssertionError,"absent from matching"):
            matching_exchanges(c,g,e,b)
        c,g,e,b=self.mappings()
        with self.assertRaisesRegex(AssertionError,"quantity/units"):
            matching_exchanges(c,g,e,b.replace(b"unit=m\n",b"unit=cm\n"))
        c["groups"][0]["sequence"].reverse()
        with self.assertRaisesRegex(AssertionError,"bracketed"):
            matching_exchanges(c,g,e,b)


class RrReadPredicateTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="dfm-rr-optional-");self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        (self.root/"PAVED.3B").write_text("PAVE id 'p' qc 0 pave\n")
        (self.root/"UNPAVED.3B").write_text("UNPV id 'u' ig 0 su 0 sp 's' unpv\n")
        (self.root/"UNPAVED.SEP").write_text("SEEP id 's' co 4\nTBLE\n'2000/01/01;00:00:00' 0 <\ntble\nseep\n")
        for name in ("paved.tbl","unpaved.tbl","greenhse.3b"):
            (self.root/name).write_bytes(b"")
        (self.root/"Sobek_3b.fnm").write_text("'paved.tbl' * 8. pump table I\n'unpaved.tbl' * 34. initial table I\n'greenhse.3b' * 35. greenhouse I\n")
        self.graph={"internal_type_counts":{"1":1,"2":1,"6":1},"nodes":{"p":{"internal_type":1},"u":{"internal_type":2},"b":{"internal_type":6}}}

    def test_empty_tables_are_optional_only_for_active_constant_options_and_inline_sep(self):
        r=optional_classification(self.root,self.graph)
        self.assertEqual([v["classification"] for v in r["empty_or_missing_inputs"]],
                         ["opened_empty_table_not_selected","opened_empty_table_not_selected","inactive_node_family"])
        self.assertEqual(r["inline_seepage_tables"],1)

    def test_active_table_options_cannot_be_dismissed_because_file_is_empty(self):
        (self.root/"PAVED.3B").write_text("PAVE id 'p' qc 1 'pump_table' pave\n")
        (self.root/"UNPAVED.3B").write_text("UNPV id 'u' ig 1 'gw_table' su 0 sp 's' unpv\n")
        r=optional_classification(self.root,self.graph)
        self.assertEqual([v["classification"] for v in r["empty_or_missing_inputs"]][:2],["unresolved_optional_predicate"]*2)

    def test_active_greenhouse_node_changes_empty_file_classification(self):
        self.graph["internal_type_counts"]["3"]=1
        r=optional_classification(self.root,self.graph)
        self.assertEqual(r["empty_or_missing_inputs"][-1]["classification"],"unresolved_optional_predicate")

    def test_inline_seepage_tables_are_real_required_records(self):
        (self.root/"UNPAVED.SEP").write_text("SEEP id 's' co 4 seep\n")
        with self.assertRaisesRegex(AssertionError,"inline seepage"):
            optional_classification(self.root,self.graph)


class RrClockAndTwoWayOracleTests(unittest.TestCase):
    def test_rr_day_long_clock_is_not_silently_truncated_to_dimr600(self):
        raw=b"[TimeSettings]\nTimestepSize=300\nStartTime=2000/01/01;00:00:00\nEndTime=2000/01/02;00:00:00\n"
        r=rr_clock(raw)
        self.assertEqual(r["duration_seconds"],86400.)
        self.assertEqual(r["step_seconds"],300.)

    def test_fm_interval_vectors_are_seconds_independent_of_relative_clock_unit(self):
        raw=b"[time]\nRefDate=20000101\nTUnit=M\nTZone=0\nTStart=0\nTStop=10\nDtUser=60\n[output]\nHisInterval=120 0 0\nMapInterval=600 0 0\nRstInterval=86400 0 0\n"
        r=fm_clock(raw)
        self.assertEqual(r["duration_seconds"],600.)
        self.assertEqual(r["output_interval_vectors_seconds"]["output/rstinterval"],[86400.,0.,0.])

    def test_rain_depth_is_mm_per_record_not_a_rate_and_trailing_rows_are_reported(self):
        raw=b"* comments\n1\n2\n'A'\n'B'\n1 86400\n2000 1 1 0 0 0 1 0 0 0\n24 48\n0 0\n"
        r=rain_contract(raw)
        self.assertEqual(r["trailing_rows"],1)
        self.assertEqual(r["first_interval_rate_m_s"],[.024/86400,.048/86400])
        with self.assertRaisesRegex(AssertionError,"columns"):
            rain_contract(raw.replace(b"24 48",b"24"))

    def two_way_case(self):
        case=synthetic_pairs()["rr"]["positive"]
        values=[12.,12.1,12.2,12.3]
        rounded=[struct.unpack("f",struct.pack("f",v))[0] for v in values]
        case["fm_water_level"]={"C1":{"seconds":[0,60,120,180],"values":values,"unit":"m","address":"laterals/C1/water_level"}}
        case["rr_received_level"]={"C1":{"seconds":[0,60,120,180],"values":rounded,"unit":"m","address":"catchments/C1/water_level"}}
        return case

    def test_level_input_and_discharge_return_are_both_checked_with_declared_single_precision_bound(self):
        r=rr_bidirectional_oracle(self.two_way_case())
        self.assertEqual(r["water_level_direction"],"passed")
        self.assertEqual(r["discharge_direction"],"passed")
        self.assertEqual(r["expected_signed_volume_m3"],240.)

    def test_correct_discharge_cannot_hide_wrong_level_receiver_or_phase(self):
        case=self.two_way_case();case["rr_received_level"]["C1"]["values"][1]=11.
        with self.assertRaisesRegex(AssertionError,"boundary received"):
            rr_bidirectional_oracle(case)
        case=self.two_way_case();case["rr_received_level"]["C1"]["seconds"]=[60,120,180,240]
        with self.assertRaisesRegex(AssertionError,"schedule/phase"):
            rr_bidirectional_oracle(case)


if __name__=="__main__":
    unittest.main()
