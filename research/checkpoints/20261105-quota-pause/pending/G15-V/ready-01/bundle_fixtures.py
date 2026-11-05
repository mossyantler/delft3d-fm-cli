"""Manually authored interchange bytes from declared schema, not exporter output.

Hydraulic index assets lists CHILD PLI/TIM only. Context and structure are exact
separate control paths, not childassets. Only children map to target assets.
This follows the declared interface, not a candidate export/parser result.
"""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PRE=HERE/'predeclared-02'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def write_json(path,obj):path.write_bytes((json.dumps(obj,indent=2)+'\n').encode())
def create_geometry(case,*,raw=None,route='W_Main'):
    root=case.source_bundle;root.mkdir(exist_ok=False)
    (root/'assets').mkdir()
    raw=raw if raw is not None else (PRE/'literal-expected/geometry-replace.pli').read_bytes()
    (root/'assets/location.pli').write_bytes(raw)
    write_json(root/'geometry.json',{'format':'dfm-structure-geometry-v1',
        'routes':[{'route_id':route,'asset_path':'assets/location.pli'}]})

def create_hydraulic(case,*,new_id=None):
    root=case.source_bundle;root.mkdir(exist_ok=False)
    (root/'context').mkdir();(root/'payload').mkdir()
    raw=(PRE/'literal-expected/export-selected-structures.ini').read_bytes()
    if new_id is not None:
        assert raw.count(b'id = W_Main\r\n')==1
        raw=raw.replace(b'id = W_Main\r\n',b'id = '+new_id.encode('ascii')+b'\r\n')
    files={
        'context/source.mdu':(PRE/'models/literal-source/model.mdu').read_bytes(),
        'payload/structures.ini':raw,
        'payload/source-weir.pli':(PRE/'literal-expected/geometry-replace.pli').read_bytes(),
        'payload/source.tim':(PRE/'literal-expected/native-minute-crest.tim').read_bytes(),
    }
    for name,data in files.items():(root/name).write_bytes(data)
    write_json(root/'bundle.json',{'format':'dfm-structure-bundle-v1',
        'context_path':'context/source.mdu','structure_path':'payload/structures.ini',
        'assets':[{'path':name,'sha256':sha(data),'bytes':len(data)} for name,data in files.items()
                  if name not in ('context/source.mdu','payload/structures.ini')]})
    write_json(case.asset_map,{'version':1,'assets':[
        {'source_path':'payload/source-weir.pli','target_path':'mapped-source.pli'},
        {'source_path':'payload/source.tim','target_path':'mapped-crest.tim'},
    ]})

def reseal(root):
    """For deliberate adulteration: update literal hash claims to actual new bytes.

    This prevents tests from merely exercising a stale hash when the intended
    negative is a wrong native role/identity/clock or unsupported dependency.
    """
    p=root/'bundle.json';index=json.loads(p.read_bytes())
    for a in index['assets']:
        raw=(root/a['path']).read_bytes();a['sha256']=sha(raw);a['bytes']=len(raw)
    write_json(p,index)
