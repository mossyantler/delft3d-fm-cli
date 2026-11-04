"""E014: bounded f34 property/export preparation; never launch on ordinary host.

The only launcher is the reviewed shared disposable-guest lifecycle hook. Preparation,
inspection and file verification execute no installed program. See the bundled
instructions; file-only verification is not evidence of a live GUI operation.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
from datetime import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute()
if (HERE.parent / 'replay.py').is_file():
    _spec = importlib.util.spec_from_file_location('e014_frozen_p08', HERE.parent / 'replay.py')
    p08 = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(p08)
    ASSETS = HERE.parent
else:
    from research.workflows.replay import dimr_project_export as p08
    ASSETS = HERE.parents[3] / 'research/assets/fields-project-export'

KIND = 'E014_f34_typed_property_export'
FLOW = 'plugins/DeltaShell.Plugins.FMSuite.FlowFM/DeltaShell.Plugins.FMSuite.FlowFM.dll'
COMMON = 'plugins/DeltaShell.Plugins.FMSuite.Common/DeltaShell.Plugins.FMSuite.Common.dll'
CSV = 'plugins/DeltaShell.Plugins.FMSuite.FlowFM/CsvFiles/dflowfm-properties.csv'
OWNER = 'DeltaShell.Plugins.FMSuite.FlowFM.ModelDefinition.WaterFlowFMProperty'
DEFINITION = 'DeltaShell.Plugins.FMSuite.FlowFM.ModelDefinition.WaterFlowFMPropertyDefinition'
DECLARING = 'DeltaShell.Plugins.FMSuite.Common.ModelSchema.ModelProperty'
CASES = {
    'control': {'source': 'chezy', 'key': None},
    'waterlevini': {'source': 'chezy', 'key': 'geometry/waterlevini', 'before': '1.9', 'after': '2.4', 'unit': 'm'},
    'dtmax': {'source': 'chezy', 'key': 'time/dtmax', 'before': '30', 'after': '15', 'unit': 's'},
    'manning-control': {'source': 'manning', 'key': None},
    'manning': {'source': 'manning', 'key': 'physics/uniffrictcoef', 'before': '0.023', 'after': '0.041', 'unit': 's m-1/3'},
}
BASE = {'geometry/waterlevini': '1.9', 'time/dtmax': '30',
        'physics/uniffricttype': '0', 'physics/uniffrictcoef': '65'}
NUM = rb'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?'
STAMP = re.compile(rb'\A((?:\xef\xbb\xbf)?# Generated on )([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})(?=\r?\n|\Z)')


def require(value, message):
    p08.require(value, message)


def plain(path):
    # P08 rejects live links; additionally reject dangling links BEFORE resolve.
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'Symlink (including dangling) refused: ' + str(part))
        if os.path.lexists(part):
            require(not getattr(part.lstat(), 'st_file_attributes', 0) & 0x400, 'Reparse path refused')
    return p08.plain(path)


def decimal(value):
    require(isinstance(value, str) and len(value) < 128 and re.fullmatch(NUM.decode(), value), 'Expected finite scalar numeric token')
    try:
        result = Decimal(value.lower().replace('d', 'e'))
    except InvalidOperation as exc:
        raise ValueError('Invalid numeric token') from exc
    require(result.is_finite(), 'Nonfinite numeric token')
    return result


def inventory(root):
    root = plain(root)
    for path in root.rglob('*'):
        plain(path)
    return p08.inventory(root)


def fields(data):
    """Ordered occurrences plus exact byte spans. Never collapse duplicate keys."""
    result = []; section = ''; offset = 0
    for line in data.splitlines(keepends=True):
        body = line.rstrip(b'\r\n')
        match = re.fullmatch(rb'\s*\[([^\]]+)\]\s*(?:#.*)?', body)
        if match:
            section = match[1].decode('ascii').strip().casefold()
        else:
            match = re.match(rb'([ \t]*)([^#;=\s][^=]*?)([ \t]*=[ \t]*)([^#\r\n]*?)([ \t]*)(#.*)?$', body)
            if match:
                key = section + '/' + match[2].decode('ascii').strip().casefold()
                start, end = match.span(4)
                result.append((key, match[4].decode('ascii'), offset + start, offset + end))
        offset += len(line)
    return result


def value(data, key):
    found = [item for item in fields(data) if item[0] == key]
    require(len(found) == 1, 'Missing/duplicate MDU target: ' + key)
    return found[0]


def expected_baseline(data, source):
    expected = dict(BASE)
    if source == 'manning':
        expected.update({'physics/uniffricttype': '1', 'physics/uniffrictcoef': '0.023'})
    for key, number in expected.items():
        require(decimal(value(data, key)[1]) == decimal(number), 'Unexpected ' + source + ' baseline: ' + key)


def masked(data, key=None, timestamp=True):
    spans = []
    if key:
        _, token, start, end = value(data, key); decimal(token)
        spans.append((start, end, b'<TARGET>'))
    stamp = STAMP.match(data)
    if timestamp and stamp:
        datetime.strptime(stamp[2].decode('ascii'), '%Y-%m-%d %H:%M:%S')
        spans.append((len(stamp[1]), stamp.end(), b'<GENERATED_TIMESTAMP>'))
    for start, end, replacement in sorted(spans, reverse=True):
        data = data[:start] + replacement + data[end:]
    return data


def manning_seed(original, derivative):
    original, derivative = plain(original), plain(derivative)
    a, b = inventory(original), inventory(derivative)
    require(len(a) == 10 and set(a) == set(b) and 'f34.mdu' in a, 'Expected two ten-file source graphs')
    require(all(a[n] == b[n] for n in a if n != 'f34.mdu'), 'Manning prerequisite changed non-MDU input')
    left, right = (original / 'f34.mdu').read_bytes(), (derivative / 'f34.mdu').read_bytes()
    expected_baseline(left, 'chezy'); expected_baseline(right, 'manning')
    def remove_prerequisites(data):
        spans = [value(data, k)[2:] for k in ('physics/uniffricttype', 'physics/uniffrictcoef')]
        for start, end in sorted(spans, reverse=True):
            data = data[:start] + b'<EXPLICIT_PREREQUISITE>' + data[end:]
        return data
    require(remove_prerequisites(left) == remove_prerequisites(right), 'Manning prerequisite changed bytes beyond two explicit numeric tokens')
    for folder in (original, derivative):
        p08.model_references(folder / 'f34.mdu', folder)
    return {'state': 'passed_two_token_authoring_only', 'original': a, 'derivative': b, 'equivalence_claimed': False}


def compare_exports(before, after, *, key=None, expected_before=None, expected_after=None):
    before, after = plain(before), plain(after)
    a, b = inventory(before), inventory(after)
    require(len(a) == 10 and set(a) == set(b) and 'f34.mdu' in a, 'Expected identical ten-file f34 export sets')
    require(all('/' not in name for name in a), 'Unexpected nested export input')
    p08.model_references(before / 'f34.mdu', before)
    p08.model_references(after / 'f34.mdu', after)
    left, right = (before / 'f34.mdu').read_bytes(), (after / 'f34.mdu').read_bytes()
    require([x[0] for x in fields(left)] == [x[0] for x in fields(right)], 'MDU ordered occurrences changed')
    if key:
        require(decimal(value(left, key)[1]) == decimal(expected_before), 'Wrong exported before value')
        require(decimal(value(right, key)[1]) == decimal(expected_after), 'Wrong exported after value (including no-op)')
    require(masked(left, key) == masked(right, key), 'Collateral MDU bytes changed')
    require(all(a[name] == b[name] for name in a if name != 'f34.mdu'), 'Non-target referenced input bytes changed')
    return {'state': 'passed', 'target': key, 'before': a, 'after': b,
            'allowed_differences': ['unique target numeric token'] * bool(key) + ['first exact Generated-on timestamp only'],
            'nine_non_mdu_files_byte_equal': True}


def schema(install):
    install = plain(install)
    selected = {name: {'sha256': p08.sha(p08.inside(install, name)), 'bytes': p08.inside(install, name).stat().st_size}
                for name in (FLOW, COMMON, CSV)}
    lines = (install / CSV).read_text(encoding='utf-8-sig').splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith('MduGroup,MduName,')), None)
    require(header is not None, 'Missing installed FlowFM property schema header')
    rows = list(csv.DictReader(io.StringIO('\n'.join(lines[header:]))))
    definitions = {}
    for key in ('geometry/waterlevini', 'physics/uniffrictcoef', 'time/dtmax'):
        section, name = key.split('/')
        matches = [row for row in rows if (row.get('MduGroup') or '').casefold() == section and (row.get('MduName') or '').casefold() == name]
        require(len(matches) == 1, 'Ambiguous/missing installed schema: ' + key)
        row = matches[0]
        require(row['Type'] == 'Double' and row['MduOnly'] == 'FALSE', 'Unsupported actual schema owner/type')
        unit = (row.get('Unit') or '').strip()
        require(unit == {'geometry/waterlevini': 'm', 'time/dtmax': 's',
                         'physics/uniffrictcoef': 'UnifFrictType: m(1/2)/s | s/m(1/3) | m'}[key], 'Unexpected installed unit metadata')
        definitions[key] = {'row': row, 'unit_raw': row.get('Unit'), 'unit_metadata': unit,
                            'owner': OWNER, 'definition': DEFINITION, 'value_declaring_type': DECLARING,
                            'data_type': 'System.Double', 'owner_path': 'model.ModelDefinition.GetModelProperty("' + row['MduName'] + '").Value'}
    return {'files': selected, 'definitions': definitions}


def authorization(target):
    """A distinct E014 authorization, never a P08 experiment declaration."""
    return {'schema': 1, 'purpose': KIND, 'disposable': True, 'independent_profile': True,
            'shared_profiles_disabled': True, 'target_identity_sha256': p08.digest(target)}


def validate_authorization(host, target, declaration, *, pending, bundle=None):
    if target is None:
        require(pending is True and host is None and declaration is None, 'Target identity/declaration must be supplied together')
    else:
        require(pending is False and host is not None, 'Missing E014 host/guest identity')
        require(type(declaration) is dict and type(declaration.get('schema')) is int
            and declaration == authorization(target) and all(declaration[k] is True for k in
            ('disposable', 'independent_profile', 'shared_profiles_disabled')), 'Require exact E014-purpose target-bound authorization; P08 authorization is not reusable')
        p08.load_identity(bundle).validate_distinct(host, target)


def prepare(project, install, out, *, manning_source, manning_original=None, host_identity=None, target=None, declaration=None):
    project, install, out, manning_source = map(plain, (project, install, out, manning_source))
    require(not out.exists(), 'Fresh output required')
    require(not out.is_relative_to(manning_source) and not manning_source.is_relative_to(out), 'Output overlaps Manning source')
    companion = plain(Path(str(project) + '_data'))
    mdus = list(companion.rglob('*.mdu'))
    require(len(mdus) == 1, 'Expected one original project MDU')
    expected_baseline(mdus[0].read_bytes(), 'chezy')
    inventory(companion)
    manning_inventory = inventory(manning_source)
    require(len(manning_inventory) == 10, 'Manning source must have exactly ten input files')
    expected_baseline((manning_source / 'f34.mdu').read_bytes(), 'manning')
    p08.model_references(manning_source / 'f34.mdu', manning_source)
    # Explicit two-token prerequisite only, no equivalence claim. The original
    # saved companion may differ in formatting from its first exported MDU.
    original_inventory = inventory(mdus[0].parent)
    require(set(original_inventory) == set(manning_inventory), 'Manning source input names differ')
    require(all(original_inventory[n] == manning_inventory[n] for n in original_inventory if n != 'f34.mdu'), 'Manning source non-MDU files differ')
    receipt = None
    if manning_original is None:
        receipt_path = plain(manning_source.parent / 'verification.json')
        receipt = p08.read_json(receipt_path)
        require(receipt['f34_manning_derivative']['hashes'] == {k: v['sha256'] for k, v in manning_inventory.items()}, 'Coordinator derivative receipt differs')
        manning_original = p08.inside(HERE.parents[3], receipt['original_f34_model_export']['path'])
        require(receipt['original_f34_model_export']['inputs'] == {k: v['sha256'] for k, v in inventory(manning_original).items()}, 'Original source receipt differs')
        receipt = {'path': str(receipt_path), 'sha256': p08.sha(receipt_path)}
    manning_original = plain(manning_original)
    require(not out.is_relative_to(manning_original) and not manning_original.is_relative_to(out), 'Output overlaps original source')
    source_proof = manning_seed(manning_original, manning_source)
    provenance = schema(install)
    if target is not None:
        host_identity = host_identity or p08.load_identity().probe()
    validate_authorization(host_identity, target, declaration, pending=target is None)
    # Closed registry owns the approved host/controller payload and prospective
    # Job trace closure. No P08 declaration or callback fallback is permitted.
    preparer = getattr(p08, 'prepare_export_guest', None)
    require(callable(preparer), 'Closed shared prepare_export_guest API not integrated; no fallback preparation')
    result = preparer(project, install, out, kind=KIND,
                      host_identity=host_identity, target=target, declaration=declaration)
    p08.copy_tree(manning_source, out / 'fixtures/manning')
    p08.copy_tree(manning_original, out / 'fixtures/chezy-original-export')
    for source, destination in ((ASSETS / 'host.py', 'host.py'), (ASSETS / 'fields_host.py', 'fields_host.py'), (HERE, 'fields_replay.py')):
        require(p08.sha(out / 'runtime' / destination) == p08.sha(source), 'Shared lifecycle packaged different E014 owner bytes: ' + destination)
    for source, destination in (('instructions.md', 'instructions.md'), ('provenance.json', 'provenance.json')):
        shutil.copyfile(ASSETS / source, out / 'runtime' / destination)
    contract = {'schema': 1, 'kind': KIND, 'cases': CASES, 'baseline': BASE, 'schema_provenance': provenance,
                'manning_prerequisite': {'source': str(manning_source), 'inputs': manning_inventory, 'source_proof': source_proof, 'coordinator_receipt': receipt,
                    'changes': {'physics/uniffricttype': ['0', '1'], 'physics/uniffrictcoef': ['65', '0.023']},
                    'equivalence_claimed': False, 'require_export_and_reopen_before_edit': True},
                'unit_notes': {'waterlevini': 'm; original f34 vertical datum undeclared, not invented here',
                               'dtmax': 's, independent of TUnit', 'manning': 's m-1/3 ONLY for law 1; source law 0/65 is Chezy'},
                'native_solver_execution': False, 'live_gui_clicks': 'unverified',
                'typed_owner_status': 'static_candidate_until_measured_in_guest'}
    p08.write_new(out / 'runtime/fields-contract.json', contract)
    record = p08.read_json(out / 'bundle.json')
    record.update(kind=KIND, isolation_purpose=KIND, host_identity=host_identity,
                  target_identity=target, declaration=declaration, guest_identity_pending=target is None,
                  expected='FM-only independent field controls, typed-owner measurements and actual exports/save/reopen; no DIMR exporter')
    record.pop('exporter', None)
    record['fields_project_export'] = {'kind': KIND, 'contract': 'runtime/fields-contract.json',
                                      'extra_suite': provenance['files'], 'manning_source': manning_inventory}
    record['files'] = inventory(out); record['files'].pop('bundle.json')
    (out / 'bundle.json').write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
    result.update(sha256=p08.sha(out / 'bundle.json'), fields_kind=KIND, instructions=str(out / 'runtime/instructions.md'),
                  status='prepared_guest_identity_pending' if target is None else 'prepared_disposable_guest_only',
                  readiness='NOT_READY_FOR_LIVE_RUN: disposable guest identity and exclusive lease required' if target is None else 'PREPARED_FOR_ASSIGNED_GUEST_ONLY',
                  prerequisite='Import authored Manning MDU into NEW project; unchanged exported AND reopened law 1 / coefficient 0.023 must pass before coefficient-only edit.',
                  live_gui_verified=False, native_solver_execution=False)
    result['runtime_verified'] = False
    result['authorization_purpose'] = KIND
    result['runner_hook_ready'] = all(callable(getattr(p08, name, None)) for name in
                                    ('prepare_export_guest', 'inspect_export_guest', 'run_export_guest'))
    result['typed_owner_status'] = 'static_candidate_until_measured_in_guest'
    if not result['runner_hook_ready']:
        result['readiness'] = 'NOT_READY_FOR_LIVE_RUN: closed shared lifecycle API requires coordinator review/integration; guest identity and lease remain required'
    inspect(out, result['sha256'])
    require(inventory(manning_source) == manning_inventory, 'Preparation changed Manning source')
    return result


def inspect(bundle, expected_sha):
    bundle = plain(bundle)
    inventory(bundle)
    inspector = getattr(p08, 'inspect_export_guest', None)
    require(callable(inspector), 'Closed shared inspect_export_guest API not integrated; old bundles are not upgraded')
    shared_record = inspector(bundle, expected_sha, kind=KIND)
    require(p08.sha(bundle / 'bundle.json') == expected_sha, 'Bundle manifest fingerprint differs')
    record = p08.read_json(bundle / 'bundle.json')
    require(record == shared_record, 'Shared/owner manifest inspection differs')
    require(record['schema'] == 1 and record['kind'] == KIND and record['native_started'] is False and record['engine_execution'] is False, 'Wrong E014 preparation record')
    require(record['isolation_purpose'] == KIND and re.fullmatch('[0-9a-f]{64}', record['nonce']), 'Wrong E014 isolation purpose/nonce; old bundles are not rewritten')
    validate_authorization(record['host_identity'], record['target_identity'], record['declaration'], pending=record['guest_identity_pending'], bundle=bundle)
    require('exporter' not in record, 'Unrelated P08 DIMR exporter contract refused')
    current = inventory(bundle); current.pop('bundle.json')
    require(current == record['files'], 'Bundle bytes added/removed/changed')
    require(not (bundle / 'runtime/p08-host.py').exists(), 'Unrelated P08 exporter host refused')
    project = p08.inside(bundle, record['project'])
    require(p08.sha(project) == record['source_project']['sha256'], 'Project byte hash differs')
    require(inventory(Path(str(project) + '_data')) == record['source_project']['companion'], 'Companion differs')
    extension = record.get('fields_project_export', {})
    require(extension.get('kind') == KIND, 'Wrong E014 bundle extension')
    contract = p08.read_json(p08.inside(bundle, extension['contract']))
    require(contract['schema'] == 1 and contract['kind'] == KIND and contract['cases'] == CASES, 'Changed field edit contract')
    require(extension['extra_suite'] == contract['schema_provenance']['files'], 'Suite schema fingerprint binding differs')
    require(p08.inventory(bundle / 'fixtures/manning') == extension['manning_source'], 'Manning fixture fingerprint differs')
    require(manning_seed(bundle / 'fixtures/chezy-original-export', bundle / 'fixtures/manning') == contract['manning_prerequisite']['source_proof'], 'Two-token prerequisite proof differs')
    return record


def verify_outputs(run, bundle=None, expected_sha=None):
    run = plain(run)
    inventory(run)
    require(not any((run / name).exists() for name in ('host-result.json', 'standard', 'dimr-1', 'dimr-2')), 'Unrelated P08 experiment artifacts refused')
    require(bundle is not None and expected_sha is not None, 'Pinned bundle required for E014 verification')
    bundle = plain(bundle); record = inspect(bundle, expected_sha)
    request = p08.read_json(run / 'request.json')
    result = p08.read_json(run / 'fields-result.json')
    require(request['nonce'] == record['nonce'] == result['nonce'] and request['kind'] == result['kind'] == KIND, 'Wrong E014 nonce/kind binding')
    require(request['engine_execution'] is False, 'Unexpected engine execution request')
    require(request['bundle_sha256'] == expected_sha and request['guest_lifecycle_sha256'] == p08.digest(record['guest_lifecycle']), 'Wrong E014 bundle/lifecycle request binding')
    require(result['bundle_sha256'] == expected_sha and result['guest_lifecycle_sha256'] == request['guest_lifecycle_sha256'], 'Wrong E014 bundle/lifecycle result binding')
    require(request['project_sha256'] == record['source_project']['sha256'] and request['companion_before'] == record['source_project']['companion'], 'Wrong copied project request binding')
    require(result['success'] is True and result['engine_execution'] is False and result['project_closed'] is True, 'Missing successful closed field workflow')
    require(result['contract_sha256'] == p08.sha(bundle / 'runtime/fields-contract.json'), 'Wrong host contract fingerprint')
    require(result['source_unchanged'] is True, 'Host observed source mutation')
    require(result['manning_prerequisite'] == {'exported_law': '1', 'exported_coefficient': '0.023',
        'reopened_law': '1', 'reopened_coefficient': '0.023', 'passed_before_any_coefficient_edit': True}, 'Missing pre-edit Manning prerequisite evidence')
    # Do not trust the host flag alone: verify copied original DB/companion again.
    require(p08.sha(p08.inside(run, request['project'])) == record['source_project']['sha256'], 'Original copied DB changed')
    require(p08.inventory(Path(str(p08.inside(run, request['project'])) + '_data')) == record['source_project']['companion'], 'Original copied companion changed')
    require(set(result['cases']) == set(CASES), 'Missing/extra field cases')
    prerequisite = run / 'manning-prerequisite'
    for phase in ('exported', 'reopened'):
        expected_baseline((prerequisite / phase / 'f34.mdu').read_bytes(), 'manning')
    preflight = compare_exports(prerequisite / 'exported', prerequisite / 'reopened')
    contract = p08.read_json(bundle / 'runtime/fields-contract.json')
    reports = {}
    for name, case in CASES.items():
        folder = run / 'cases' / name
        expected_baseline((folder / 'before/f34.mdu').read_bytes(), case['source'])
        entry = result['cases'][name]
        require(entry['source'] == case['source'] and entry['reopened'] is True, 'Wrong case source/reopen evidence')
        if case['key']:
            actual = entry['property']
            definition = contract['schema_provenance']['definitions'][case['key']]
            for key in ('owner', 'definition', 'value_declaring_type', 'data_type', 'owner_path', 'unit_metadata'):
                require(actual[key] == definition[key], 'Live property metadata mismatch: ' + key)
            require(actual['runtime_value_type'] == 'System.Double' and actual['section_key'] == case['key'], 'Wrong live type/section')
            require(actual['unit'] == case['unit'], 'Wrong selected physical unit')
            require(actual['owner_assembly']['sha256'] == contract['schema_provenance']['files'][FLOW]['sha256'], 'Wrong live property owner assembly')
            require(actual['value_assembly']['sha256'] == contract['schema_provenance']['files'][COMMON]['sha256'], 'Wrong live Value declaring assembly')
            require(actual['schema_file']['sha256'] == contract['schema_provenance']['files'][CSV]['sha256'], 'Wrong actual property schema file')
            require(decimal(entry['before']) == decimal(case['before']) and decimal(entry['after']) == decimal(case['after']) and decimal(entry['reopened_value']) == decimal(case['after']), 'Wrong typed readback')
        reports[name] = {'edit': compare_exports(folder / 'before', folder / 'after', key=case['key'],
                expected_before=case.get('before'), expected_after=case.get('after')),
            'reopen': compare_exports(folder / 'after', folder / 'reopened')}
        if case['source'] == 'manning':
            for phase in ('before', 'after', 'reopened'):
                require(decimal(value((folder / phase / 'f34.mdu').read_bytes(), 'physics/uniffricttype')[1]) == 1, 'Manning law changed')
        matched_control = run / 'cases' / ('control' if case['source'] == 'chezy' else 'manning-control') / 'before'
        reports[name]['matched_control'] = compare_exports(matched_control, folder / 'before')
        if case['source'] == 'manning':
            reports[name]['authored_prerequisite'] = compare_exports(prerequisite / 'reopened', folder / 'before')
    for extra in ('rejected', 'noop'):
        compare_exports(run / 'cases/control/before', run / 'cases/control' / extra)
    controls = result['controls']
    require(set(controls) == {'invalid_numeric', 'wrong_unit', 'wrong_owner', 'chezy_not_manning', 'unsupported_export_item', 'missing_export_path', 'noop'}, 'Missing negative/no-op controls')
    require(all(c.get('passed') is True for c in controls.values()), 'A negative/no-op control failed')
    require(controls['invalid_numeric']['mechanism'] == 'actual ModelProperty.SetValueFromString', 'Not a real property parser rejection')
    require(controls['invalid_numeric']['exception_type'] == 'System.FormatException', 'Unexpected actual parser exception')
    require(not list((run / 'negative-fm-item').rglob('*.mdu')), 'Rejected object emitted MDU')
    return {'state': 'passed_field_export_files_only', 'kind': KIND, 'cases': reports,
            'manning_prerequisite': preflight, 'negative_controls': controls, 'source_project_unchanged': True,
            'scope': 'Bounded console-hosted property/export/save/reopen; file verification alone is not live GUI evidence; no solver execution or physical equivalence.'}


def run_guest(bundle, expected_sha, install, out, *, slot=None, timeout=180):
    bundle, install, out = map(plain, (bundle, install, out))
    record = inspect(bundle, expected_sha)
    require(schema(install)['files'] == record['fields_project_export']['extra_suite'], 'Selected property DLL/schema changed')
    require(slot and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', slot), 'Exclusive native lease identifier required')
    require(record['target_identity'] is not None and record['guest_identity_pending'] is False, 'No independently identified disposable guest')
    runner = getattr(p08, 'run_export_guest', None)
    require(callable(runner), 'Closed shared run_export_guest API not integrated; no fallback native runner or P08 dummy success is permitted')
    return runner(bundle, expected_sha, install, out, kind=KIND, slot=slot, timeout=timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    for arg in ('project', 'install', 'out', 'manning-source'):
        prep.add_argument('--' + arg, type=Path, required=True)
    for arg in ('host-identity', 'target-identity', 'declaration'):
        prep.add_argument('--' + arg, type=Path)
    prep.add_argument('--manning-original', type=Path, help='Original ten-file Chezy export; otherwise require coordinator receipt beside Manning source')
    for action in ('inspect', 'verify', 'run-guest'):
        child = sub.add_parser(action); child.add_argument('--bundle', type=Path, required=True)
        child.add_argument('--expect-sha256', required=True)
        if action in ('verify', 'run-guest'): child.add_argument('--out', type=Path, required=True)
        if action == 'run-guest':
            child.add_argument('--install', type=Path, required=True); child.add_argument('--slot', required=True)
            child.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            result = prepare(args.project, args.install, args.out, manning_source=args.manning_source, manning_original=args.manning_original,
                host_identity=p08.read_json(args.host_identity) if args.host_identity else None,
                target=p08.read_json(args.target_identity) if args.target_identity else None,
                declaration=p08.read_json(args.declaration) if args.declaration else None)
        elif args.action == 'inspect':
            record = inspect(args.bundle, args.expect_sha256)
            result = {'state': 'prepared_files_verified', 'guest_identity_pending': record['guest_identity_pending'], 'native_started': False}
        elif args.action == 'verify': result = verify_outputs(args.out, args.bundle, args.expect_sha256)
        else: result = run_guest(args.bundle, args.expect_sha256, args.install, args.out, slot=args.slot, timeout=args.timeout)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if not result.get('state', '').startswith(('failed', 'timed_out', 'cleanup_failed')) else 6
    except Exception as exc:
        print(json.dumps({'state': 'refused_or_verification_failed', 'error': str(exc)}))
        return 6


if __name__ == '__main__':
    raise SystemExit(main())
