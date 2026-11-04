"""Public, independent restart forecast gate over RETAINED native calculations.

No engine launcher or product import. Negative copies are labelled tampered test
fixtures, not new native evidence. Their output hashes are refreshed deliberately
so a refusal tests arrays/schema rather than just stale file fingerprints.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import traceback

from . import verify_restart_diagnostics as oracle

ROLES = ('continuous', 'first', 'resumed', 'cold-tail')
CONTRACT = 'saved-forecast-v1'


class PublicCLI:
    def __init__(self, folder):
        self.folder = Path(folder); self.folder.mkdir(parents=True, exist_ok=False)
        self.calls = []

    def invoke(self, *args):
        # Explicit allow-list makes this archived-data tool unable to launch an
        # engine even if a future caller accidentally supplies run/start args.
        oracle.require(tuple(map(str, args[:2])) in (('schema', 'inspect'), ('restart', 'compare'), ('restart', 'forecast')),
                       'This verifier may only invoke read-only public commands')
        argv = [sys.executable, '-B', '-m', 'dfm_cli', *map(str, args)]
        completed = subprocess.run(argv, cwd=oracle.ROOT, capture_output=True, timeout=90)
        index = len(self.calls)
        stdout, stderr = [self.folder / (f'{index:03d}' + suffix) for suffix in ('.stdout.json', '.stderr.txt')]
        stdout.write_bytes(completed.stdout); stderr.write_bytes(completed.stderr)
        call = {'argv': argv, 'returncode': completed.returncode, 'stdout': str(stdout), 'stderr': str(stderr)}
        self.calls.append(call)
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, UnicodeError):
            raise AssertionError('Public CLI did not emit a JSON object: ' + str(call))
        oracle.require(isinstance(payload, dict), 'Public JSON must be an object')
        oracle.require(payload.get('protocol_version') == 2 and payload.get('ok') == (completed.returncode == 0), 'Public protocol/exit disagreement')
        body = payload.get('result') if completed.returncode == 0 else payload.get('error')
        oracle.require(isinstance(body, dict), 'Missing public result/error object')
        return completed.returncode, body


def relative(record, value):
    """Independently resolve a relocated archived manifest's output references."""
    win = PureWindowsPath(value)
    if win.drive or win.root:
        return win.relative_to(PureWindowsPath(record['run_directory'])).as_posix()
    path = Path(value)
    return path.relative_to(record['run_directory']).as_posix() if path.is_absolute() else value.replace('\\', '/')


def refresh_output_hashes(run):
    """Only copied output metadata changes; inputs/parent receipt stay intact."""
    path = run / 'manifest.json'; record = json.loads(path.read_text())
    for item in record['outputs']:
        output = run / relative(record, item['path'])
        item['sha256'] = oracle.sha(output); item['bytes'] = output.stat().st_size
    axes = list(record['verification']['axes'].values()) + record['verification']['restart_axes']
    for item in axes: item['sha256'] = oracle.sha(run / relative(record, item['path']))
    oracle.write_json(path, record)


def clone_trial(trial, destination):
    destination.mkdir(parents=True, exist_ok=False)
    for name in ROLES: shutil.copytree(trial / 'runs' / name, destination / 'runs' / name)
    shutil.copyfile(trial / 'tolerances.predeclared.json', destination / 'tolerances.predeclared.json')
    oracle.write_json(destination / 'NEGATIVE-FIXTURE.json', {
        'kind': 'copied archived arrays for deliberate black-box perturbation; NOT a native calculation',
        'source': str(trial), 'source_manifest_hashes': {r: oracle.sha(trial / 'runs' / r / 'manifest.json') for r in ROLES},
        'native_started': False})
    return destination


