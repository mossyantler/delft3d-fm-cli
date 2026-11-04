"""Portable tests of the RTC native replay's independent raw-data contract."""
from __future__ import annotations

import contextlib
import copy
from datetime import datetime,timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from research.workflows.verification.verify_rtc_exchange_checkpoint import hydraulic_checkpoint,unique_coordinate_map

from research.workflows.verification.verify_rtc_exchange_native import (
    compare_sources, main, read_dimr_logger, read_rtc_csv, receipt_oracle,
    shifted_y_only, source_inventory, terminal_receipt,
    bootstrap_review,
    section_discharge,
    causal_comparison,
)

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc=np=None


def rule(shift=0):
    records=''.join(f'<record x="{x}" y="{y+shift:g}" />' for x,y in [(0,0),(2,0),(10,5),(20,5)])
    return ('<rtcToolsConfig><lookupTable><table>'+records+'</table><interpolationOption>LINEAR</interpolationOption><extrapolationOption>BLOCK</extrapolationOption><input><x ref="IMPLICIT">input_ObservationPoint01_water_level</x></input><output><y>output_weir_crest_level</y></output></lookupTable></rtcToolsConfig>').encode()


class MatchedRtcPairTests(unittest.TestCase):
    def test_schema_bootstrap_contains_no_physical_input_mapping_or_event_data(self):
        raw=b'<TimeSeries><timeZone>0</timeZone><series><header><locationId>interface_bootstrap</locationId><parameterId>unused</parameterId></header></series></TimeSeries>'
        self.assertEqual(bootstrap_review(raw)["state"],"metadata_only_unmapped_no_events")
        for bad in (raw.replace(b'interface_bootstrap',b'ObservationPoint01'),raw.replace(b'</series>',b'<event date="2015-05-27" time="00:00:00" value="9"/></series>')):
            with self.assertRaises(AssertionError):bootstrap_review(bad)

    def test_exact_rule_y_shift_keeps_x_units_order_and_all_unrelated_bytes(self):
        self.assertEqual(shifted_y_only(rule(),rule(.25))["shift_m"],.25)
        for changed in (rule(.3),rule(.25).replace(b'x="10"',b'x="11"'),rule(.25).replace(b'IMPLICIT',b'EXPLICIT')):
            with self.assertRaises(AssertionError):shifted_y_only(rule(),changed)

    def test_source_file_sets_and_all_noncontroller_input_bytes_must_match(self):
        with tempfile.TemporaryDirectory(prefix="dfm-rtc-pair-") as temp:
            root=Path(temp);specs=[]
            for label,shift in (("positive",0),("changed",.25)):
                source=root/label;source.mkdir();(source/"rtc/xml_dir").mkdir(parents=True);(source/"fm").mkdir()
                (source/"rtc/xml_dir/rtcToolsConfig.xml").write_bytes(rule(shift));(source/"fm/model.mdu").write_text("same input")
                spec={"profile":"fm_rtc","source":{"root":label,"files":["fm/model.mdu","rtc/xml_dir/rtcToolsConfig.xml"]},
                      "clock":{"reference":"2015-05-27T00:00:00Z","start":"2015-05-27T00:00:00Z","stop":"2015-05-27T00:10:00Z"},
                      "components":[{"library":"dflowfm"},{"library":"FBCTools_BMI"}],"control":[],"couplers":[],"patches":[],"observables":[]}
                path=root/(label+".json");path.write_text(json.dumps(spec));specs.append(path)
            a,b=map(source_inventory,specs)
            self.assertEqual(compare_sources(a,b)["all_other_source_files_identical"],1)
            (root/"changed/fm/model.mdu").write_text("also changes forcing")
            with self.assertRaisesRegex(AssertionError,"Exactly one controller"):
                compare_sources(a,source_inventory(specs[1]))

    def test_no_native_flag_can_start_without_explicit_slot_record(self):
        with patch("research.workflows.verification.verify_rtc_exchange_native.subprocess.Popen",side_effect=AssertionError("must not launch")),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                main(["--positive-spec","absent-positive.json","--changed-spec","absent-changed.json","--out","unused","--install","unused","--native"])
            self.assertEqual(result.exception.code,2)


