"""Independent installed G15 I1 public file tests; no candidate parser as oracle.

Invoke from this private directory using a clean interpreter that only imports
the installed candidate in the guarded public child. Each test uses a fresh case.
Public bundle serialization must be prospectively frozen/confirmed before run.
"""
import argparse
import json
import os
from pathlib import Path
import unittest

from public_support import Case,Public,PRE,save
from bundle_fixtures import create_geometry,create_hydraulic,write_json,reseal
from raw_oracle import snapshot,require_exact,public_snapshot
from win_file_acl import observe,public as public_acl,set_protected

HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
p.add_argument('--python',type=Path,required=True)
p.add_argument('--installed-root',type=Path,required=True)
p.add_argument('--out-name',required=True)
p.add_argument('--base-schema',type=Path,help='Independent actual accepted191 schema result, for exact preservation comparison')
p.add_argument('--only',action='append')
a=p.parse_args()
OUT=HERE/a.out_name
assert OUT.resolve().is_relative_to(HERE)
OUT.mkdir(exist_ok=False)
CLI=Public(a.python,a.installed_root,OUT)
COUNT=0
FACTS=[]

class PublicTransfer(unittest.TestCase):
    def case(self,**kw):
        global COUNT
        COUNT+=1
        return Case(OUT,f'{COUNT:03d}-{self._testMethodName}',**kw)

    def unchanged(self,c,before):
        require_exact(before,snapshot(c.model))

    def preview(self,c,argv):
        before=snapshot(c.model)
        result=CLI.call(argv)
        self.unchanged(c,before)
        self.assertIsInstance(result['input_sha256'],str)
        self.assertEqual(len(result['input_sha256']),64)
        return result,before

    def test_geometry_replace_exact_untouched_full_graph(self):
        c=self.case();create_geometry(c)
        argv=c.geometry_import_args();r,before=self.preview(c,argv)
        CLI.apply(argv,r)
        expected=(PRE/'literal-expected/geometry-replace.pli').read_bytes()
        require_exact(before,snapshot(c.model),{'target-weir.pli':expected})

    def test_schema_commands_parameters_and_all16_scopes(self):
        result=CLI.call(['schema','inspect'])
        for command in ('structure inspect','structure export','structure import'):
            self.assertIn(command,result['commands'])
            self.assertIn(command,result['command_parameters'])
        params=result['command_parameters']['structure import']
        options={o:p for p in params for o in p['options']}
        for name in ('--id','--all','--source','--representation','--mode','--coordinates','--xy-unit','--height-unit','--vertical-datum','--target-structure-file','--asset-map','--apply','--expect-sha256'):
            self.assertIn(name,options)
        self.assertTrue(options['--id'].get('repeatable'))
        rows=[]
        def visit(x):
            if isinstance(x,list):
                if len(x)==16 and all(isinstance(r,dict) and 'id' in r for r in x):rows.append(x)
                for v in x:visit(v)
            elif isinstance(x,dict):
                for v in x.values():visit(v)
        visit(result)
        expected=[r['id'] for r in json.loads((PRE/'accepted-contract/coverage.json').read_bytes())['rows']]
        self.assertTrue(any([r['id'] for r in x]==expected for x in rows),'All16 structured scope rows required, not a vague complete G15 claim')
        if a.base_schema:
            baseline=json.loads(a.base_schema.read_bytes());baseline=baseline.get('result',baseline)
            for name,parameters in baseline['command_parameters'].items():
                self.assertEqual(result['command_parameters'][name],parameters,name)
            self.assertEqual(set(result['commands'])-set(baseline['commands']),{'structure inspect','structure export','structure import'})

    def test_inspect_binds_complete_real_input_inventory(self):
        for label in ('real-pump','real-weir'):
            c=self.case(target=label);before=snapshot(c.model)
            r=CLI.call(['structure','inspect',str(c.mdu)])
            records=[]
            def visit(x):
                if isinstance(x,dict):
                    if {'path','sha256','bytes'}<=x.keys():records.append(x)
                    for v in x.values():visit(v)
                elif isinstance(x,list):
                    for v in x:visit(v)
            visit(r)
            by_path={str(Path(x['path']).resolve()):x for x in records}
            for name,expected in before.items():
                found=by_path.get(str((c.model/name).resolve()))
                self.assertIsNotNone(found,('Missing actual connected input from reported graph',label,name))
                self.assertEqual(found['sha256'],expected['sha256']);self.assertEqual(found['bytes'],expected['bytes'])
            self.unchanged(c,before)

    def test_hydraulic_replace_literal_core_and_paths(self):
        c=self.case();create_hydraulic(c)
        argv=c.hydraulic_import_args('--id','W_Main');r,before=self.preview(c,argv)
        CLI.apply(argv,r)
        expected=(PRE/'literal-expected/hydraulic-replace-structures.ini').read_bytes()
        require_exact(before,snapshot(c.model),{'structures.ini':expected})

    def test_hydraulic_append_literal_before_footer(self):
        c=self.case();create_hydraulic(c,new_id='W_New')
        argv=c.hydraulic_import_args('--id','W_New',mode='append');r,before=self.preview(c,argv)
        CLI.apply(argv,r)
        expected=(PRE/'literal-expected/hydraulic-append-structures.ini').read_bytes()
        require_exact(before,snapshot(c.model),{'structures.ini':expected})

    def test_noop_keeps_inode_mtime_and_complete_graph(self):
        c=self.case();create_geometry(c,raw=(c.model/'target-weir.pli').read_bytes())
        argv=c.geometry_import_args();r,before=self.preview(c,argv)
        CLI.apply(argv,r);self.unchanged(c,before)

    def test_real_complete_model_export_geometry(self):
        for label,id,child in (('real-pump','transfer_pump','pump.pli'),('real-weir','blocking_weir','blocking_weir.pli')):
            c=self.case(target=label);before=snapshot(c.model)
            argv=c.export_args('--id',id,representation='geometry')
            r=CLI.call(argv);self.assertFalse(c.export_path.exists());self.unchanged(c,before)
            CLI.apply(argv,r);self.unchanged(c,before)
            index=json.loads((c.export_path/'geometry.json').read_bytes())
            self.assertEqual(index['format'],'dfm-structure-geometry-v1')
            self.assertEqual(len(index['routes']),1)
            route=index['routes'][0];self.assertEqual(route['route_id'],id)
            self.assertEqual((c.export_path/route['asset_path']).read_bytes(),(c.model/child).read_bytes())
            self.assertEqual({p.relative_to(c.export_path).as_posix() for p in c.export_path.rglob('*') if p.is_file()}, {'geometry.json',route['asset_path']})

    def test_literal_selected_hydraulic_export_projection(self):
        c=self.case();before=snapshot(c.original_source)
        argv=c.export_args('--id','W_Main',source=True)
        r=CLI.call(argv);self.assertFalse(c.export_path.exists());CLI.apply(argv,r)
        require_exact(before,snapshot(c.original_source))
        index=json.loads((c.export_path/'bundle.json').read_bytes())
        self.assertEqual(index['format'],'dfm-structure-bundle-v1')
        expected=(PRE/'literal-expected/export-selected-structures.ini').read_bytes()
        self.assertEqual((c.export_path/index['structure_path']).read_bytes(),expected)
        for raw in ((PRE/'literal-expected/geometry-replace.pli').read_bytes(),(PRE/'literal-expected/native-minute-crest.tim').read_bytes()):
            self.assertIn(raw,[(c.export_path/x['path']).read_bytes() for x in index['assets']])
        self.assertEqual((c.export_path/index['context_path']).read_bytes(),(c.original_source/'model.mdu').read_bytes())

    def test_literal_all_export_order_and_no_concatenated_geometry(self):
        c=self.case()
        argv=c.export_args('--all',source=True);r,_=self.preview(c,argv);CLI.apply(argv,r)
        index=json.loads((c.export_path/'bundle.json').read_bytes())
        self.assertEqual((c.export_path/index['structure_path']).read_bytes(),(PRE/'literal-expected/export-all-structures.ini').read_bytes())
        self.assertEqual({x['path'] for x in index['assets']},{'payload/source-weir.pli','payload/source.tim','payload/source-pump.pli'})
        c=self.case();argv=c.export_args('--all',source=True,representation='geometry');r=CLI.call(argv);CLI.apply(argv,r)
        index=json.loads((c.export_path/'geometry.json').read_bytes())
        self.assertEqual(index['routes'],[{'route_id':'W_Main','asset_path':'assets/0001.pli'},{'route_id':'P_Keep','asset_path':'assets/0002.pli'}])
        self.assertEqual((c.export_path/'assets/0001.pli').read_bytes(),(c.original_source/'source-weir.pli').read_bytes())
        self.assertEqual((c.export_path/'assets/0002.pli').read_bytes(),(c.original_source/'source-pump.pli').read_bytes())

    def test_existing_export_never_overwrites_even_same_bytes(self):
        for kind in ('dir','file'):
            c=self.case()
            if kind=='dir':c.export_path.mkdir();(c.export_path/'foreign').write_bytes(b'foreign')
            else:c.export_path.write_bytes(b'foreign')
            before=snapshot(c.model);external=snapshot(c.external)
            CLI.call(c.export_args('--id','W_Main',representation='geometry'),expected=4)
            self.unchanged(c,before);require_exact(external,snapshot(c.external))

    def test_usage_JSON_missing_and_conflicting_arguments(self):
        c=self.case();create_geometry(c)
        valid=c.geometry_import_args()
        variants=[
            ['structure','export',str(c.mdu),'--representation','geometry','--out',str(c.export_path)],
            [*valid,'--all'],[*valid,'--id','W_Main'],
            [*valid,'--apply'],
            [x for i,x in enumerate(valid) if i not in (valid.index('--xy-unit'),valid.index('--xy-unit')+1)],
        ]
        for argv in variants:
            before=snapshot(c.model);CLI.call(argv,expected=2);self.unchanged(c,before)

    def test_geometry_operator_route_not_PLI_identity(self):
        for route in ('P_Keep','w_main','Missing'):
            c=self.case();create_geometry(c,route=route);before=snapshot(c.model)
            CLI.call(c.geometry_import_args(),expected=(3,4));self.unchanged(c,before)

    def test_geometry_untrusted_routing_fields(self):
        for key,value in (('verified_id','W_Main'),('passed',True),('source_type','weir')):
            c=self.case();create_geometry(c);p=c.source_bundle/'geometry.json'
            d=json.loads(p.read_bytes());d[key]=value;write_json(p,d);before=snapshot(c.model)
            CLI.call(c.geometry_import_args(),expected=3);self.unchanged(c,before)

    def test_geometry_duplicate_json_keys_and_casefold_routes(self):
        for raw in (
            b'{"format":"dfm-structure-geometry-v1","format":"dfm-structure-geometry-v1","routes":[]}',
            b'{"format":"dfm-structure-geometry-v1","routes":[{"route_id":"W_Main","asset_path":"assets/location.pli"},{"route_id":"w_main","asset_path":"assets/location.pli"}]}',
        ):
            c=self.case();create_geometry(c);(c.source_bundle/'geometry.json').write_bytes(raw);before=snapshot(c.model)
            CLI.call(c.geometry_import_args(),expected=3);self.unchanged(c,before)

    def test_hydraulic_content_not_hash_or_index_authority(self):
        for mutation in ('wrongID','unknownField','branchLocation','missingCrest','BC','REALTIME','numericPrefix','nonfinite'):
            c=self.case();create_hydraulic(c);ini=c.source_bundle/'payload/structures.ini';raw=ini.read_bytes()
            if mutation=='wrongID':raw=raw.replace(b'id = W_Main',b'id = Different')
            elif mutation=='unknownField':raw+=b'FutureControl = W_Main\r\n'
            elif mutation=='branchLocation':raw+=b'branchId = B1\r\nchainage = 1\r\n'
            elif mutation=='missingCrest':raw=raw.replace(b'crestLevel = source.tim\r\n',b'')
            else:
                v={'BC':b'source.bc','REALTIME':b'REALTIME','numericPrefix':b'1 source.tim','nonfinite':b'NaN'}[mutation]
                raw=raw.replace(b'crestLevel = source.tim',b'crestLevel = '+v)
            ini.write_bytes(raw);reseal(c.source_bundle);before=snapshot(c.model)
            CLI.call(c.hydraulic_import_args('--id','W_Main'),expected=(3,4));self.unchanged(c,before)

    def test_clock_and_TIM_order_coverage_raw_failures(self):
        values=[b'0 0.2\n0 0.8\n2 0.3\n',b'1 0.2\n0 0.8\n2 0.3\n',b'0 0.2\n1 0.8\n',b'0 NaN\n2 0.3\n']
        for raw in values:
            c=self.case();create_hydraulic(c);(c.source_bundle/'payload/source.tim').write_bytes(raw);reseal(c.source_bundle)
            # Map equal bytes too: failure must be clock/content, not byte mismatch.
            (c.model/'mapped-crest.tim').write_bytes(raw);before=snapshot(c.model)
            CLI.call(c.hydraulic_import_args('--id','W_Main'),expected=3);self.unchanged(c,before)
        for field,old,new in (('origin',b'RefDate = 20010101',b'RefDate = 20010102'),('zone',b'TZone = 0',b'TZone = 1')):
            c=self.case();create_hydraulic(c);p=c.source_bundle/'context/source.mdu';p.write_bytes(p.read_bytes().replace(old,new));reseal(c.source_bundle)
            before=snapshot(c.model);CLI.call(c.hydraulic_import_args('--id','W_Main'),expected=3);self.unchanged(c,before)

    def test_actual_mapped_asset_difference_and_wrong_path(self):
        for mutation in ('bytes','missing','role','extra'):
            c=self.case();create_hydraulic(c)
            if mutation=='bytes':(c.model/'mapped-source.pli').write_bytes(b'Altered\n2 2\n11 0\n11 10\n')
            elif mutation=='missing':(c.model/'mapped-source.pli').unlink()
            else:
                d=json.loads(c.asset_map.read_bytes())
                if mutation=='role':d['assets'][0]['target_path']='mapped-crest.tim'
                else:d['assets'].append({'source_path':'context/source.mdu','target_path':'model.mdu'})
                write_json(c.asset_map,d)
            before=snapshot(c.model);CLI.call(c.hydraulic_import_args('--id','W_Main'),expected=(3,4));self.unchanged(c,before)

    def test_unselected_complete_graph_unknown_extensionless_consumers(self):
        for location,line in (
            ('structures.ini',b'\r\n[Structure]\r\nid=Controller\r\ntype=futureController\r\ncontrolTarget=W_Main\r\n'),
            ('model.mdu',b'\r\n[future]\r\nControlTarget = W_Main\r\n'),
            ('boundaries.ext',b'\n[FutureLink]\nNativeReceiver = W_Main\nNested = external_table\n'),
        ):
            c=self.case();create_geometry(c);p=c.model/location;p.write_bytes(p.read_bytes()+line)
            before=snapshot(c.model);CLI.call(c.geometry_import_args(),expected=3);self.unchanged(c,before)

    def test_unknown_nested_container_or_reference_must_not_be_leaf(self):
        for setting,value in (('FutureFile','unknown.ini'),('Alias','nested.tbl'),('Receiver','extensionless_control')):
            c=self.case();create_geometry(c)
            p=c.model/'model.mdu';p.write_bytes(p.read_bytes()+f'\r\n[unselected]\r\n{setting} = {value}\r\n'.encode())
            (c.model/value).write_bytes(b'[Control]\nTarget=W_Main\nFurther=not_in_model\n')
            before=snapshot(c.model);CLI.call(c.geometry_import_args(),expected=3);self.unchanged(c,before)

    def test_compound_and_unknown_numeric_ID_consumer_controls(self):
        # First establish that numeric native ID itself is an admitted string,
        # then demonstrate both known and unknown incoming consumer grammars.
        for consumer in ('none','compound','unknown'):
            c=self.case();create_geometry(c,route='7')
            p=c.model/'structures.ini';p.write_bytes(p.read_bytes().replace(b'id = W_Main\r\n',b'id = 7\r\n'))
            if consumer=='compound':
                p.write_bytes(p.read_bytes()+b'\r\n[Structure]\r\nid=Group\r\ntype=compound\r\nnumStructures=1\r\nstructureIds=7\r\n')
            if consumer=='unknown':
                p=c.model/'model.mdu';p.write_bytes(p.read_bytes()+b'\r\n[future]\r\nControlTarget = 7\r\n')
            before=snapshot(c.model)
            CLI.call(c.geometry_import_args(id='7'),expected=0 if consumer=='none' else 3)
            self.unchanged(c,before)

    def test_shared_location_across_true_roles_refused(self):
        for role in ('structure','section','boundary'):
            c=self.case();create_geometry(c)
            if role=='structure':
                p=c.model/'structures.ini';p.write_bytes(p.read_bytes().replace(b'locationFile = target-pump.pli',b'locationFile = target-weir.pli'))
            elif role=='section':
                p=c.model/'model.mdu';p.write_bytes(p.read_bytes().replace(b'CrsFile = fixed_sections.pli',b'CrsFile = target-weir.pli'))
            else:
                p=c.model/'boundaries.ext';p.write_bytes(p.read_bytes().replace(b'boundary_west.pli',b'target-weir.pli'))
            before=snapshot(c.model);CLI.call(c.geometry_import_args(),expected=3);self.unchanged(c,before)

    def test_original_whitespace_counterpath_no_quoted_bypass(self):
        for value in ('structure file.ini','"structures.ini"','structures.ini;other.ini'):
            c=self.case();create_geometry(c);p=c.model/'model.mdu'
            p.write_bytes(p.read_bytes().replace(b'StructureFile = structures.ini',b'StructureFile = '+value.encode()))
            before=snapshot(c.model);CLI.call(c.geometry_import_args(),expected=3);self.unchanged(c,before)

    def test_no_G18_missing_X_or_multiblock_semantics(self):
        # Finite -999 is a legitimate XY value in this modern reader policy.
        c=self.case();create_geometry(c,raw=b'Not_ID\n2 2\n-999 0\n-999 10\n')
        argv=c.geometry_import_args();r,before=self.preview(c,argv);CLI.apply(argv,r)
        require_exact(before,snapshot(c.model),{'target-weir.pli':b'Not_ID\n2 2\n-999 0\n-999 10\n'})
        for raw in (b'A\n2 2\n10 0\n10 10\nB\n2 2\n20 0\n20 10\n',b'A\n2 3\n10 0 1\n10 10 2\n'):
            c=self.case();create_geometry(c,raw=raw);before=snapshot(c.model)
            CLI.call(c.geometry_import_args(),expected=3);self.unchanged(c,before)

    def test_stale_unselected_full_inputs_and_map(self):
        for path in ('boundaries.bc','observations.xyn','fixed_sections.pli','mesh_net.nc','structures.ini','mapped-source.pli','asset-map'):
            c=self.case();create_hydraulic(c);argv=c.hydraulic_import_args('--id','W_Main');r,_=self.preview(c,argv)
            p=c.asset_map if path=='asset-map' else c.model/path
            p.write_bytes(p.read_bytes()+(b'\n \t\n' if path=='asset-map' else b'\n# independent late change\n'))
            before=snapshot(c.model);CLI.call([*argv,'--apply','--expect-sha256',r['input_sha256']],expected=4);self.unchanged(c,before)

    def test_same_bytes_replaced_file_identity_is_stale(self):
        for path in ('target-weir.pli','mesh_net.nc','boundaries.bc','source-asset'):
            c=self.case();create_geometry(c);argv=c.geometry_import_args();r,_=self.preview(c,argv)
            p=c.source_bundle/'assets/location.pli' if path=='source-asset' else c.model/path
            original=p.stat().st_ino;fresh=c.external/'replacement-object';fresh.write_bytes(p.read_bytes());os.replace(fresh,p)
            self.assertNotEqual(p.stat().st_ino,original,'Fixture must genuinely replace original object')
            before=snapshot(c.model);CLI.call([*argv,'--apply','--expect-sha256',r['input_sha256']],expected=4);self.unchanged(c,before)

    def test_request_and_routing_hash_bound(self):
        c=self.case();create_geometry(c);argv=c.geometry_import_args();r,before=self.preview(c,argv)
        changed=[*argv];changed[changed.index('--id')+1]='P_Keep'
        CLI.call([*changed,'--apply','--expect-sha256',r['input_sha256']],expected=(3,4));self.unchanged(c,before)

    def test_real_protected_target_and_late_DACL(self):
        c=self.case();create_geometry(c);target=c.model/'target-weir.pli';original=observe(target)
        try:
            set_protected(target,original,fixture_root=HERE,protected=True)
            before=snapshot(c.model);CLI.call(c.geometry_import_args(),expected=(3,4));self.unchanged(c,before)
        finally:set_protected(target,original,fixture_root=HERE,protected=False)
        argv=c.geometry_import_args();r,_=self.preview(c,argv)
        try:
            protected=set_protected(target,original,fixture_root=HERE,protected=True);before=snapshot(c.model)
            CLI.call([*argv,'--apply','--expect-sha256',r['input_sha256']],expected=4);self.unchanged(c,before)
        finally:restored=set_protected(target,original,fixture_root=HERE,protected=False)
        self.assertEqual(restored['sddl'],original['sddl'])
        FACTS.append({'case':str(c.root),'original':public_acl(original),'protected':public_acl(protected),'restored':public_acl(restored)})

    def test_real_inherited_ACL_survives_success(self):
        c=self.case();create_geometry(c);target=c.model/'target-weir.pli'
        before_acl=observe(target);self.assertFalse(before_acl['protected_dacl'])
        argv=c.geometry_import_args();r,before=self.preview(c,argv);CLI.apply(argv,r)
        after_acl=observe(target)
        self.assertEqual(before_acl['sddl'],after_acl['sddl'])
        require_exact(before,snapshot(c.model),{'target-weir.pli':(PRE/'literal-expected/geometry-replace.pli').read_bytes()})
        FACTS.append({'case':str(c.root),'ordinary_inherited_before':public_acl(before_acl),'after':public_acl(after_acl)})

    def test_real_readonly_target_no_staging_or_byte_loss(self):
        import stat
        c=self.case();create_geometry(c);target=c.model/'target-weir.pli';mode=target.stat().st_mode
        try:
            target.chmod(mode & ~stat.S_IWRITE)
            before=snapshot(c.model);CLI.call(c.geometry_import_args(),expected=(3,4));self.unchanged(c,before)
        finally:target.chmod(mode)

    def test_late_actual_parent_DACL_is_bound(self):
        c=self.case();create_geometry(c);original=observe(c.model)
        argv=c.geometry_import_args();r,_=self.preview(c,argv)
        try:
            protected=set_protected(c.model,original,fixture_root=HERE,protected=True)
            before=snapshot(c.model)
            CLI.call([*argv,'--apply','--expect-sha256',r['input_sha256']],expected=4);self.unchanged(c,before)
        finally:restored=set_protected(c.model,original,fixture_root=HERE,protected=False)
        self.assertEqual(restored['sddl'],original['sddl'])
        FACTS.append({'case':str(c.root),'parent_original':public_acl(original),'parent_late':public_acl(protected),'parent_restored':public_acl(restored)})

suite=unittest.defaultTestLoader.loadTestsFromTestCase(PublicTransfer)
if a.only:
    names=set(a.only);suite=unittest.TestSuite(t for t in suite if t._testMethodName in names)
    assert suite.countTestCases()==len(names)
result=unittest.TextTestRunner(verbosity=2).run(suite)
CLI.finish({'state':'passed' if result.wasSuccessful() else 'FAILED_RETAINED',
 'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
 'native_started':False,'GUI_started':False,'expected_native_bytes_from_independent_literals':True,
 'full_graph_cases_not_only_author_fixture':True,'ACL_facts':FACTS,
 'candidate_implementation_read_for_expectations':False,
 'scope':'I1 installed file commands only; publication fault suite and all16 deferred scopes separate; no fullG15/native/GUI acceptance'})
raise SystemExit(0 if result.wasSuccessful() else 1)