def mutate(trial, case):
    """Predeclared edits, fixed magnitudes; no thresholds inferred from results."""
    from netCDF4 import Dataset
    import numpy as np
    run = trial / 'runs' / ('cold-tail' if case == 'cold_not_discriminating' else 'resumed')
    path = run / 'model/output/model_map.nc'; field = 'mesh2d_s1'
    evidence = {'case': case, 'path': str(path), 'thresholds_changed': False}
    if case in ('final_state', 'final_state_inside_old_tolerance'):
        path = oracle.find_checkpoint(run, 240); field = 's1'
    if case == 'cut_checkpoint_input': path = run / 'model/restart-state_rst.nc'; field = 's1'
    if case == 'unlisted_advanced': field = 'mesh2d_Numlimdt'
    if case in ('advanced_diagnostic', 'initial_exception_mask'):
        field = 'mesh2d_viu'
    if case in ('counter_unexplained', 'interval_bounds'):
        path = run / 'model/output/model_his.nc'
        field = 'water_balance_storage' if case == 'counter_unexplained' else 'time_bds'
    with Dataset(path, 'r+') as ds:
        if case == 'unknown_inventory':
            v = ds.createVariable('independent_unregistered_forecast_field', 'f8', ('time',)); v.units = '1'; v[:] = 7
            evidence.update(field=v.name, mutation='New unregistered field on resumed output only; inventory mismatch must refuse')
        elif case == 'cold_not_discriminating':
            with Dataset(trial / 'runs/resumed/model/output/model_map.nc') as hot:
                for name in ('mesh2d_s1', 'mesh2d_ucx', 'mesh2d_ucy'): ds[name][0] = hot[name][0]
            evidence['mutation'] = 'Cold control initial physical observations replaced by hot observations'
        elif case == 'units':
            evidence.update(field=field, before=ds[field].units, after='cm'); ds[field].units = 'cm'
        elif case == 'clock':
            evidence.update(field='time', index=1, before=float(ds['time'][1]), after=float(ds['time'][1]) + 1)
            ds['time'][1] += 1
        else:
            v = ds[field]; row = 0 if case in ('cut_state', 'final_state', 'final_state_inside_old_tolerance', 'cut_checkpoint_input', 'initial_exception_mask') else 1
            values = np.ma.asarray(v[row]); indices = np.argwhere(~np.ma.getmaskarray(values))
            oracle.require(indices.size or values.ndim == 0, 'Need an unmasked perturbation target')
            index = tuple(indices[0]) if values.ndim else ()
            target = (row, *index); before = float(v[target])
            if case in ('mask', 'initial_exception_mask'):
                v[target] = np.ma.masked; after = 'MISSING'
            else:
                after = float(np.nextafter(np.asarray(before, dtype=v.dtype), np.asarray(np.inf, dtype=v.dtype))) if case in ('advanced_inside_old_tolerance', 'final_state_inside_old_tolerance') else before + (1 if case in ('counter_unexplained', 'interval_bounds', 'unlisted_advanced') else .01)
                v[target] = after
            evidence.update(field=field, index=[int(i) for i in target], before=before, after=after)
    refresh_output_hashes(run)
    evidence.update(path=str(path), changed_sha256=oracle.sha(path), copied_manifest_sha256=oracle.sha(run / 'manifest.json'))
    oracle.write_json(trial / 'perturbation.json', evidence)
    return evidence


def arguments(trial, *, forecast=False):
    args = ['restart', 'forecast' if forecast else 'compare', *[trial / 'runs' / role for role in ROLES[:3]],
            '--tolerances', trial / 'tolerances.predeclared.json']
    if forecast: args += ['--cold-control', trial / 'runs/cold-tail', '--contract', CONTRACT]
    return args


def report_body(payload):
    # Protocol 2 errors carry the full failed scientific report under details.
    return payload.get('details', payload)


def raw_gate(cli, trial, independent):
    code, payload = cli.invoke(*arguments(trial))
    oracle.require(code == 6 and payload.get('code') == 'restart_numerical_mismatch', 'Frozen all-fields raw comparator must still exit 6')
    body = report_body(payload)
    raw = body['raw_native_equivalence']
    oracle.require(raw['state'] == 'failed', 'Raw failure was promoted')
    for kind, key in (('history', 'failed_history'), ('map', 'failed_map')):
        oracle.require(set(raw[key]) == set(independent['traces'][kind]['raw_failed_fields']), 'Public raw verdict differs from independent arrays')
    return {'returncode': code, 'error': payload['code'], 'raw_verdict': raw, 'full_original_result': body}


