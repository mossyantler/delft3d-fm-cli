"""Complete positional FNM disposition for the byte-bound fixed62 f152 recipe.

Only call after reconstructing the complete pinned source and byte-comparing
the authored recipe. No general optional-file exemptions are exported here.
Evidence is static analysis of ENGINE_SOURCE, not installed-engine evidence.
"""
from collections import Counter
import re

from .rr_f152_source import ENGINE_SOURCE, FNM_PREDICATES, fail, regular


# Closed storage/consumer analysis, independently crosschecked by Faraday:
# NAMFIL is PRIVATE; no pointer or bulk getter exposes it. All executable
# accesses to names outside Conf_fil use this one getter. Its 285 literal
# callsites never select39/58. All seven dynamic callsites were traced through
# their consumers: they only transform names and pass them back to the setter.
# INITDT's later NMFMAP assignments explicitly select actual output slots.
# This is stronger than an absent-filename search and narrower than claiming
# that legacy entries are optional in other releases or installations.
LEGACY_READER_PROOF = dict(
    revision=ENGINE_SOURCE,
    scope='Private NAMFIL storage and complete RR getter-consumer dataflow in pinned source only',
    private_storage='Conf_fil.f90:50,100; getter154-158; setter161-166',
    literal_getter_calls=285,
    dynamic_getter_calls=[
        'FILESMODULE.F90:617,670 -> local name/postfix transforms -> setter641,673',
        'INITDT.F90:181,183,190,198,210 -> local name/path transforms -> setter197,202,209,214,217',
    ],
    source_sha256={
        'Conf_fil.f90':'3e151deb2ff90a4fa7ad4bc36d27cc4a1f09855858448f6b18874241d72fa168',
        'FILESMODULE.F90':'dbbc225d4fe1aca5d2c525df6a4106dfe1caf1b1c6313cf3d67ece8aafa13e0b',
        'INITDT.F90':'2cfb31cd0f92b4d5e46ce2b85ee42047afad5ce406b0bfedb00be464494a91a8',
    },
    installed_engine_source_commit='unknown',native_initialization='not_performed',
)

# Output roles are positional, from the pinned FNM and native output tables.
# Slot102 can be an incoming Modflow HIS and is handled by its disabled module
# predicate instead of claiming it is universally an output.
OUTPUT_SLOTS=(set(range(22,31))|{32,37,42,45,46,47}|set(range(62,77))|
              {81}|set(range(83,92))|set(range(95,102))|
              {103,104,105,107,116,119,120})
PREDICATES={
    '39':dict(classification='retained_legacy_slot_no_input_reader_in_pinned_source',
              basis='Closed private NAMFIL/getter-consumer proof; SaltComputation absent => ISLCMP=0 (NetworkModule:615,558-559); not inferred from OutputRRSalt',proof=LEGACY_READER_PROOF),
    '58':dict(classification='retained_legacy_slot_no_input_reader_in_pinned_source',
              basis='Closed private NAMFIL/getter-consumer proof; actual RTC location identities come from DIO header (OUTPUTMODULE:5611-5685)',proof=LEGACY_READER_PROOF),
    '80':dict(classification='inactive_node_family',
              basis='No internal18 External Runoff nodes; BinFileModule:794,852-854 sets NcRRRunoffExternal=0; FILESMODULE:474-475/RRModule:823-825 gate reader on >0'),
    '95':dict(classification='native_output_path',
              basis='UnpavedModule.F90:4606-4614 opens FNM95 for writing with UnsatZoneOption>=1; pinned UnsaturatedZone=1'),
    '102':dict(classification='inactive_explicit_option',
               basis='ModflowModule absent => IModFlow=0 (NetworkModule:634,502-504); RRModule:2100-2105 reads incoming HIS only if OnLineModflowUsed'),
    '114':dict(classification='explicit_missing_file_fallback',
               basis='RRModule.F90:320-325 INQUIRE then DioInit only if present; missing emits warning and continues. No old RTC/Modflow/WQ data exchange activated in fixed DIMR recipe'),
    '115':dict(classification='inactive_explicit_option',
               basis='Pinned NWRWContinuous=0; rdini:342,790-792; RRModule:491-496 uses FNM115 only when true'),
    '118':dict(classification='inactive_node_family',
               basis='No internal17 Cell nodes; BinFileModule:635-642 Cell reader disabled in pinned source; no literal input getter'),
    '121':dict(classification='inactive_explicit_option',
               basis='NetworkModule:615,636 defaults ISLCMP=IWQModule=0, neither enabled in fixed INI; RRModule:1692/2094-2095 also exclude DLL/DIMR salt-HIS path'),
    '123':dict(classification='inactive_explicit_option',
               basis='UseOpenDAFile default false (rdini:372,445-447), absent in fixed INI; RRModule:1790-1794 and3120-3121 gate read/write; RestartIn=0'),
}


