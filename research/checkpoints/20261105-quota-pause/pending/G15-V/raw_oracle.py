"""Independent literal file oracle; never imports dfm_cli.

An operation receives expected complete bytes by relative path. Everything else
must be byte-identical, and no unannounced artifact is allowed under the model.
Identity/mtime preservation is separately available for no-ops/refusals.
"""
import hashlib
from pathlib import Path

def sha(raw):return hashlib.sha256(raw).hexdigest()

def snapshot(root):
    root=Path(root)
    result={}
    for path in sorted(root.rglob('*')):
        info=path.lstat()
        assert not path.is_symlink(),path
        if path.is_file():
            raw=path.read_bytes()
            result[path.relative_to(root).as_posix()]={
                'raw':raw,'sha256':sha(raw),'bytes':len(raw),
                'identity':[info.st_dev,info.st_ino],
                'mtime_ns':info.st_mtime_ns,'nlink':info.st_nlink,
                'mode':info.st_mode,'attributes':getattr(info,'st_file_attributes',None)}
    return result

def public_snapshot(data):
    return {name:{k:v for k,v in entry.items() if k!='raw'} for name,entry in data.items()}

def require_exact(before,after,expected_changes=None,*,stable_untouched=True):
    expected_changes=expected_changes or {}
    assert set(before)==set(after),{'missing':sorted(before.keys()-after.keys()),'added':sorted(after.keys()-before.keys())}
    assert set(expected_changes)<=set(before),'No input insertion/deletion admitted'
    for name,old in before.items():
        expected=expected_changes.get(name,old['raw'])
        assert after[name]['raw']==expected,('Unexpected complete bytes',name,sha(expected),after[name]['sha256'])
        if stable_untouched and (name not in expected_changes or expected==old['raw']):
            for key in ('identity','mtime_ns','mode','attributes','nlink'):
                assert old[key]==after[name][key],('Unannounced metadata/identity change',name,key,old[key],after[name][key])

def require_roles(actual,expected):
    """Same bytes are insufficient for a different logical source/target role."""
    normalized=lambda edges:sorted((e['from'],e['setting'],e['path'],e.get('id')) for e in edges)
    assert normalized(actual)==normalized(expected),('Reference roles differ',actual,expected)