def positive_gate(cli, trial, independent, original_raw):
    code, payload = cli.invoke(*arguments(trial, forecast=True))
    failure = report_body(payload)
    summary = {kind: failure.get('saved_' + kind, {}).get('failed_fields') for kind in ('history', 'map')}
    oracle.require(code == 0, 'Retained matched native forecast rejected: ' + str({'returncode': code, 'code': payload.get('code'), 'failed_fields': summary}))
    # The public response schema is intentionally explicit. Adapt this adapter
    # only to the published schema, never alter the independent expected arrays.
    oracle.require(payload.get('state') == 'passed' and payload.get('contract') == CONTRACT, 'Missing named forecast verdict')
    raw = payload['raw_native_equivalence']
    oracle.require(raw['state'] == 'failed', 'Optional forecast must retain raw diagnostic failures')
    oracle.require(payload.get('native_equivalence_promoted') is False, 'Raw native equivalence must never be promoted')
    oracle.require(payload['original_raw_result'] == original_raw, 'Optional route changed the attached default raw report')
    oracle.require(payload['original_raw_command']['exit_code'] == 6, 'Attached raw command exit must remain 6')
    initial = payload['initialization_and_cold_control']
    oracle.require(initial['passed'] and initial['checkpoint_encoded_initialization_exact'], 'Missing actual file-state initialization gate')
    oracle.require(initial['measured_level_separation_m'] == independent['initial_state_encoding']['s1']['resumed_vs_cold_max_difference'], 'Cold separation differs from raw independent observation')
    final = payload['final_all_native_state_exact']
    oracle.require(final['passed'] and set(final['variables']) == set(independent['final_checkpoints']['variables']), 'Final all-state coverage differs')
    for kind, key in (('history', 'failed_history'), ('map', 'failed_map')):
        oracle.require(set(raw[key]) == set(independent['traces'][kind]['raw_failed_fields']), 'Forecast lost original raw field failures')
        observed = payload['saved_' + kind]
        expected = independent['traces'][kind]
        oracle.require(observed['passed'] and set(observed['variables']) == set(expected['variables']), 'Saved-field inventory differs from independent NetCDF')
        for name, detail in observed['variables'].items():
            if name not in oracle.COUNTERS and 'advanced_exact' in detail:
                oracle.require(detail['advanced_exact']['passed'] and detail['advanced_exact']['stored_value_exact'], 'Advanced field was accepted by a tolerance: ' + name)
        for name, precision in expected['counters'].items():
            actual = observed['diagnostic_views'][name]['interval_reset']
            for metric in ('consistent_with_one_shared_origin_and_stored_precision', 'feasible_offset_interval_exact',
                           'interval_endpoint_inclusive', 'interval_reset_residual_exact', 'interval_reset_exact',
                           'interval_reset_max_abs_residual', 'native_equality_proven', 'acceptance_tolerances_changed'):
                oracle.require(actual[metric] == precision[metric], 'Public diagnostic precision differs from independent oracle: ' + name + '/' + metric)
        check_native_views(trial, kind, observed['diagnostic_views'])
    return {'returncode': code, 'state': payload['state'], 'contract': payload['contract'], 'raw_state': raw['state']}


def check_native_views(trial, kind, views):
    """Returned diagnostic values/masks/units must literally retain native data."""
    from netCDF4 import Dataset
    import numpy as np
    suffix = 'his' if kind == 'history' else 'map'
    for role in ROLES[:3]:
        with Dataset(trial / 'runs' / role / f'model/output/model_{suffix}.nc') as ds:
            for name, details in views.items():
                key = role if role in details else 'earlier_cut' if role == 'first' else 'resumed_initial' if role == 'resumed' else None
                if key is None: continue
                view = details[key]
                oracle.require(isinstance(view, dict), 'Raw diagnostic view is missing literal data')
                values = np.ma.asarray(ds[name][:] if key == role else ds[name][-1 if role == 'first' else 0])
                oracle.require(view['values'] == values.tolist() and view['mask'] == np.ma.getmaskarray(values).tolist(), 'Diagnostic raw data/masks changed in report: ' + name)
                oracle.require(view['units'] == getattr(ds[name], 'units', None) and view['dtype'] == str(ds[name].dtype), 'Diagnostic units/dtype changed in report')


def negative_reason(payload, case, perturbation):
    """Refusal must detect THIS edit, not an unrelated existing raw failure."""
    body = report_body(payload); code = payload.get('code')
    if case in ('unknown_inventory', 'units'):
        return code in ('restart_forecast_schema', 'restart_comparison_schema'), 'schema/field semantics refusal'
    if case == 'cut_checkpoint_input':
        return code in ('restart_input_changed', 'stale_preview'), 'actual checkpoint input fingerprint refusal'
    if case == 'clock':
        return code == 'incomplete_output' and body.get('path') == perturbation['path'], 'actual advanced CF schedule refusal on the edited file'
    if code != 'restart_forecast_mismatch': return False, 'expected supported saved-forecast numerical mismatch'
    if case == 'cold_not_discriminating':
        detail = body.get('initialization_and_cold_control', {})
        return detail.get('passed') is False and detail.get('measured_level_separation_m') == 0, 'measured hot/cold level separation lost'
    if case in ('final_state', 'final_state_inside_old_tolerance'):
        detail = body.get('final_all_native_state_exact', {}).get('variables', {}).get('s1', {})
        return detail.get('passed') is False, 'exact final s1 comparison failed'
    kind = 'history' if perturbation['path'].endswith('_his.nc') else 'map'
    detail = body.get('saved_' + kind, {}).get('variables', {}).get(perturbation['field'], {})
    return detail.get('passed') is False, kind + '/' + perturbation['field'] + ' specifically failed'