def disposition(root,original,actual,audit):
    """Return all123 affirmatively classified slots, or explicit blockers.

    The caller has already established exact fixed graph, options, and bytes.
    Generic audit issues remain available separately; none are silently dropped.
    """
    rows=[];by_name={name.casefold():name for name in actual}
    if len(by_name)!=len(actual):fail('Case-insensitive prepared path aliases')
    input_identities=set()
    for name in actual:
        st=(root/name).stat();input_identities.add((st.st_dev,st.st_ino))
    generic={row['slot']:row for row in audit['unresolved_fnm_slots']}
    for line in original['rr/Sobek_3b.fnm'].decode('ascii').splitlines():
        text=line.strip()
        if not text or text.startswith('*'):continue
        match=re.fullmatch(r"'([^']*)'\s*(?:\*.*)?",text)
        if not match:fail('Unexpected fixed FNM record')
        slot=len(rows)+1;name=match[1];native=by_name.get(('rr/'+name).casefold())
        present=native is not None;raw=actual[native] if present else None
        predicate=PREDICATES.get(str(slot)) or FNM_PREDICATES.get(str(slot))
        if predicate and not predicate['classification'].startswith('unresolved'):
            rule=dict(predicate)
        elif slot in OUTPUT_SLOTS:
            rule=dict(classification='native_output_path',basis='Pinned FNM positional output role and INITDT/OUTPUTMODULE tables; output is not an immutable input')
        elif name=='not used' or name=='':
            rule=dict(classification='explicit_native_not_used_sentinel',basis="FILESMODULE.F90:94 normalizes exact 'not used'; remaining input names/graph are byte-bound")
        elif present and raw:
            rule=dict(classification='pinned_input_present',basis='Complete62 source inventory and exact authored derivative byte comparison; no missing reference waived')
        else:
            rule=dict(classification='unresolved_native_reference',basis='No affirmative fixed-recipe source disposition; refuse native preparation')
        # Missing-DIO fallback must describe the filesystem the engine will
        # actually see. An added untracked .ini is an active input, not a harmless
        # extra file. Native outputs may appear after execution, but may never
        # alias an immutable input.
        if name and name!='not used':
            candidate=root/'rr'/name
            if candidate.exists() or candidate.is_symlink() or candidate.is_junction():
                path=regular(candidate)
                if rule['classification']=='native_output_path':
                    st=path.stat()
                    if (st.st_dev,st.st_ino) in input_identities:
                        fail('Native FNM output aliases an immutable input',dict(slot=slot,name=name))
                elif not present:
                    fail('Untracked FNM input changes the fixed recipe or missing-file predicate',dict(slot=slot,name=name))
        if rule['classification'].startswith('required_') and not present:
            fail('Required FNM container is missing',dict(slot=slot,name=name))
        row=dict(slot=slot,name=name,present=present,bytes=len(raw) if present else None,
                 relative_path=native,**rule)
        if slot in generic:row['generic_audit_classification']=generic[slot]['classification']
        rows.append(row)
    if len(rows)!=123:fail('Fixed FNM must have exactly123 slots')
    blockers=[r['slot'] for r in rows if r['classification'].startswith('unresolved')]
    return dict(scope='Byte-bound fixed62 f152 recipe only',source_revision=ENGINE_SOURCE,
                state='blocked' if blockers else 'complete_static_disposition',slots=rows,
                counts=dict(Counter(row['classification'] for row in rows)),unresolved_slots=blockers,
                native_initialization='not_performed',installed_engine_source_commit='unknown')
