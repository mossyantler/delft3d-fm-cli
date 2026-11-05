"""Pure prospective adapter/auditor interface probes; no native APIs."""
from pathlib import Path
import importlib.util
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V = ROOT / 'research/experiments/SHORT-CLOSE-NATIVE-V-rev04-20261105-01/raw_audit.py'
I = ROOT / 'research/experiments/SHORT-CLOSE-NATIVE-I-rev04-20261105-01/public_driver.py'
ADAPTER = I.with_name('replay_adapter.py')
pins = {}
for path in (V, I, ADAPTER):
    raw = path.read_bytes()
    snapshot = HERE / ('snapshot-' + path.name)
    with snapshot.open('xb') as stream:
        stream.write(raw)
    pins[str(path)] = hashlib.sha256(raw).hexdigest()
spec = importlib.util.spec_from_file_location('raw_interface_snapshot', HERE / 'snapshot-raw_audit.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
oid = 'a' * 32
identity = {'pid': 1234, 'creation_time_100ns': 123456789}
exe = r'C:\synthetic\dflowfm-cli.exe'
sample = dict(identity, observer_id=oid, image=exe, state='exited', in_a_job=None,
              observed_at_utc='2001-01-01T00:00:01+00:00', monotonic_ns=10,
              source='independent_retained_Windows_query_and_synchronize_handle')
close = dict(api='CloseHandle', source='independent_retained_observer_handle',
             observer_id=oid, identity=identity, image=exe, attempted=True,
             return_value=1, return_type='int', succeeded=True,
             started_at_utc='2001-01-01T00:00:02+00:00',
             observed_at_utc='2001-01-01T00:00:02.001+00:00',
             finished_at_utc='2001-01-01T00:00:02.002+00:00')
outcomes = []
for label, observed in [('adapter_pre_call_observation', close['observed_at_utc']),
                        ('post_call_observation_control', '2001-01-01T00:00:02.003+00:00')]:
    raw = dict(close, observed_at_utc=observed)
    try:
        v.observer_close({'final_snapshot': sample, 'close': raw}, oid,
                         v.birth(identity), exe, v.stamp(sample['observed_at_utc']))
        result = {'case': label, 'accepted': True}
    except Exception as exc:
        result = {'case': label, 'accepted': False, 'error': str(exc)}
    outcomes.append(result)
record = {'state': 'cancelled', 'route': 'direct', 'profile_name': 'short', 'termination': {}}
expectation = {'family': 'control', 'route': 'direct', 'allow_natural_race': True,
               'control_terminal_states': ['cancelled', 'completed', 'failed']}
outcomes.append({'case': 'adapter_declared_control_states',
                 'result': v.assert_public_state(record, expectation)})
result = {'state': 'PROSPECTIVE_INTERFACE_MISMATCHES_OBSERVED_NOT_NATIVE_FAILURE',
          'source_snapshot_sha256': pins, 'outcomes': outcomes, 'native_launches': 0,
          'root_product_writes': 0,
          'scope': 'Synthetic source-declared timestamp ordering and control expectation only; candidates still mutable, not a frozen final verdict.'}
(HERE / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, indent=2))