class RtcPerExchangeReceiverTests(unittest.TestCase):
    def setUp(self):
        received=[0.,3.,5.,7.,9.,10.,8.,6.,4.,2.]
        outputs=[0.,0.,.625,1.875,3.125,4.375,5.,3.75,2.5,1.25,0.]
        self.data={"level":{"values":received+[0.]},"crest":{"values":[0.]+outputs[1:]},
                   "inbound":{"values":list(received)},"outbound":{"values":outputs[1:]},"pi":{"values":list(outputs)},
                   "csv":{"columns":{"input_ObservationPoint01_water_level":received+[None],"output_weir_crest_level":list(outputs)}}}
        self.knots=[(0,0),(2,0),(10,5),(20,5)]

    def test_every_transaction_crosses_raw_sender_receiver_controller_and_actual_actuator(self):
        report=receipt_oracle(self.data,self.knots)
        self.assertEqual(report["transactions"],10)
        self.assertEqual(report["controller_expected_m"][2],1.875)

    def test_sender_log_agreement_does_not_replace_independent_received_samples(self):
        self.data["csv"]["columns"]["input_ObservationPoint01_water_level"][3]=6.
        with self.assertRaisesRegex(AssertionError,"received state"):
            receipt_oracle(self.data,self.knots)

    def test_streamed_controller_csv_requires_applied_fm_crest_without_disabled_pi(self):
        del self.data["pi"]
        self.assertEqual(receipt_oracle(self.data,self.knots)["state"],"passed")
        self.data["crest"]["values"][5]+=1.
        with self.assertRaises(AssertionError):receipt_oracle(self.data,self.knots)

    def test_lagged_controller_values_are_not_shifted_until_they_fit(self):
        case=copy.deepcopy(self.data)
        case["csv"]["columns"]["output_weir_crest_level"]= [0.]+case["csv"]["columns"]["output_weir_crest_level"][:-1]
        with self.assertRaisesRegex(AssertionError,"independent controller"):
            receipt_oracle(case,self.knots)

    def test_completed_state_and_empty_pid_list_do_not_replace_member_handle_exit(self):
        record={"state":"completed","returncode":0,"verification":{"state":"passed"},
                "ownership":{"method":"windows_job_object","assigned_before_resume":True},
                "termination":{"tree_terminated":True,"job_pids_after":[],"owned_process_exited":True,"member_exit_confirmations":{"root":True,"helper":True}}}
        self.assertEqual(terminal_receipt(record)["state"],"passed")
        record["termination"]["member_exit_confirmations"]["helper"]=None
        with self.assertRaisesRegex(AssertionError,"member handles"):
            terminal_receipt(record)


class RtcCsvTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="dfm-rtc-csv-");self.addCleanup(t.cleanup)
        self.path=Path(t.name)/"timeseries_0000.csv";self.start=datetime(2015,5,27)
        lines=["date time,input_ObservationPoint01_water_level,output_weir_crest_level,Control Group 1Lookup table_isActive"]
        for i in range(11):
            lines.append((self.start+timedelta(seconds=i*60)).strftime("%Y-%m-%d %H:%M:%S")+f",{i if i<10 else ''},{i*.25}"+(",1" if i<10 else ""))
        self.path.write_text('\n'.join(lines)+'\n')

    def test_native_csv_preserves_receiver_identity_final_output_and_unset_terminal_input(self):
        result=read_rtc_csv(self.path,self.start)
        self.assertEqual(result["columns"]["input_ObservationPoint01_water_level"][:3],[0.,1.,2.])
        self.assertIsNone(result["terminal_input_value"])
        self.assertEqual(result["columns"]["output_weir_crest_level"][-1],2.5)

    def test_required_per_exchange_input_and_terminal_output_cannot_be_blank(self):
        raw=self.path.read_text()
        for bad in (raw.replace("00:03:00,3,", "00:03:00,,"),raw.replace("00:10:00,,2.5", "00:10:00,,")):
            self.path.write_text(bad)
            with self.assertRaisesRegex(AssertionError,"blank/nonfinite"):read_rtc_csv(self.path,self.start)

    def test_time_relabelling_and_duplicate_headers_are_refused(self):
        raw=self.path.read_text()
        for bad in (raw.replace("00:03:00", "00:04:00"),raw.replace("output_weir_crest_level", "input_ObservationPoint01_water_level")):
            self.path.write_text(bad)
            with self.assertRaises(AssertionError):read_rtc_csv(self.path,self.start)

    def test_only_terminal_writer_may_omit_rule_flag_and_inactive_rule_fails(self):
        raw=self.path.read_text()
        for bad in (raw.replace("00:03:00,3,0.75,1", "00:03:00,3,0.75"),
                    raw.replace("00:03:00,3,0.75,1", "00:03:00,3,0.75,0"),
                    raw.replace("00:10:00,,2.5", "00:10:00,,2.5,1")):
            self.path.write_text(bad)
            with self.assertRaises(AssertionError):read_rtc_csv(self.path,self.start)


