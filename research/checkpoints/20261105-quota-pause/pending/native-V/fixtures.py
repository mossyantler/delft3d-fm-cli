"""Own tests: untouched227 originals or explicitly SYNTHETIC observer records.

No legacy classifier, product predicate, process query or launcher is imported.
"""
import copy
import json
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HISTORICAL = ROOT / 'research/experiments/SHORT-CLOSE-G-native-227-01'


def original(name):
    return json.loads((HISTORICAL / name / 'manifest.json').read_bytes())


def expected(record):
    return {k: copy.deepcopy(record[k]) for k in
            ('route', 'argv', 'working_directory', 'run_directory', 'executable_sha256', 'profile_name')}


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def observer_bundle(target, control):
    """Metadata-only positive fake: never observed survivor/native proof."""
    from raw_audit import stamp
    request = stamp(target['termination']['termination_request']['started_at_utc'])
    terminal = stamp(target['ownership']['job_close']['finished_at_utc'])
    cleanup = stamp(control['termination']['termination_request']['started_at_utc'])
    finished = stamp(control['ownership']['job_close']['finished_at_utc'])
    assert terminal < cleanup
    ids = {'target': 'c' * 32, 'control': 'd' * 32}
    def sample(which, state, time):
        rec = target if which == 'target' else control
        ident = rec['ownership']['native_identity']
        return dict(observer_id=ids[which], pid=ident['pid'], creation_time_100ns=ident['creation_time_100ns'],
                    image=rec['argv'][0], state=state, in_a_job=True,
                    observed_at_utc=time.isoformat(), monotonic_ns=int(time.timestamp() * 1e9),
                    source='independent_retained_Windows_query_and_synchronize_handle',
                    handle_relation='NOT_native_Popen', membership_scope='any_Job_only_NOT_exact_private_Job',
                    SYNTHETIC_FIXTURE_NOT_OBSERVED=True)
    values = {'schema': 'SHORT-CLOSE-NATIVE-V-control-observations-2',
              'target_case_id': Path(target['run_directory']).name,
              'target_before': sample('target', 'live', request - timedelta(milliseconds=20)),
              'target_exit': sample('target', 'exited', terminal + timedelta(milliseconds=1)),
              'control_before': sample('control', 'live', request - timedelta(milliseconds=30)),
              'control_after': sample('control', 'live', terminal + timedelta(milliseconds=1)),
              'control_pre_cleanup': sample('control', 'live', cleanup - timedelta(milliseconds=1)),
              'control_final': sample('control', 'exited', finished + timedelta(milliseconds=1))}
    for which, key in [('target', 'target_exit'), ('control', 'control_final')]:
        last = values[key]
        t = stamp(last['observed_at_utc']) + timedelta(milliseconds=1)
        raw = dict(api='CloseHandle', source='independent_retained_observer_handle',
                   observer_id=ids[which], identity=copy.deepcopy((target if which == 'target' else control)['ownership']['native_identity']),
                   image=last['image'], succeeded=True, return_type='int', return_value=1,
                   started_at_utc=t.isoformat(), finished_at_utc=t.isoformat(), observed_at_utc=t.isoformat())
        values[which + '_observer_close'] = {'final_snapshot': copy.deepcopy(last), 'close': raw}
    return values
