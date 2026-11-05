"""Correct G-only synthetic identity type; retain initial harness failures."""
from pathlib import Path
import importlib.util
import hashlib
import json

HERE = Path(__file__).resolve().parent
path = HERE / 'snapshot-raw_audit.py'
spec = importlib.util.spec_from_file_location('interface_snapshot', path)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
oid = 'a' * 32
identity = {'pid': 1234, 'creation_time_100ns': '123456789'}
exe = r'C:\synthetic\dflowfm-cli.exe'
sample = dict(identity, observer_id=oid, image=exe, state='exited', in_a_job=None,
              observed_at_utc='2001-01-01T00:00:01+00:00', monotonic_ns=10,
              source='independent_retained_Windows_query_and_synchronize_handle')
close = dict(api='CloseHandle', source='independent_retained_observer_handle',
             observer_id=oid, identity=identity, image=exe, attempted=True,
             return_value=1, return_type='int', succeeded=True,
             started_at_utc='2001-01-01T00:00:02+00:00',
             finished_at_utc='2001-01-01T00:00:02.002+00:00')
outcomes = []
for label, observed in [('adapter_pre_call_observation', '2001-01-01T00:00:02.001+00:00'),
                        ('post_call_observation_control', '2001-01-01T00:00:02.003+00:00')]:
    raw = dict(close, observed_at_utc=observed)
    try:
        v.observer_close({'final_snapshot': sample, 'close': raw}, oid,
                         v.birth(identity), exe, v.stamp(sample['observed_at_utc']))
        result = {'case': label, 'accepted': True}
    except Exception as exc:
        result = {'case': label, 'accepted': False, 'error': str(exc)}
    outcomes.append(result)
assert outcomes[0]['accepted'] is False and outcomes[1]['accepted'] is True
record = {'state': 'cancelled', 'route': 'direct', 'profile_name': 'short', 'termination': {}}
for allowed in (['cancelled', 'completed', 'failed'], ['cancelled', 'completed']):
    result = v.assert_public_state(record, {'family': 'control', 'route': 'direct',
                 'allow_natural_race': True, 'control_terminal_states': allowed})
    outcomes.append({'case': 'declared_control_states', 'allowed': allowed, 'result': result})
assert outcomes[2]['result']['passed'] is False and outcomes[3]['result']['passed'] is True
result = {'state': 'TWO_PROSPECTIVE_INTERFACE_MISMATCHES_WITH_POSITIVE_CONTROLS',
          'raw_audit_snapshot_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
          'outcomes': outcomes, 'native_launches': 0, 'root_product_writes': 0,
          'initial_harness_failure': 'verification.json retained: initial G-only synthetic creation time used int instead of observed string; not candidate failure',
          'scope': 'Synthetic integration semantics only, no frozen candidate or native defect verdict.'}
with (HERE / 'verification-02.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
