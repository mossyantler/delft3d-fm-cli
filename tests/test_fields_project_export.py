"""Independent raw export tests. Synthetic inputs never prove GUI execution."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.verification.verify_fields_project_export import (
    FILES,compare_exports,graph,guest_readiness,inventory,manning_seed,records,sha,installed_schema,SCHEMA_PATH,audit_export_tree,
)


def exported(root):
    root.mkdir()
    for name in FILES-{'f34.mdu'}:(root/name).write_bytes(('synthetic bytes '+name+'\r\n').encode())
    (root/'f34_bnd.ext').write_bytes(b'[General]\r\nfileType=extForce\r\n[Boundary]\r\nlocationFile=f34_001.pli\r\nforcingFile=f34_001.bc\r\n[Meteo]\r\nforcingFile=f34.wnd\r\nforcingFileType=uniMagDir\r\n')
    (root/'f34_001.bc').write_bytes(b'[General]\r\nfileType=boundConds\r\n[Forcing]\r\nName=L1_0001\r\nQuantity=time\r\nUnit=s\r\nQuantity=waterlevelbnd\r\nUnit=m\r\n0 0\r\n120 0\r\n[Forcing]\r\nName=L1_0002\r\nQuantity=time\r\nUnit=s\r\nQuantity=waterlevelbnd\r\nUnit=m\r\n0 0\r\n120 0\r\n')
    raw=('\ufeff# Generated on 2026-11-04 12:00:00\r\n# exact comment / 독립 synthetic fixture\r\n'
         '[General]\r\nPathsRelativeToParent = 0\r\n[geometry]\r\nNetFile = f34_net.nc\r\nThinDamFile = f34_thd.pli\r\nDryPointsFile = f34_drypoints_dry.xyz\r\nWaterLevIni = 1.9 # m, not water depth\r\n'
         '[physics]\r\nUnifFrictType = 0\r\nUnifFrictCoef = 65\r\n[time]\r\nTUnit = M\r\nDtMax = 30 # seconds regardless TUnit\r\n'
         '[external forcing]\r\nExtForceFileNew = f34_bnd.ext\r\n[output]\r\nObsFile = f34_obs.xyn\r\nCrsFile = f34_crs.pli\r\nHisFile = f34_his.nc\r\nMapFile = f34_map.nc\r\nHisInterval = 300\r\nMapInterval = 300\r\nStatistic = first\r\nStatistic = second\r\n')
    (root/'f34.mdu').write_bytes(raw.encode('utf-8'))


def change(root,before,after):
    path=root/'f34.mdu';raw=path.read_bytes();assert before in raw;path.write_bytes(raw.replace(before,after,1))


def spec(address='geometry/waterlevini',before='1.9',after='2.15',unit='m'):
    result={'schema_version':1,'purpose':'E014_GUI_field_export','operation':'scalar','mdu':'f34.mdu','address':address,'before':before,'after':after,'unit':unit}
    if address=='physics/uniffrictcoef':result['preconditions']={'physics/uniffricttype':'1'}
    return result


class RawFieldsProjectExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dfm-e014-gui-raw-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.control=self.root/'control';exported(self.control)
        self.changed=self.root/'changed';shutil.copytree(self.control,self.changed)

    def water(self):change(self.changed,b'WaterLevIni = 1.9',b'WaterLevIni = 2.15')

    def manning(self):
        seed=self.root/'intentional-manning-source';shutil.copytree(self.control,seed)
        change(seed,b'UnifFrictType = 0',b'UnifFrictType = 1');change(seed,b'UnifFrictCoef = 65',b'UnifFrictCoef = 0.023')
        control=self.root/'manning-control';edited=self.root/'manning-edited';shutil.copytree(seed,control);shutil.copytree(seed,edited)
        change(edited,b'UnifFrictCoef = 0.023',b'UnifFrictCoef = 0.041')
        return seed,control,edited

    def test_water_scalar_raw_graph_pass_not_runtime_or_science(self):
        self.water();before=inventory(self.control);edited=inventory(self.changed)
        result=compare_exports(self.control,self.changed,spec())
        self.assertEqual(result['actual_target']['after'],'2.15');self.assertEqual(result['non_MDU_files_byte_identical'],9)
        self.assertEqual(result['typed_owner_runtime_gate']['state'],'not_established');self.assertFalse(result['actual_guest_ready'])
        self.assertEqual(result['scientific_validation'],'not_performed');self.assertEqual(inventory(self.control),before);self.assertEqual(inventory(self.changed),edited)

    def test_dtmax_units_seconds_even_with_model_tunit_minutes(self):
        change(self.changed,b'DtMax = 30',b'DtMax = 15')
        result=compare_exports(self.control,self.changed,spec('time/dtmax','30','15','s'))
        self.assertEqual(result['actual_target']['unit'],'s')
        with self.assertRaisesRegex(ValueError,'unit'):compare_exports(self.control,self.changed,spec('time/dtmax','30','15','min'))

    def test_only_precise_first_generated_timestamp_span_may_vary(self):
        self.water();change(self.changed,b'2026-11-04 12:00:00',b'2026-11-04 12:01:05')
        self.assertEqual(compare_exports(self.control,self.changed,spec())['raw_export_difference_gate']['state'],'passed')
        change(self.changed,b'# exact comment',b'# exact comment changed')
        with self.assertRaisesRegex(ValueError,'comments/formatting'):compare_exports(self.control,self.changed,spec())

    def test_timestamp_or_comment_lines_cannot_hide_another_scalar(self):
        self.water();change(self.changed,b'2026-11-04 12:00:00',b'2026-11-04 13:00:00');change(self.changed,b'DtMax = 30',b'DtMax = 15')
        with self.assertRaisesRegex(ValueError,'Non-target MDU'):compare_exports(self.control,self.changed,spec())

    def test_generated_timestamp_suffix_payload_and_invalid_calendar_refuse(self):
        self.water();change(self.changed,b'12:00:00\r\n',b'12:00:01 HIDDEN\r\n')
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())
        change(self.changed,b'12:00:01 HIDDEN',b'12:00:01');change(self.changed,b'2026-11-04',b'2026-02-31')
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())

    def test_second_generated_on_comment_is_never_ignored(self):
        self.water();change(self.changed,b'# exact comment',b'# Generated on 2026-11-04 12:05:00 # exact comment')
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())

    def test_typing_success_readback_and_zero_exit_cannot_rescue_unchanged_export(self):
        owner={'success':True,'exit_code':0,'owner_type':'System.Double','before':1.9,'after':2.15,'unit':'m'}
        with self.assertRaisesRegex(ValueError,'Actual exported target'):compare_exports(self.control,self.changed,spec(),owner_evidence=owner)

    def test_p08_stamp_or_unowned_success_receipt_never_qualifies_E014(self):
        self.water()
        report=compare_exports(self.control,self.changed,spec(),owner_evidence={'kind':'P08_disposable_guest_export_only','marker':'P08_EXPORT_OK','success':True,'owner_verified':True})
        self.assertEqual(report['raw_export_difference_gate']['state'],'passed')
        self.assertEqual(report['typed_owner_runtime_gate']['state'],'not_established')
        self.assertEqual(report['overall_gui_mapping_gate'],'not_established_by_raw_disk_oracle_alone')

    def test_wrong_target_value_or_section_is_not_the_requested_mutation(self):
        change(self.changed,b'WaterLevIni = 1.9',b'WaterLevIni = 2.5')
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())
        change(self.changed,b'WaterLevIni = 2.5',b'WrongWaterLevIni = 2.15')
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())

    def test_repeated_non_target_setting_occurrences_and_order_are_preserved(self):
        self.water();result=compare_exports(self.control,self.changed,spec())
        entries=[e for e in records((self.changed/'f34.mdu').read_bytes()) if e['address']=='output/statistic']
        self.assertEqual([entry['value'] for entry in entries],['first','second'])
        change(self.changed,b'Statistic = first\r\nStatistic = second',b'Statistic = second\r\nStatistic = first')
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())

    def test_duplicate_target_ambiguous_not_last_wins(self):
        self.water();change(self.changed,b'WaterLevIni = 2.15 # m, not water depth',b'WaterLevIni = 2.15 # m, not water depth\r\nWaterLevIni = 1.9')
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())

    def test_nontarget_precision_comment_whitespace_or_newline_changes_refuse(self):
        self.water()
        for old,new in [(b'DtMax = 30',b'DtMax = 30.000'),(b'UnifFrictCoef = 65',b'UnifFrictCoef\t= 65')]:
            change(self.changed,old,new)
            with self.subTest(new=new),self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())
            change(self.changed,new,old)
        path=self.changed/'f34.mdu';path.write_bytes(path.read_bytes().replace(b'\r\n',b'\n'))
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())

    def test_linked_boundary_change_not_hidden_by_matching_file_names(self):
        self.water();path=self.changed/'f34_001.bc';path.write_bytes(path.read_bytes().replace(b'Unit=m',b'Unit=cm',1))
        with self.assertRaisesRegex(ValueError,'linked file bytes'):compare_exports(self.control,self.changed,spec())

    def test_extra_missing_or_same_added_file_in_both_graphs_refused(self):
        self.water();(self.control/'extra.txt').write_text('same');(self.changed/'extra.txt').write_text('same')
        with self.assertRaisesRegex(ValueError,'exactly'):compare_exports(self.control,self.changed,spec())
        (self.control/'extra.txt').unlink();(self.changed/'extra.txt').unlink();(self.changed/'f34_obs.xyn').unlink()
        with self.assertRaises(ValueError):compare_exports(self.control,self.changed,spec())

    def test_escaping_reference_fails_without_reading_external_target(self):
        change(self.control,b'NetFile = f34_net.nc',b'NetFile = ../outside.nc')
        with self.assertRaisesRegex(ValueError,'Escaping'):graph(self.control)

    def test_hardlink_alias_is_not_an_independent_control_copy(self):
        target=self.root/'outside.bin';target.write_bytes(b'fixture')
        path=self.changed/'f34_net.nc';path.unlink()
        try:path.hardlink_to(target)
        except OSError:self.skipTest('Fixture volume does not support hard links')
        with self.assertRaisesRegex(ValueError,'Hardlinked'):graph(self.changed)

    def test_no_change_control_allows_timestamp_but_not_model_mutation(self):
        declaration={'schema_version':1,'purpose':'E014_GUI_field_export','operation':'no_change','mdu':'f34.mdu'}
        change(self.changed,b'12:00:00',b'12:00:10')
        self.assertEqual(compare_exports(self.control,self.changed,declaration)['raw_export_difference_gate']['state'],'passed')
        self.water()
        with self.assertRaisesRegex(ValueError,'No-change'):compare_exports(self.control,self.changed,declaration)

    def test_natural_f34_chezy_never_accepts_manning_signature(self):
        change(self.changed,b'UnifFrictCoef = 65',b'UnifFrictCoef = 0.041')
        with self.assertRaisesRegex(ValueError,'Manning signature'):compare_exports(self.control,self.changed,spec('physics/uniffrictcoef','65','0.041','s m-1/3'))

    def test_law_change_during_single_coefficient_edit_is_refused(self):
        change(self.changed,b'UnifFrictType = 0',b'UnifFrictType = 1');change(self.changed,b'UnifFrictCoef = 65',b'UnifFrictCoef = 0.041')
        with self.assertRaisesRegex(ValueError,'Manning signature'):compare_exports(self.control,self.changed,spec('physics/uniffrictcoef','65','0.041','s m-1/3'))

    def test_matching_intentional_manning_source_and_control_required(self):
        seed,control,edited=self.manning();declaration=spec('physics/uniffrictcoef','0.023','0.041','s m-1/3')
        result=compare_exports(control,edited,declaration,manning_original=self.control,manning_source=seed)
        self.assertEqual(result['manning_source_control_gate']['law_after'],'1')
        self.assertEqual(result['actual_target']['before'],'0.023');self.assertEqual(result['actual_target']['after'],'0.041')
        self.assertEqual(result['typed_owner_runtime_gate']['state'],'not_established')

    def test_manning_source_missing_or_unrelated_source_mutation_refuses(self):
        seed,control,edited=self.manning();declaration=spec('physics/uniffrictcoef','0.023','0.041','s m-1/3')
        with self.assertRaisesRegex(ValueError,'preparation proof'):compare_exports(control,edited,declaration)
        change(seed,b'DtMax = 30',b'DtMax = 15')
        with self.assertRaisesRegex(ValueError,'unrelated bytes'):manning_seed(self.control,seed)

    def test_unrecognized_ignore_policy_and_composite_scalars_refuse(self):
        self.water();declaration=spec();declaration['ignore_comments']=True
        with self.assertRaisesRegex(ValueError,'ignore policy'):compare_exports(self.control,self.changed,declaration)
        for value in ('NaN','2.15 99','Infinity','２.１５'):
            declaration=spec(after=value)
            with self.subTest(value=value),self.assertRaises(ValueError):compare_exports(self.control,self.changed,declaration)

    def test_oracle_never_calls_any_process_boundary(self):
        self.water()
        with patch('subprocess.Popen',side_effect=AssertionError('host process forbidden')):
            self.assertTrue(compare_exports(self.control,self.changed,spec())['inputs_unchanged'])
            self.assertFalse(guest_readiness()['actual_guest_ready'])

    def tree(self):
        seed,_,_=self.manning();root=self.root/'raw-five-case-tree';root.mkdir()
        for phase in ('exported','reopened'):
            (root/'manning-prerequisite').mkdir(exist_ok=True);shutil.copytree(seed,root/'manning-prerequisite'/phase)
        for name in ('control','waterlevini','dtmax','manning-control','manning'):
            folder=root/'cases'/name;folder.mkdir(parents=True)
            phases=['before','after','reopened']+(['rejected','noop'] if name=='control' else [])
            for phase in phases:
                source=seed if name.startswith('manning') else self.control;target=folder/phase;shutil.copytree(source,target)
                if phase in ('after','reopened'):
                    if name=='waterlevini':change(target,b'WaterLevIni = 1.9',b'WaterLevIni = 2.4')
                    elif name=='dtmax':change(target,b'DtMax = 30',b'DtMax = 15')
                    elif name=='manning':change(target,b'UnifFrictCoef = 0.023',b'UnifFrictCoef = 0.041')
        return seed,root

    def test_whole_tree_compares_against_independent_control_not_only_own_before(self):
        seed,root=self.tree();result=audit_export_tree(root,manning_original=self.control,manning_source=seed)
        self.assertEqual(result['raw_export_tree_gate'],'passed');self.assertEqual(len(result['comparisons']),17)
        self.assertFalse(result['actual_guest_ready'])

    def test_collateral_mutation_in_both_edited_before_and_after_cannot_hide(self):
        seed,root=self.tree()
        for phase in ('before','after','reopened'):change(root/'cases/waterlevini'/phase,b'DtMax = 30',b'DtMax = 15')
        with self.assertRaisesRegex(ValueError,'No-change'):audit_export_tree(root,manning_original=self.control,manning_source=seed)

    def test_actual_reopened_manning_law_must_already_be_one(self):
        seed,root=self.tree();change(root/'manning-prerequisite/reopened',b'UnifFrictType = 1',b'UnifFrictType = 0')
        with self.assertRaisesRegex(ValueError,'prerequisite'):audit_export_tree(root,manning_original=self.control,manning_source=seed)


class FieldsGuestReadinessTests(unittest.TestCase):
    def test_no_guest_descriptor_is_not_actual_readiness(self):
        result=guest_readiness();self.assertEqual(result['state'],'not_ready');self.assertFalse(result['actual_guest_ready']);self.assertFalse(result['host_launch_permitted'])

    def test_prepared_identity_pending_bundle_and_claimed_success_do_not_enable_host(self):
        with tempfile.TemporaryDirectory(prefix='dfm-fields-guest-') as temp:
            root=Path(temp);(root/'payload.py').write_text('# never executed\n')
            record={'kind':'P08_disposable_guest_export_only','files':inventory(root),'target_identity':None,'guest_identity_pending':True,'claimed_ready':True}
            path=root/'bundle.json';path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'standalone E014 kind'):guest_readiness(root,sha(path))
            (root/'payload.py').write_text('# tampered\n')
            with self.assertRaisesRegex(ValueError,'standalone E014 kind'):guest_readiness(root,sha(path))

    def test_installed_text_schema_is_not_a_live_typed_owner(self):
        with tempfile.TemporaryDirectory(prefix='dfm-fields-csv-') as temp:
            path=Path(temp)/SCHEMA_PATH;path.parent.mkdir(parents=True)
            raw='MduGroup,MduName,Type,MduOnly,Unit\ngeometry,WaterLevIni,Double,FALSE,m\ntime,DtMax,Double,FALSE,s\nphysics,UnifFrictCoef,Double,FALSE,UnifFrictType: m(1/2)/s | s/m(1/3) | m\n'
            path.write_text(raw)
            result=installed_schema(temp);self.assertEqual(result['state'],'observed_static_schema_only');self.assertFalse(result['assemblies_loaded'])
            path.write_text(raw.replace('DtMax,Double','DtMax,TimeSpan'))
            with self.assertRaisesRegex(ValueError,'type/unit'):installed_schema(temp)


if __name__=='__main__':unittest.main()