@unittest.skipIf(nc is None,"optional netCDF4 required")
class NativeDimrLoggerTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="dfm-dimr-logger-");self.addCleanup(t.cleanup)
        self.path=Path(t.name)/"flow2rtc.nc";self.start=datetime(2015,5,27)
        self.source="observations/Upstream/water_level";self.target="input_ObservationPoint01_water_level"
        with nc.Dataset(self.path,"w") as ds:
            ds.createDimension("time_offset",10);ds.createDimension("item1_nValues",1)
            t=ds.createVariable("time_offset","f8",("time_offset",),fill_value=-999.)
            t.units="seconds since 1980-01-01T00:00:00";t.long_name="seconds since simulation reference date, T00:00:00";t[:]=list(range(0,600,60))
            v=ds.createVariable("item1_values","f8",("time_offset","item1_nValues"),fill_value=-999.)
            v.long_name=self.source+" -> "+self.target;v[:]=1.

    def read(self):return read_dimr_logger(self.path,self.source,self.target,self.start,range(0,600,60))

    def test_actual_native1980_metadata_is_retained_separate_from_declared_master_offsets(self):
        result=self.read()
        self.assertIn("1980",result["raw_units"])
        self.assertEqual(result["iso"][0],"2015-05-27T00:00:00")
        self.assertEqual(result["raw_offsets_seconds"][-1],540.)

    def test_masked_or_wrong_actual_offsets_fail_without_trimming_or_padding(self):
        with nc.Dataset(self.path,"r+") as ds:ds["time_offset"][9]=600.
        with self.assertRaisesRegex(AssertionError,"actual offsets"):self.read()
        with nc.Dataset(self.path,"r+") as ds:ds["time_offset"][9]=-999.
        with self.assertRaisesRegex(AssertionError,"missing/nonfinite"):self.read()

    def test_wrong_pair_identity_or_unreviewed_native_unit_metadata_is_refused(self):
        with nc.Dataset(self.path,"r+") as ds:ds["item1_values"].long_name="different -> receiver"
        with self.assertRaisesRegex(AssertionError,"identity"):self.read()
        with nc.Dataset(self.path,"r+") as ds:
            ds["item1_values"].long_name=self.source+" -> "+self.target
            ds["time_offset"].units="seconds since 2015-05-27T00:00:00"
        with self.assertRaisesRegex(AssertionError,"metadata"):self.read()


@unittest.skipIf(nc is None,"optional netCDF4 required")
class FiniteSectionPlanTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="dfm-rtc-section-");self.addCleanup(t.cleanup)
        self.path=Path(t.name)/"map.nc";self.line=Path(t.name)/"weir.pli"
        self.line.write_text("L1\n2 2\n0 -1\n0 1\n")
        with nc.Dataset(self.path,"w") as ds:
            for k,n in [('time',3),('mesh2d_nFaces',2),('mesh2d_nEdges',2),('Two',2)]:ds.createDimension(k,n)
            t=ds.createVariable('time','f8',('time',));t.units='seconds since 2015-05-27 00:00:00';t[:]=[0,60,120]
            for k,values in [('mesh2d_face_x',[-1,1]),('mesh2d_face_y',[0,0])]:
                v=ds.createVariable(k,'f8',('mesh2d_nFaces',));v.units='m';v[:]=values
            f=ds.createVariable('mesh2d_edge_faces','i4',('mesh2d_nEdges','Two'),fill_value=-999);f.start_index=1;f[:]=[[1,2],[1,-999]]
            q=ds.createVariable('mesh2d_q1','f8',('time','mesh2d_nEdges'),fill_value=-999.)
            q.units='m3 s-1';q.location='edge';q.comment='Positive direction is from first to second neighbouring face (flow element).';q[:]=[[0,-999],[3,-999],[4,-999]]

    def test_signed_geometric_section_ignores_boundary_not_missing_physics(self):
        a=section_discharge(self.path,self.line)
        self.assertEqual(a['edge_indices_zero_based'],[0]);self.assertEqual(a['values'],[0.,-3.,-4.])
        self.assertEqual(a['state'],'finite_observation_only_not_acceptance')
        self.line.write_text("L1\n2 2\n0 1\n0 -1\n")
        self.assertEqual(section_discharge(self.path,self.line)['values'],[0.,3.,4.])

    def test_masked_selected_flow_is_never_zero_or_interpolated(self):
        with nc.Dataset(self.path,'r+') as ds:ds['mesh2d_q1'][1,0]=-999.
        with self.assertRaisesRegex(AssertionError,'masked/nonfinite'):section_discharge(self.path,self.line)

    def test_unknown_native_sign_convention_refuses_plan(self):
        with nc.Dataset(self.path,'r+') as ds:ds['mesh2d_q1'].comment='unknown'
        with self.assertRaisesRegex(AssertionError,'orientation'):section_discharge(self.path,self.line)

    def test_actual_upstream_downstream_geometry_defines_positive_flow(self):
        obs=self.line.with_name('obs.xyn');obs.write_text('1 0 Upstream\n-1 0 Downstream\n')
        self.assertEqual(section_discharge(self.path,self.line,obs)['physical_orientation'],'Upstream to Downstream')
        obs.write_text('-1 0 Upstream\n1 0 Downstream\n')
        with self.assertRaisesRegex(AssertionError,'Upstream to Downstream'):section_discharge(self.path,self.line,obs)