CASES = ('advanced_state', 'advanced_inside_old_tolerance', 'cut_state', 'mask',
         'unknown_inventory', 'unlisted_advanced', 'advanced_diagnostic', 'initial_exception_mask',
         'interval_bounds', 'counter_unexplained', 'final_state', 'final_state_inside_old_tolerance',
         'cut_checkpoint_input', 'units', 'clock', 'cold_not_discriminating')


def exercise(trials, out):
    before = {str(t): oracle.fingerprints(t) for t in trials}
    source_paths = sorted((oracle.ROOT / 'src/dfm_cli').glob('restart*.py'))
    code_before = {str(p): oracle.sha(p) for p in source_paths}
    cli = PublicCLI(out / 'commands'); results = []; failures = []
    report = {'status': 'failed_public_forecast_gate', 'native_started': False,
              'contract': CONTRACT, 'verifier_sha256': oracle.sha(Path(__file__)),
              'oracle_sha256': oracle.sha(Path(oracle.__file__)), 'calls': cli.calls,
              'product_source_sha256_before': code_before,
              'trials': results, 'failures': failures,
              'negative_fixture_policy': 'Copied outputs deliberately edited and copied output hashes refreshed; never presented as native calculations'}
    try:
        code, schema = cli.invoke('schema', 'inspect'); oracle.require(code == 0, 'Public schema unavailable')
        registered = 'restart forecast' in schema['commands']; report['forecast_registered'] = registered
        for i, trial in enumerate(trials):
            oracle.require(oracle.sha(trial / 'tolerances.predeclared.json') == oracle.POLICY_SHA, 'Frozen original policy differs')
            independent = oracle.investigate(trial)
            oracle.require(independent['conclusion']['independent_saved_forecast_array_gates_passed'], 'Retained positive fails independent saved-forecast array gates')
            item = {'source': str(trial), 'independent': independent, 'negative_fixtures': []}; results.append(item)
            item['raw_public'] = raw_gate(cli, trial, independent)
            if not registered: continue
            try: item['forecast_public'] = positive_gate(cli, trial, independent, item['raw_public']['full_original_result'])
            except Exception as exc: failures.append({'trial': str(trial), 'case': 'positive', 'error': str(exc)})
            for case in CASES:
                fixture = clone_trial(trial, out / 'negative-fixtures' / f'trial-{i:02d}' / case)
                entry = {'fixture': str(fixture), 'perturbation': mutate(fixture, case)}; item['negative_fixtures'].append(entry)
                fixture_before = oracle.fingerprints(fixture)
                code, payload = cli.invoke(*arguments(fixture, forecast=True))
                reason, explanation = negative_reason(payload, case, entry['perturbation'])
                entry.update(returncode=code, code=payload.get('code'), refused=code in (4, 6), unchanged=oracle.fingerprints(fixture) == fixture_before,
                             intended_perturbation_detected=reason, detection=explanation)
                if not entry['refused'] or not entry['unchanged'] or not reason:
                    failures.append({'trial': str(trial), 'case': case, 'error': 'Perturbation accepted, unsupported CLI, or input mutated', 'result': entry})
                elif payload.get('code') in ('internal_error', 'usage'):
                    failures.append({'trial': str(trial), 'case': case, 'error': 'Refusal did not reach a supported contract check'})
        if not registered: report['status'] = 'public_forecast_not_registered_raw_gate_preserved'
        elif not failures: report['status'] = 'passed_archived_public_saved_forecast_and_negative_gate'
    except Exception as exc:
        failures.append({'error': str(exc), 'traceback': traceback.format_exc()})
    finally:
        report['retained_trials_unchanged'] = all(oracle.fingerprints(t) == before[str(t)] for t in trials)
        report['product_source_sha256_after'] = {str(p): oracle.sha(p) for p in source_paths}
        report['restart_product_code_unchanged_during_gate'] = report['product_source_sha256_after'] == code_before
        if not report['restart_product_code_unchanged_during_gate']:
            report['status'] = 'failed_product_changed_during_gate'; failures.append({'error': 'Restart product code changed during gate; repeat after freeze'})
        if not report['retained_trials_unchanged']:
            report['status'] = 'failed_archived_evidence_changed'; failures.append({'error': 'Historical evidence changed'})
        oracle.write_json(out / 'verification.json', report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trial', type=Path, action='append', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv); out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    report = exercise([t.resolve() for t in a.trial], out)
    print(json.dumps({'status': report['status'], 'failures': report['failures'], 'native_started': False,
                      'verification': str(out / 'verification.json')}, indent=2))
    return 0 if report['status'].startswith('passed_') else 2 if report['status'].startswith('public_forecast_not_registered') else 1


if __name__ == '__main__': raise SystemExit(main())
