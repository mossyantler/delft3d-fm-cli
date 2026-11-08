"""I1 structure interchange metadata. No mutable evidence/source-file reads."""
from .common import DfmError
from .pump_edit_contract import POLICY_VERSION as FILE_PUBLICATION_POLICY

CONTRACT='structure-transfer-I1-v1'
EDIT_POLICY='structure-transfer-raw-cores-routing-v1'
DIRECTORY_POLICY='structure-transfer-exclusive-directory-v1'
LIMITS={'files':512,'graph_bytes':2*1024**3,'file_bytes':256*1024**2,'text_bytes':8*1024**2,
        'text_total_bytes':64*1024**2,'structures':1024,'assets':128,'vertices':100000,'references':8192,'details':256}
SCOPE=[
 ('W2D','I1','planar XY locationFile weir; scalar or root-relative TIM crest'),
 ('P2D','I1','planar XY scalar unstaged no-reduction pump'),
 ('WTBC','deferred_I2','structure BC and pump TIM: typed quantity/object/clock grammar required'),
 ('G2D','deferred_I3','gate/orifice/generalstructure hydraulic and motion semantics'),
 ('PTRIGGER','deferred_I3','staged/reduction/live-controller pump'),
 ('PIL12','deferred_I4','PillarFile x,y,diameter,Cd; not hydraulic bridge or elevation'),
 ('PIL3D','unsupported','manual pillar3D unavailable; no runtime qualification'),
 ('PPLIZ','deferred_I4','extra pump PLIZ attributes never truncated to XY'),
 ('SHP','deferred_I5','documented GIS branches; actual GUI schema/sidecars unknown'),
 ('D1','deferred_I6','branch/chainage/inline locations and network topology'),
 ('MODEL3D','deferred_I6','layered/mixed mesh semantics; Kmx0 not topology proof'),
 ('LEG','deferred_I6','legacy structures/EXT/CMP/fixed-weir3/4/5/9/10-column variants'),
 ('OTHER','deferred_I6','universalweir/culvert/bridge/dambreak/longculvert'),
 ('GROUP','deferred_I2_I6','compound/multiple INIs/mode1/nested path counterpaths'),
 ('MULTI','deferred_I7','new assets/MDU refs/multi-target transaction, never simulated atomic'),
 ('GUI','unverified','fresh owned standalone GUI import/export remains separate'),
]


def fail(code,message,details=None,exit_code=3):
    raise DfmError('structure_transfer_'+code,message,exit_code,details)


def context(exc):
    if exc.code.startswith('structure_transfer_'):return exc
    message=str(exc).replace('Pump input publication','Structure input publication').replace('Pump input','Structure input')
    return DfmError('structure_transfer_service',message,exc.exit_code,{'service_code':exc.code,'service_details':exc.details})


def policies():return {'edit':EDIT_POLICY,'file_publication':FILE_PUBLICATION_POLICY,'directory_publication':DIRECTORY_POLICY}


def contract():
    return {'contract':CONTRACT,'policy':policies(),'commands':{
      'inspect':'structure inspect MDU [--id FULL_ID]',
      'export':'structure export MDU (--all|--id FULL_ID repeat) --representation geometry|hydraulic-bundle --out NEW_DIRECTORY [--apply --expect-sha256 HASH]',
      'import_geometry':'structure import MDU --source GEOMETRY_DIRECTORY --representation geometry --id TARGET_ID --mode replace-matching --coordinates model-xy-as-is --xy-unit m [--apply --expect-sha256 HASH]',
      'import_hydraulic':'structure import MDU --source HYDRAULIC_DIRECTORY --representation hydraulic-bundle (--all|--id FULL_ID repeat) --mode append|replace-matching --coordinates model-xy-as-is --xy-unit m --target-structure-file EXISTING_RELATIVE_INI --asset-map MAP.json [--height-unit m --vertical-datum LABEL] [--apply --expect-sha256 HASH]'},
      'scope':[{'id':i,'state':s,'description':d} for i,s,d in SCOPE],
      'first_profile':'one root3.01 StructureFile; MDU value has no whitespace/quotes/semicolon; explicit PathsRelativeToParent0/Kmx0. This is a file/XY-parameter profile, not mesh dimensionality/spatial or native validation.',
      'geometry_identity':'source route_id operator-declared/unverified; actual target ID/type/roles from INI, actual geometry from PLI. Header never relabelled or matched as Structure.id.',
      'hydraulic_identity':'actual source ID/type and references from raw INI; explicit target INI and existing byte-identical mapped assets. No hidden asset/MDU/multi-file writes.',
      'selection':'exact full ASCII IDs1..255; global exact/casefold ambiguity refused as policy. Source INI order; replace destination slots; append before file-owned footer.',
      'framing':'INI core header through LAST key/value EOL; interior comments travel, trailing comments/blanks are file-owned. General/non-target destination bytes exact. Missing-EOL bridges use first destination EOL only when more bytes follow.',
      'geometry':'one complete ASCII location block, <=256byte records, >=2 distinct normal binary64 XY points, no zero adjacent segments; extra blocks/columns refuse. Finite -999/999.999 XY is not a native separator.',
      'units':{'capacity':'m3/s','crestLevel':'m','crestWidth':'m','orientation':None,'declared_file_unit':'scalar/TIM has no invented Unit header','spatial':'explicit as-is/m assertion, no CRS/axis/datum/unit transform; height fields require m+datum label on import'},
      'clock':'TIM minute column, actual explicit RefDate/TZone/model coverage; never MDU TUnit as TIM unit or initialized0 substituted for authored knot. BC/live controls deferred, not filenames guessed from suffix.',
      'indices':'strict closed schemas/actual full file tree, untrusted routing/index/map; no stored approval/eligibility/authenticity authority or unlisted nested dependency/extraction bypass',
      'publication':'preview no writes; request+graph+external bytes/identity/security/parents+intended output consent. Full late rechecks; legitimate identical-target import no staging/identity/mtime churn; export absent directory only. Honest raw commit/rollback/cleanup, no global CAS.',
      'limits':LIMITS,'errors':{'usage':2,'unsupported_data_path':3,'collision_missing_match_stale_publication':4},
      'evidence':{'source_pin':'5a4649830b1e5072caf019fb4850bbdefd9ad431','GUI':'not_verified','native':'not_performed','scientific':'not_performed','mesh_topology':'not_verified','G13_G16_G18_acceptance_inherited':False}}