class NaturalExitProofTests(unittest.TestCase):
    def setUp(self):
        self.root={'identity':{'pid':123,'creation_time_100ns':'123456'},'image':str(Path('native.exe').resolve()),'handle_signalled':True,'exit_code':0}
        normal={'method':'windows_job_object_normal_exit','state':'captured','termination_attempted':False,
                'root':{'pid':123,'handle_source':'original_subprocess.Popen._handle','state':'signalled','wait_result':0,'wait_timeout_ms':0,'exit_confirmed':True,'exit_code':0,'exit_code_query':{'state':'captured'}},
                'job_accounting':{'state':'captured','handle_source':'retained_OwnedJob.handle','information_class':1,'structure':'JOBOBJECT_BASIC_ACCOUNTING_INFORMATION','buffer_bytes':48,'returned_bytes':48,'values':{'TotalUserTime':0,'TotalKernelTime':0,'ThisPeriodTotalUserTime':0,'ThisPeriodTotalKernelTime':0,'TotalPageFaultCount':0,'TotalProcesses':1,'ActiveProcesses':0,'TotalTerminatedProcesses':0}},
                'job_members':{'state':'captured','pids':[]},'job_pids_after':[],'member_exit_confirmations':{'123':True},'retained_member_handle_count':1,'confirmed_member_exit_count':1,'unobserved_member_count':0,'total_processes':1,'active_processes':0,'sole_ever_member':True,'all_owned_members_exit_confirmed':True,'root_exit_confirmed':True,'job_empty':True}
        self.record={'state':'completed','returncode':0,'verification':{'state':'passed'},'argv':[self.root['image']],
                     'ownership':{'method':'windows_job_object','assigned_before_resume':True,'kill_on_owner_handle_close':True,'native_identity':dict(self.root['identity']),'final_job_pids':[],'normal_exit':normal}}

    def test_natural_root_only_exit_needs_no_forced_termination(self):
        self.assertEqual(terminal_receipt(self.record,self.root)['state'],'passed')
        self.assertNotIn('termination',self.record)

    def test_original_partial_record_without_any_member_proof_still_fails(self):
        del self.record['ownership']['normal_exit']
        with self.assertRaises(AssertionError):terminal_receipt(self.record,self.root)

    def test_capture_requires_independent_retained_identity_not_pid_presence(self):
        for change in ({'identity':{'pid':123,'creation_time_100ns':'reused'}},{'handle_signalled':False},{'exit_code':1},{'image':'different.exe'}):
            independent={**self.root,**change}
            with self.subTest(change=change),self.assertRaises(AssertionError):terminal_receipt(self.record,independent)
        with self.assertRaises(AssertionError):terminal_receipt(self.record)

    def test_empty_job_cannot_hide_historical_child_or_failed_accounting(self):
        changes=[lambda n:n['job_accounting']['values'].update(TotalProcesses=2),
                 lambda n:n['job_accounting']['values'].update(ActiveProcesses=1),
                 lambda n:n['job_accounting']['values'].update(TotalTerminatedProcesses=1),
                 lambda n:n['job_accounting'].update(state='unavailable'),
                 lambda n:n['job_accounting'].update(returned_bytes=0),
                 lambda n:n['root'].update(wait_result=258),
                 lambda n:n['root'].update(handle_source='reopened_pid'),
                 lambda n:n.update(member_exit_confirmations={}),
                 lambda n:n.update(retained_member_handle_count=0),
                 lambda n:n['job_members'].update(pids=[124])]
        for change in changes:
            record=copy.deepcopy(self.record);change(record['ownership']['normal_exit'])
            with self.subTest(change=change),self.assertRaises(AssertionError):terminal_receipt(record,self.root)

    def test_json_booleans_cannot_stand_in_for_native_integer_evidence(self):
        paths=[('returncode',),('ownership','native_identity','pid'),
               *[('ownership','normal_exit','root',k) for k in ('pid','wait_result','wait_timeout_ms','exit_code')],
               *[('ownership','normal_exit','job_accounting',k) for k in ('information_class','buffer_bytes','returned_bytes')],
               *[('ownership','normal_exit','job_accounting','values',k) for k in self.record['ownership']['normal_exit']['job_accounting']['values']],
               *[('ownership','normal_exit',k) for k in ('retained_member_handle_count','confirmed_member_exit_count','unobserved_member_count','total_processes','active_processes')]]
        for path in paths:
            for value in (False,True,0.0,None):
                record=copy.deepcopy(self.record);obj=record
                for part in path[:-1]:obj=obj[part]
                obj[path[-1]]=value
                with self.subTest(path=path,value=value),self.assertRaises(AssertionError):terminal_receipt(record,self.root)
        for path in [('exit_code',),('identity','pid')]:
            independent=copy.deepcopy(self.root);obj=independent
            for part in path[:-1]:obj=obj[part]
            obj[path[-1]]=False
            with self.subTest(independent_path=path),self.assertRaises(AssertionError):terminal_receipt(self.record,independent)


