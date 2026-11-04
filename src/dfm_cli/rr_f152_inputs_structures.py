"""Exact-SHA f152 structure declaration repair; never infer a bedLevel shift.

The pinned fixture already has both bridge shifts, despite its v2 declaration.
Readstructures.f90:175-176 supports v2 for nonbridges; :286-291 rejects bridges
by major version before reading their fields. :82 and UM C.12.11 (PDF486)
identify the v3 bridge change. Here all fields already meet that format. Only
the declaration is repaired; this is not an arbitrary legacy model converter.
"""
from collections import Counter
from decimal import Decimal
import hashlib

from .model import parse
from .rr_f152_source import ENGINE_SOURCE, REVISION, FILES, fail

STRUCTURES='fm/structure.ini'
DEFINITIONS='fm/cross_section_definitions.ini'
COUNTS={'culvert':25,'weir':4,'bridge':2,'pump':2,'universalWeir':2,'orifice':1,'compound':1}
FIELDS={
    'culvert': 'allowedflowdir bedfriction bedfrictiontype branchid chainage csdefid id inletlosscoeff leftlevel length numlosscoeff outletlosscoeff rightlevel type valveonoff',
    'weir': 'allowedflowdir branchid chainage corrcoeff crestlevel crestwidth id type usevelocityheight',
    'bridge': 'allowedflowdir branchid chainage csdefid friction frictiontype id inletlosscoeff length outletlosscoeff shift type',
    'pump': 'branchid capacity chainage controlside id numstages orientation startlevelsuctionside stoplevelsuctionside type',
    'universalWeir': 'allowedflowdir branchid chainage crestlevel dischargecoeff id numlevels type yvalues zvalues',
    'orifice': 'allowedflowdir branchid chainage corrcoeff crestlevel crestwidth gateloweredgelevel id limitflowneg limitflowpos type uselimitflowneg uselimitflowpos usevelocityheight',
    'compound': 'id numstructures structureids type',
}
LEGACY_KEYS={'bedlevel','nrstages','reductionfactorlevels','losscoeffcount','levelscount','lat_contr_coeff','polylinefile'}
BRIDGES={'RS1-KBR32':('prof_RS1-KBR32','yz'), 'RS1-KBR31':('W_980.1S_0','zw')}


def _blocks(raw):
    result=[]
    for line in raw.decode('ascii').splitlines():
        text=line.split('#',1)[0].strip()
        if not text:continue
        if text.startswith('[') and text.endswith(']'):
            result.append((text[1:-1].casefold(),{}))
        elif '=' in text and result:
            key,value=text.split('=',1);key=key.strip().casefold()
            if key in result[-1][1]:fail('Ambiguous fixed structure/definition key',key)
            result[-1][1][key]=value.strip()
        else:fail('Unsupported record in fixed structure declaration repair',text)
    return result


def repair(raw,definitions):
    """Return one-byte header repair plus independently reviewable metadata.

    Exact source binding precedes the type/key checks. A future bedLevel input,
    different profile, or any other fixture cannot acquire a version bump here.
    Original whole bytes and hashes are retained by rr_f152's existing source
    proof, including the newly changed structure.ini, without a new side file.
    """
    for name,content in ((STRUCTURES,raw),(DEFINITIONS,definitions)):
        if hashlib.sha256(content).hexdigest()!=FILES[name]['sha256']:
            fail('Structure declaration repair is limited to the exact pinned f152 SHA',name)
    blocks=_blocks(raw);metadata=[fields for kind,fields in blocks if kind=='general']
    if metadata!=[dict(fileversion='2.00',filetype='structure')]:fail('Unexpected structure declaration')
    structures=[fields for kind,fields in blocks if kind=='structure']
    if len(blocks)!=len(structures)+1 or Counter(s['type'] for s in structures)!=COUNTS:
        fail('Fixed structure type inventory changed')
    identities=[s['id'] for s in structures]
    if len(set(identities))!=len(identities):fail('Ambiguous structure identities')
    inventory=[];bridges=[]
    defs={}
    for kind,fields in _blocks(definitions):
        if kind=='definition':
            if fields['id'] in defs:fail('Ambiguous cross-section definition identity',fields['id'])
            defs[fields['id']]=fields
    for block in structures:
        kind=block['type'];keys=set(block)
        if keys & LEGACY_KEYS or keys!=set(FIELDS[kind].split()):
            fail('Structure fields require a separate format/geometry migration',dict(id=block['id'],keys=sorted(keys)))
        inventory.append(dict(id=block['id'],type=kind,keys=sorted(keys)))
        if kind=='bridge':
            identity=block['id'];expected=BRIDGES.get(identity)
            if not expected or block['csdefid']!=expected[0] or block['shift']!='0.0':
                fail('Bridge shift/reference changed; never infer an absolute bedLevel conversion',identity)
            definition=defs.get(block['csdefid'])
            if not definition or definition['type']!=expected[1]:fail('Referenced bridge definition is missing/unsupported',identity)
            ordinate='zcoordinates' if definition['type']=='yz' else 'levels'
            values=[Decimal(v) for v in definition[ordinate].split()]
            count=int(definition['yzcount' if ordinate=='zcoordinates' else 'numlevels'])
            if len(values)!=count or not all(v.is_finite() for v in values):fail('Incomplete/nonfinite bridge profile',identity)
            bridges.append(dict(id=identity,csDefId=block['csdefid'],shift=block['shift'],shift_unit='m',positive='upwards',
                                definition_type=definition['type'],vertical_ordinates_key=ordinate,
                                vertical_ordinates=definition[ordinate],minimum_input_ordinate_m=str(min(values)),
                                geometry_bytes='unchanged',absolute_bedLevel='absent; no conversion performed'))
    if {b['id'] for b in bridges}!=set(BRIDGES):fail('Incomplete fixed bridge inventory')
    records=[entry for entry in parse(raw) if entry.address=='general/fileversion']
    if len(records)!=1:fail('Ambiguous version token')
    record=records[0]
    if raw[record.start:record.end]!=b'2.00':fail('Unexpected version token bytes')
    result=raw[:record.start]+b'3.00'+raw[record.end:]
    if len(result)!=len(raw) or sum(a!=b for a,b in zip(raw,result))!=1:
        fail('Structure repair must change exactly one version byte')
    report=dict(operation='repair_misdeclared_format_header',relative_path=STRUCTURES,
                from_version='2.00',to_version='3.00',changed_byte_count=1,version_token_offset=record.start,
                original_sha256=FILES[STRUCTURES]['sha256'],authored_sha256=hashlib.sha256(result).hexdigest(),
                original_bytes='Retained verbatim in rr-f152-source.json changed_or_unstaged_originals_zlib_base64',
                structure_count=len(structures),type_counts=dict(COUNTS),block_inventory=inventory,bridges=bridges,
                cross_definition_sha256=FILES[DEFINITIONS]['sha256'],legacy_keys_present=[],
                source=dict(engine_revision=ENGINE_SOURCE,fixture_revision=REVISION,
                            reader='src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90:73-83,109-114,175-176,286-291,794-828',
                            reader_sha256='4ede5d23e95312f5340846e04af3359488cd8d75a47220f014ed51cac61f4761',
                            manual='D-Flow FM User Manual 2026.02 rev81168: C.12.4 Table C.18 PDF479; C.12.11 PDF486',
                            scope='v2/v3 share nonbridge readers; both satisfy currentFileVersion>=2 compound finalization; explicit bridge shift is positive-up metres'),
                geometry_conversion='none; existing shifts and cross-section definition bytes preserved',
                native_initialization='not_performed')
    return result,report
