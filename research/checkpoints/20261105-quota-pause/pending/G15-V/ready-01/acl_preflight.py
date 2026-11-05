"""Exercise independent ACL observation only on one fresh G15 V-owned file."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from win_file_acl import observe,public,set_protected

HERE=Path(__file__).resolve().parent
OUT=HERE/'acl-witness-preflight-01'
OUT.mkdir(exist_ok=False)
target=OUT/'private.pli'
raw=b'Not_a_structure_ID\r\n2 2\r\n10 0\r\n10 10\r\n'
target.write_bytes(raw)
before=None
with patch('subprocess.Popen',side_effect=AssertionError('G15 file-only no process')) as popen:
    before=observe(target)
    assert before['protected_dacl'] is False
    try:
        protected=set_protected(target,before,fixture_root=HERE,protected=True)
    finally:
        restored=set_protected(target,before,fixture_root=HERE,protected=False)
    assert target.read_bytes()==raw
    assert before['sddl']==restored['sddl']
    assert popen.call_count==0
report={'state':'PASSED_INDEPENDENT_PRIVATE_FILE_ACL_WITNESS_ONLY','before':public(before),
 'protected':public(protected),'restored':public(restored),'exact_SDDL_restored':True,
 'raw_sha256':hashlib.sha256(raw).hexdigest(),'only_modified_path':str(target),
 'native_or_GUI_started':False,'processes_launched':0,'Job_objects_created':0,
 'product_ACL_acceptance':False,'root_or_product_writes':False,
 'ACL_helper_sha256':hashlib.sha256((HERE/'win_file_acl.py').read_bytes()).hexdigest()}
(OUT/'verification.json').write_bytes((json.dumps(report,indent=2)+'\n').encode())
print(json.dumps({'state':report['state'],'exact_SDDL_restored':True,'processes_launched':0}))