class ProspectiveHydraulicControlTests(unittest.TestCase):
    def cases(self):
        a={'raw':{},'executable_sha256':'same','FM_map_axis':{'path':'mapA'}}
        for key,unit,values in [('crest','m',[0.,0.,1.]),('section_discharge','m3 s-1',[0.,0.,3.]),('level','m',[0.,2.,4.]),('downstream','m',[0.,0.,1.])]:
            a['raw'][key]={'path':'historyA','iso':['t0','t1','t2'],'unit':unit,'values':values}
        a['raw']['section_discharge'].update(edge_indices_zero_based=[3,5],signed_orientation=[1.,-1.],intersection_xy_m=[[0.,1.],[0.,2.]],polyline_sha256='same',topology_sha256='same',observation_sha256='same',observation_xy_m={'Upstream':[1,0],'Downstream':[-1,0]},physical_orientation='Upstream to Downstream')
        a['raw']['discharge_history']={'values':[None,None,3.],'mask':[True,True,False]}
        b=copy.deepcopy(a);b['raw']['crest']['values'][2]+=.25;b['raw']['section_discharge']['values'][2]+=.2;b['raw']['downstream']['values'][2]+=.01
        return a,b

    @patch('research.workflows.verification.verify_rtc_exchange_native.netcdf_differential',return_value={})
    def test_finite_signed_section_and_actual_downstream_effect_required(self,_):
        a,b=self.cases();before=copy.deepcopy(a['raw']['discharge_history'])
        self.assertEqual(causal_comparison(a,b)['state'],'passed');self.assertEqual(a['raw']['discharge_history'],before)
        b['raw']['downstream']['values']=list(a['raw']['downstream']['values']);b['raw']['level']['values'][2]+=1.
        with self.assertRaisesRegex(AssertionError,'downstream'):causal_comparison(a,b)

    @patch('research.workflows.verification.verify_rtc_exchange_native.netcdf_differential',return_value={})
    def test_wrong_section_identity_or_absent_flow_effect_cannot_pass(self,_):
        a,b=self.cases();b['raw']['section_discharge']['signed_orientation']=[-1.,1.]
        with self.assertRaisesRegex(AssertionError,'section changed'):causal_comparison(a,b)
        a,b=self.cases();b['raw']['section_discharge']['values']=list(a['raw']['section_discharge']['values'])
        with self.assertRaisesRegex(AssertionError,'discharge effect'):causal_comparison(a,b)


