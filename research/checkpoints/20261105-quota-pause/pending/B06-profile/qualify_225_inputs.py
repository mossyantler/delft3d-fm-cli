"""Read-only admission of retained six public cases and original trace joins."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
runpy.run_path(str(HERE / 'candidate_cli.py'))
from dfm_cli import source_sink_run_profile as candidate


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


inputs_path = HERE.parent / 'B06-PUBLIC-G-inputs-01/input-manifest.json'
runs_path = HERE.parent / 'B06-PUBLIC-RUNNER-I-native-225-01/runs.json'
inputs = json.loads(inputs_path.read_text(encoding='utf-8'))
runs = json.loads(runs_path.read_text(encoding='utf-8'))
assert inputs['wheel_sha256'] == 'eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d'
held = {}
for case in inputs['cases']:
    for record in case['files'].values():
        path = Path(record['path'])
        assert sha(path) == record['sha256']
        held[str(path)] = record['sha256']
results, matrix = [], []
for case in inputs['cases']:
    path = Path(case['mdu'])
    for route in ('direct', 'dimr'):
        report, selected = candidate.native_preflight(path, 'source-sink', route=route)
        active = {f['relative_path'] for f in report['files']}
        unbound = sorted(set(case['files']) - active)
        assert len(active) == 6
        if case['operation'] != 'noop5':
            assert unbound == ['source.bc']
        else:
            assert unbound == []
        assert selected['checkpoint_schedule']['rst_interval_literal'] == '120 0 120'
        assert selected['checkpoint_schedule']['expected_seconds_since_refdate'] == [0, 120]
        results.append({'case_id': case['case_id'], 'route': route, 'active_input_files': sorted(active),
                        'inactive_source_files': unbound, 'input_sha256': selected['input_sha256'],
                        'status': 'static_admission_passed_native_not_launched'})
        if case['case_id'] in {'point_set15', 'pair_set15'}:
            reference = next(r['path'] for r in runs['runs'] if r['case_id'] == case['case_id'])
            matrix.append({'case_id': case['case_id'] + '_' + route, 'input_mdu': str(path), 'route': route,
                'profile': 'source-sink', 'reference_225': reference, 'native_status': 'unallocated_not_launched',
                'future_command_shape': ['dfm', 'run', 'start', str(path), '--profile', 'source-sink',
                    '--route', route, '--install', '<coordinator-selected-suite>', '--out', '<fresh-run-root>', '--timeout', '120'],
                'acceptance_owner': 'Mill independent gate; 170 arrays/units/masks/attrs/time vs225, original Job/CloseHandle proof',
                'launch_authorized': False})
trace_results = []
for row in runs['runs']:
    receipt_path = Path(row['path']) / 'runner-receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    passed = candidate.notifications_complete(receipt['normal_exit']['member_trace'])
    assert passed
    trace_results.append({'case_id': row['case_id'], 'receipt_sha256': sha(receipt_path),
                          'source_family_notification_bijection': 'passed',
                          'scope': 'Offline replay of the new pure subset guard only, not a new engine or full terminal verdict.'})
assert all(sha(Path(p)) == h for p, h in held.items())
report = {'kind': 'author-read-only-225-admission', 'passed': True, 'inputs_manifest_sha256': sha(inputs_path),
    'cases': results, 'original_inputs_unchanged': len(held), 'retained_trace_join_checks': trace_results,
    'native_launches': 0, 'GUI_launches': 0, 'original_225_evidence_edited': False,
    'limitations': 'Static admission and raw-notification join compatibility only; both public run routes remain native-unverified.'}
(HERE / 'retained225-admission.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
(HERE / 'native-proposal.json').write_text(json.dumps({'state': 'proposal-only-no-launch-authorization',
    'minimum_matrix': matrix, 'additional_scope': 'No inherited noop/add/C5 or DIMR scientific coverage from flags.'}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'static_admissions': len(results), 'retained_traces': len(trace_results), 'unchanged_inputs': len(held), 'native_launches': 0}))
