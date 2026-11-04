"""Independent public model-set O03/O04 tests and optional retained f34 replay.

Portable: python -B -m unittest tests.test_output_toggle_edits -v
Real input copies only: python -B -m tests.test_output_toggle_edits --real-replay
  --source ORIGINAL_TEN_FILES --native-controls RETAINED_I_ROOT --out NEW
No engine, GUI, VM or native slot is used. Expected edits use independent byte
spans and hashlib, never production parsers/editors or field-set eligibility.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli.cli import main as public_main

ADDRESSES=('output/wrishp_obs','output/wrihis_balance')
POINTER={'command':'model set','apply_hash':'before_sha256','hash_scope':'MDU bytes'}
INVALID_NEW=('', '00','01','10','2','-1','-0','+0','+1','0.0','1.0','1.','1e0','0e0',
    'NaN','Infinity','-Infinity','true','True','False','on','off','yes','no','0x1','1_0',
    '0 1','0 0 600','1,0','0;1','１','０','١','٠',' 1','1 ','\t0','0\t','1\n','0\r\n','1 #new','1\x00')
INVALID_OLD=('', '00','01','10','2','-1','-0','+0','+1','0.0','1.0','1e0','NaN','Infinity',
    'True','False','on','off','0x1','1_0','0 1','0 0 600','1,0','0;1','１','٠','1\x00')


def sha_bytes(data):return hashlib.sha256(data).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix():sha_bytes(p.read_bytes()) for p in sorted(Path(root).rglob('*')) if p.is_file()}


def expected_edit(raw,address,value):
    """Independent byte oracle: resolve one explicit section/key occurrence."""
    section,key=address.casefold().split('/');current='';offset=0;matches=[]
    for line in raw.splitlines(keepends=True):
        content=line;prefix=0
        if offset==0 and content.startswith(b'\xef\xbb\xbf'):content=content[3:];prefix=3
        code=content.split(b'#',1)[0].rstrip(b'\r\n')
        header=re.fullmatch(rb'[ \t]*\[([^]]+)\][ \t]*',code)
        if header:current=header[1].decode('utf-8').strip().casefold()
        elif b'=' in code and current==section:
            left,right=code.split(b'=',1)
            if left.decode('utf-8').strip().casefold()==key:
                token=right.strip();start=offset+prefix+len(left)+1+len(right)-len(right.lstrip())
                matches.append((start,start+len(token),token))
        offset+=len(line)
    if len(matches)!=1:raise ValueError('Independent target is missing or ambiguous')
    start,end,old=matches[0]
    if old not in (b'0',b'1') or value not in ('0','1'):raise ValueError('Independent binary contract requires exact ASCII0/1')
    return raw[:start]+value.encode('ascii')+raw[end:]


def fixture(*,shape='0',balance='1',bom=True,eol='\r\n'):
    lines=['# 한글 bytes preserved; comments are not a value oracle','[general]','PathsRelativeToParent = 0',
        '[geometry]','NetFile = mesh.nc','[time]','RefDate = 20010101','TUnit = M','TZone = 0','DtUser = 30',
        'StartDateTime = 20010101000000','StopDateTime = 20010101000200','[output]',
        '  WriShp_obs\t =  '+shape+'\t  # keep this exact comment',
        'Wrihis_balance = '+balance+' # another comment','HisInterval = 60.0000 # seconds',
        'MapInterval = 60 0 120','RstInterval = 0','Mystery = 1.234567890123456789',
        '[custom]','Tag = first','[custom]','Tag = second','',]
    return (b'\xef\xbb\xbf' if bom else b'')+eol.join(lines).encode('utf-8')


class PublicCLI:
    def __init__(self,out=None):self.out=out;self.counter=0
    def call(self,args,label='call'):
        args=[str(a) for a in args];stdout=io.StringIO();stderr=io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):code=public_main(args)
        text=stdout.getvalue();decoder=json.JSONDecoder();payload,end=decoder.raw_decode(text.strip())
        if text.strip()[end:]:raise AssertionError('Public stdout contains more than one JSON object')
        if payload.get('protocol_version')!=2:raise AssertionError('Public JSON protocol changed')
        if payload.get('ok') is not (code==0):raise AssertionError('Public exit/ok mismatch')
        if self.out is not None:
            self.counter+=1;prefix=f'{self.counter:02d}-{label}'
            (self.out/(prefix+'.stdout.json')).write_text(text,encoding='utf-8')
            (self.out/(prefix+'.stderr.txt')).write_text(stderr.getvalue(),encoding='utf-8')
            (self.out/(prefix+'.argv.json')).write_text(json.dumps({'entrypoint':'dfm_cli.cli.main','argv':args,'exit_code':code},indent=2),encoding='utf-8')
        return code,payload,stderr.getvalue()


class PublicOutputToggleEditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dfm-output-toggle-public-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.mdu=self.root/'input with spaces'/'flow.mdu';self.mdu.parent.mkdir()
        self.mdu.write_bytes(fixture());(self.mdu.parent/'mesh.nc').write_bytes(b'opaque portable sentinel; never a native model')
        (self.mdu.parent/'untouched.bc').write_bytes(b'[Forcing]\r\nQuantity=time\r\nQuantity=waterlevelbnd\r\n')
        self.cli=PublicCLI();guard=patch('subprocess.Popen',side_effect=AssertionError('No process may launch from model-set portable tests'))
        guard.start();self.addCleanup(guard.stop)

    def call(self,args):
        code,payload,stderr=self.cli.call(args);self.assertEqual(stderr,'');return code,payload

    def edit(self,address,value,*,apply=False,expected=None):
        args=['model','set',self.mdu,address,value]
        if apply:args.append('--apply')
        if expected is not None:args+=['--expect-sha256',expected]
        return self.call(args)

    def refuse(self,address,value,*,apply=False,expected=None,error=None):
        before=inventory(self.root);code,payload=self.edit(address,value,apply=apply,expected=expected)
        self.assertIn(code,(2,3,4),payload);self.assertFalse(payload['ok']);self.assertNotIn(payload['error']['code'],('internal_error','unsupported_edit','invalid_date'))
        self.assertTrue(payload['error']['message'])
        if error:self.assertEqual(payload['error']['code'],error)
        self.assertEqual(inventory(self.root),before);return code,payload

    def apply(self,address,value):
        raw=self.mdu.read_bytes();expected=expected_edit(raw,address,value);before=inventory(self.root)
        code,preview=self.edit(address,value);self.assertEqual(code,0,preview);r=preview['result']
        self.assertIs(r['applied'],False);self.assertEqual(r['before_sha256'],sha_bytes(raw));self.assertEqual(r['after_sha256'],sha_bytes(expected))
        self.assertEqual(r['before'],'0' if expected_edit(raw,address,'0')==raw else '1');self.assertEqual(r['after'],value)
        self.assertEqual(inventory(self.root),before);self.assertEqual(r['setting'],address.casefold())
        code,result=self.edit(address,value,apply=True,expected=r['before_sha256']);self.assertEqual(code,0,result)
        self.assertIs(result['result']['applied'],True);self.assertEqual(self.mdu.read_bytes(),expected)
        wanted=dict(before);wanted['input with spaces/flow.mdu']=sha_bytes(expected);self.assertEqual(inventory(self.root),wanted)
        return preview,result

    def test_schema_discovers_exact_ASCII_values_in_model_set_and_not_field_set(self):
        before=inventory(self.root);code,payload=self.call(['schema','inspect']);self.assertEqual(code,0)
        schema=payload['result'];self.assertIn('model set',schema['commands'])
        for address in ADDRESSES:
            self.assertIn(address,schema['editable_settings']);entry=schema['editable_settings'][address]
            self.assertEqual(entry['allowed_values'],['0','1']);self.assertIn('existing',entry['scope'].casefold())
            self.assertIn('ASCII',entry['type']);self.assertNotIn(address,schema['field_edits']['fields'])
        parameters=schema['command_parameters']['model set'];self.assertIn('--apply',{o for p in parameters for o in p['options']})
        self.assertEqual(inventory(self.root),before)

    def test_both_switches_both_directions_preview_hash_apply_and_byte_preservation(self):
        for address in ADDRESSES:
            for old,value in (('0','1'),('1','0')):
                with self.subTest(address=address,old=old,value=value):
                    self.mdu.write_bytes(fixture(shape=old,balance=old));self.apply(address,value)

    def test_same_value_noop_preserves_exact_hash_and_bytes(self):
        for address in ADDRESSES:
            for value in ('0','1'):
                self.mdu.write_bytes(fixture(shape=value,balance=value))
                with self.subTest(address=address,value=value):
                    preview,applied=self.apply(address,value)
                    self.assertEqual(preview['result']['before_sha256'],preview['result']['after_sha256']);self.assertEqual(preview['result']['diff'],'')

    def test_BOM_CRLF_LF_last_line_no_newline_and_case_insensitive_addresses(self):
        for bom,eol in ((True,'\r\n'),(False,'\r\n'),(False,'\n')):
            self.mdu.write_bytes(fixture(bom=bom,eol=eol).rstrip(b'\r\n'))
            with self.subTest(bom=bom,eol=eol):self.apply('OUTPUT/WriShp_OBS','1')

    def test_unrelated_repeated_keys_and_sections_are_preserved_and_allowed(self):
        raw=fixture()+b'[another]\r\nTag = A\r\n[another]\r\nTag = B\r\n'
        for address,value in ((ADDRESSES[0],'1'),(ADDRESSES[1],'0')):
            self.mdu.write_bytes(raw)
            with self.subTest(address=address):self.apply(address,value)

    def test_duplicate_target_in_same_or_repeated_output_section_refused(self):
        for address in ADDRESSES:
            key=address.split('/')[1]
            same_section=fixture().replace(b'Mystery =',key.encode()+b' = 0\r\nMystery =')
            self.mdu.write_bytes(same_section);self.refuse(address,'1',error='ambiguous_setting')
            for suffix in ('\r\n[output]\r\n'+key+' = 0\r\n','\r\n[output]\r\n'+key+' = 1\r\n'+key+' = 0\r\n'):
                self.mdu.write_bytes(fixture()+suffix.encode());self.refuse(address,'1',error='ambiguous_setting')
                self.refuse(address,'1',apply=True,expected=sha_bytes(self.mdu.read_bytes()),error='ambiguous_setting')

    def test_absent_switch_or_absent_output_section_is_never_inserted(self):
        for address in ADDRESSES:
            key=address.split('/')[1]
            token=b'Wrihis_balance' if key=='wrihis_balance' else b'WriShp_obs'
            raw=fixture().replace(token,('Unknown_'+key).encode())
            self.mdu.write_bytes(raw);self.refuse(address,'1',error='missing_setting')
        self.mdu.write_bytes(b'[other]\nWrishp_obs = 0\n')
        self.refuse(ADDRESSES[0],'1',apply=True,expected=sha_bytes(self.mdu.read_bytes()),error='missing_setting')

    def test_new_values_reject_numeric_aliases_nonfinite_unicode_and_injection(self):
        for address in ADDRESSES:
            self.mdu.write_bytes(fixture())
            for value in INVALID_NEW:
                with self.subTest(address=address,value=repr(value)):self.refuse(address,value)

    def test_malformed_existing_values_are_not_repaired_by_valid_request(self):
        for address in ADDRESSES:
            for old in INVALID_OLD:
                self.mdu.write_bytes(fixture(shape=old,balance=old))
                with self.subTest(address=address,old=repr(old)):self.refuse(address,'1')

    def test_apply_rejects_missing_invalid_and_stale_MDU_hash_without_changes(self):
        for address in ADDRESSES:
            self.mdu.write_bytes(fixture());code,payload=self.refuse(address,'1',apply=True,error='expected_hash_required');self.assertEqual(code,2)
            for invalid in ('0'*64,'not-a-hash','0'*63,'0'*65):
                code,payload=self.refuse(address,'1',apply=True,expected=invalid,error='stale_preview');self.assertEqual(code,4)
            code,preview=self.edit(address,'1');self.assertEqual(code,0)
            self.mdu.write_bytes(self.mdu.read_bytes()+b'# actual competing writer\r\n')
            code,payload=self.refuse(address,'1',apply=True,expected=preview['result']['before_sha256'],error='stale_preview');self.assertEqual(code,4)

    def test_preview_with_stale_expectation_also_refuses_and_does_not_write(self):
        for address in ADDRESSES:
            self.refuse(address,'1',expected='0'*64,error='stale_preview')

    def test_mid_preparation_concurrent_change_is_preserved_and_not_overwritten(self):
        for address in ADDRESSES:
            self.mdu.write_bytes(fixture());original=self.mdu.read_bytes();concurrent=original+b'# concurrent writer during apply\r\n';calls=0;real_read=Path.read_bytes
            def observe(path):
                nonlocal calls
                if path.resolve()==self.mdu.resolve():
                    calls+=1
                    if calls==2:path.write_bytes(concurrent)
                return real_read(path)
            with patch.object(Path,'read_bytes',observe):code,payload=self.edit(address,'1',apply=True,expected=sha_bytes(original))
            self.assertEqual(code,4,payload);self.assertEqual(payload['error']['code'],'stale_preview');self.assertEqual(self.mdu.read_bytes(),concurrent)
            self.assertGreaterEqual(calls,2)

    def test_preview_hash_describes_captured_snapshot_not_later_file_version(self):
        original=fixture();self.mdu.write_bytes(original);later=original+b'# later version\r\n';real_read=Path.read_bytes;changed=False
        def observe(path):
            nonlocal changed
            data=real_read(path)
            if path.resolve()==self.mdu.resolve() and not changed:changed=True;path.write_bytes(later)
            return data
        with patch.object(Path,'read_bytes',observe):code,payload=self.edit(ADDRESSES[0],'1')
        self.assertEqual(code,0,payload);self.assertEqual(payload['result']['before_sha256'],sha_bytes(original))
        self.assertEqual(payload['result']['after_sha256'],sha_bytes(expected_edit(original,ADDRESSES[0],'1')))
        self.assertEqual(self.mdu.read_bytes(),later);self.refuse(ADDRESSES[0],'1',apply=True,expected=payload['result']['before_sha256'],error='stale_preview')

    def test_hash_scope_is_MDU_not_a_field_set_graph_hash_and_unrelated_writer_survives(self):
        code,preview=self.edit(ADDRESSES[0],'1');self.assertEqual(code,0)
        linked=self.mdu.parent/'untouched.bc';external=b'actual independently changed unrelated input\r\n';linked.write_bytes(external)
        code,payload=self.edit(ADDRESSES[0],'1',apply=True,expected=preview['result']['before_sha256']);self.assertEqual(code,0,payload)
        self.assertEqual(linked.read_bytes(),external)

    def test_switch_edit_does_not_validate_rewrite_or_insert_interval_and_clock_fields(self):
        original=b'\xef\xbb\xbf[output]\r\nWrishp_obs = 0\r\nWrihis_balance=1\r\nHisInterval=60 0 600\r\nMapInterval=0\r\nRstInterval=30 30 90\r\n'
        self.mdu.write_bytes(original);self.apply(ADDRESSES[0],'1')
        self.assertNotIn(b'[time]',self.mdu.read_bytes());self.assertNotIn(b'StopDateTime',self.mdu.read_bytes())

    def test_existing_interval_and_stop_editor_semantics_remain_distinct(self):
        raw=fixture().replace(b'MapInterval = 60 0 120',b'MapInterval = 60');self.mdu.write_bytes(raw)
        code,preview=self.edit('output/hisinterval','30');self.assertEqual(code,0,preview)
        code,result=self.edit('output/hisinterval','30',apply=True,expected=preview['result']['before_sha256']);self.assertEqual(code,0,result)
        self.assertEqual(self.mdu.read_bytes(),raw.replace(b'HisInterval = 60.0000',b'HisInterval = 30'))
        code,result=self.edit('output/hisinterval','0');self.assertNotEqual(code,0);self.assertEqual(result['error']['code'],'invalid_interval')
        code,result=self.edit('time/stopdatetime','1');self.assertNotEqual(code,0);self.assertEqual(result['error']['code'],'invalid_date')
        code,preview=self.edit('time/stopdatetime','20010101000300');self.assertEqual(code,0,preview)
        code,result=self.edit('time/stopdatetime','20010101000300',apply=True,expected=preview['result']['before_sha256']);self.assertEqual(code,0,result)
        self.assertIn(b'StopDateTime = 20010101000300',self.mdu.read_bytes())

    def test_public_fields_pointer_is_discovery_not_candidate_or_field_set_permission(self):
        before=inventory(self.root)
        for address in ADDRESSES:
            code,payload=self.call(['model','fields',self.mdu,'--section','output','--key',address.split('/')[1]]);self.assertEqual(code,0,payload)
            rows=payload['result']['fields'];self.assertEqual(len(rows),1)
            for row in rows:
                self.assertEqual(row['model_set_preview'],dict(POINTER,setting=address));self.assertIs(row['editor_available'],False);self.assertIs(row['editable'],False)
                self.assertEqual(row['edit_eligibility']['candidate_validation'],'not_performed')
            code,payload=self.call(['model','field-set',self.mdu,address,'1','--unit','1'])
            self.assertNotEqual(code,0);self.assertEqual(payload['error']['code'],'unsupported_field_edit')
        self.assertEqual(inventory(self.root),before)

    def test_pointer_on_duplicate_target_occurrences_never_promotes_ambiguous_edit(self):
        self.mdu.write_bytes(fixture()+b'[output]\nWrishp_obs = 1\n')
        code,payload=self.call(['model','fields',self.mdu,'--section','output','--key','Wrishp_obs']);self.assertEqual(code,0,payload)
        rows=payload['result']['fields'];self.assertEqual(len(rows),2)
        for row in rows:self.assertEqual(row['model_set_preview'],dict(POINTER,setting=ADDRESSES[0]));self.assertFalse(row['editable'])
        self.refuse(ADDRESSES[0],'1',error='ambiguous_setting')

    def test_pointer_for_malformed_existing_token_is_not_candidate_acceptance(self):
        self.mdu.write_bytes(fixture(shape='01',balance='01'));before=inventory(self.root)
        for address in ADDRESSES:
            code,payload=self.call(['model','fields',self.mdu,'--section','output','--key',address.split('/')[1]])
            self.assertEqual(code,0,payload);row=payload['result']['fields'][0]
            self.assertEqual(row['value'],'01');self.assertEqual(row['model_set_preview'],dict(POINTER,setting=address))
            self.assertFalse(row['editable']);self.assertEqual(row['edit_eligibility']['candidate_validation'],'not_performed')
            self.refuse(address,'1')
        self.assertEqual(inventory(self.root),before)


def real_replay(source,controls,out):
    source=Path(source).resolve(strict=True);controls=Path(controls).resolve(strict=True);out=Path(out).resolve()
    if any(out.is_relative_to(p) or p.is_relative_to(out) for p in (source,controls)):raise ValueError('Fresh public evidence overlaps retained original')
    out.mkdir(parents=True,exist_ok=False);commands=out/'commands';commands.mkdir();cli=PublicCLI(commands)
    source_before=inventory(source);controls_before=inventory(controls);results=[]
    code,schema,_=cli.call(['schema','inspect'],'schema');assert code==0
    for case,address,value in [('wrishp_obs_1',ADDRESSES[0],'1'),('wrihis_balance_0',ADDRESSES[1],'0')]:
        target=out/case;shutil.copytree(source,target);mdu=target/'f34.mdu';original=mdu.read_bytes();wanted=expected_edit(original,address,value)
        assert (controls/'cases'/case/'f34.mdu').read_bytes()==wanted,'Independent native authored control differs'
        before=inventory(target);code,preview,_=cli.call(['model','set',mdu,address,value],case+'-preview');assert code==0,preview
        assert inventory(target)==before and preview['result']['before_sha256']==sha_bytes(original) and preview['result']['after_sha256']==sha_bytes(wanted)
        code,applied,_=cli.call(['model','set',mdu,address,value,'--apply','--expect-sha256',preview['result']['before_sha256']],case+'-apply');assert code==0,applied
        assert mdu.read_bytes()==wanted and inventory(target)==inventory(controls/'cases'/case)
        one={'case':case,'preview_hash':preview['result']['before_sha256'],'applied_hash':applied['result']['after_sha256'],
            'native_authored_control_MDU_sha256':sha_bytes((controls/'cases'/case/'f34.mdu').read_bytes()),'all_ten_files_match_native_control':True}
        original_value='0' if case=='wrishp_obs_1' else '1'
        code,reverse,_=cli.call(['model','set',mdu,address,original_value],case+'-reverse-preview');assert code==0,reverse
        code,reverse_applied,_=cli.call(['model','set',mdu,address,original_value,'--apply','--expect-sha256',reverse['result']['before_sha256']],case+'-reverse-apply');assert code==0,reverse_applied
        assert inventory(target)==source_before;one['reverse_exact_original_ten_files']=True;results.append(one)
    assert inventory(source)==source_before and inventory(controls)==controls_before
    report={'state':'public_f34_preview_apply_reverse_matches_retained_native_controls','cases':results,'source_hashes':source_before,
        'native_controls_unchanged':True,'original_source_unchanged':True,'native_started':False,'GUI_mapping':'not_tested',
        'scope':'Public editor byte/hash behavior only. Reuses retained engine-authored input controls; no new numerical/native claim.',
        'test_file_sha256':sha_bytes(Path(__file__).read_bytes())}
    (out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report


if __name__=='__main__':
    if '--real-replay' in sys.argv:
        parser=argparse.ArgumentParser(description='Read-only retained-control comparison using fresh public-edit f34 copies')
        parser.add_argument('--real-replay',action='store_true');parser.add_argument('--source',required=True);parser.add_argument('--native-controls',required=True);parser.add_argument('--out',required=True)
        a=parser.parse_args();print(json.dumps(real_replay(a.source,a.native_controls,a.out),indent=2))
    else:unittest.main()