@unittest.skipIf(np is None,'optional NumPy required')
class CheckpointCoordinateProofTests(unittest.TestCase):
    def test_unique_projection_reorders_instead_of_trusting_file_indices(self):
        self.assertEqual(unique_coordinate_map([[1,2],[3,4]],[[3,4],[1,2]])[0],[1,0])
        for right in ([[1,2],[1,2]],[[1.001,2],[3,4]]):
            with self.assertRaisesRegex(AssertionError,'Missing/ambiguous'):unique_coordinate_map([[1,2]],right)


@unittest.skipIf(nc is None,'optional netCDF4 required')
class HydraulicCheckpointGateTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix='dfm-rtc-checkpoint-');self.addCleanup(t.cleanup)
        self.rst=Path(t.name)/'rst.nc';self.map=Path(t.name)/'map.nc'
        with nc.Dataset(self.rst,'w') as ds:
            for k,n in [('time',1),('nFlowElem',2),('nFlowLink',2)]:ds.createDimension(k,n)
            time=ds.createVariable('time','f8',('time',));time.units='seconds since 2015-05-27 00:00:00';time[:]=[600]
            for k,dim,values in [('FlowElem_xcc','nFlowElem',[1,2]),('FlowElem_ycc','nFlowElem',[0,0]),('FlowLink_xu','nFlowLink',[10,20]),('FlowLink_yu','nFlowLink',[0,0])]:
                v=ds.createVariable(k,'f8',(dim,));v.units='m';v[:]=values
            for k,dim,unit,values in [('s1','nFlowElem','m',[1.000000003,2.5]),('q1','nFlowLink','m3 s-1',[-4.1,3.2])]:
                v=ds.createVariable(k,'f8',('time',dim),fill_value=-999.);v.units=unit;v[:]=[values]
        with nc.Dataset(self.map,'w') as ds:
            for k,n in [('time',2),('face',2),('edge',3),('Two',2)]:ds.createDimension(k,n)
            time=ds.createVariable('time','f8',('time',));time.units='seconds since 2015-05-27 00:00:00';time[:]=[0,600]
            for k,dim,values in [('mesh2d_face_x','face',[2,1]),('mesh2d_face_y','face',[0,0]),('mesh2d_edge_x','edge',[20,10,30]),('mesh2d_edge_y','edge',[0,0,0])]:
                v=ds.createVariable(k,'f8',(dim,));v.units='m';v[:]=values
            f=ds.createVariable('mesh2d_edge_faces','i4',('edge','Two'),fill_value=-999);f[:]=[[1,2],[2,1],[1,-999]]
            for k,dim,unit,values in [('mesh2d_s1','face','m',[2.5,1.000000003]),('mesh2d_q1','edge','m3 s-1',[3.2,-4.1,0.])]:
                v=ds.createVariable(k,'f4',('time',dim),fill_value=-999.);v.units=unit;v[:]=[values,values]

    def test_final_projected_physics_passes_but_saved_actuator_stays_unknown(self):
        result=hydraulic_checkpoint(self.rst,self.map)
        self.assertEqual(result['fields']['water_level']['map_indices_zero_based'],[1,0])
        self.assertEqual(result['fields']['signed_flow']['map_indices_zero_based'],[1,0])
        self.assertEqual(result['fields']['signed_flow']['unmatched_map_locations'],[2])
        self.assertEqual(result['saved_actuator_restorability_gate']['state'],'not_established')
        self.assertFalse(result['saved_actuator_restorability_gate']['restart_actuator_field_present'])

    def test_wrong_signed_flow_or_mask_is_not_quantization(self):
        for value in (4.1,-999.):
            with nc.Dataset(self.map,'r+') as ds:ds['mesh2d_q1'][1,1]=value
            with self.subTest(value=value),self.assertRaises(AssertionError):hydraulic_checkpoint(self.rst,self.map)

    def test_unmatched_nonzero_map_edge_is_not_assumed_closed(self):
        with nc.Dataset(self.map,'r+') as ds:ds['mesh2d_q1'][1,2]=1.
        with self.assertRaisesRegex(AssertionError,'nonzero'):hydraulic_checkpoint(self.rst,self.map)

    def test_saved_field_presence_alone_is_not_restorability(self):
        with nc.Dataset(self.rst,'r+') as ds:
            ds.createDimension('weir',1);v=ds.createVariable('weirgen_crest_level','f8',('time','weir'));v.units='m';v[:]=4.
        result=hydraulic_checkpoint(self.rst,self.map)['saved_actuator_restorability_gate']
        self.assertTrue(result['restart_actuator_field_present']);self.assertEqual(result['state'],'not_established')


if __name__=="__main__":
    unittest.main()
