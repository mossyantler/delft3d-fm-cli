"""Continue after V probe-name repair; no new installation or package rebuild."""
import json
from pathlib import Path
import audit_runtime as a


def main():
    before = a.check_freeze(); root_before = a.source_snapshot()
    a.need(a.sha(a.WHEEL) == a.WHEEL_SHA, 'wheel differs')
    dependency = a.HERE.parent / 'SHORT-CLOSE-PACK-I-rev04-PLAN-20261105-01/dependency-wheel-inputs.json'
    a.need(a.sha(dependency) == 'e93b5a6c5728f07823b27da153f5a36a48469119bec1c5800f87b14f1ba4ff06', 'dependency pin differs')
    locked = json.loads(dependency.read_bytes())['wheels']; wheels = []
    for name in a.RUNTIME_NAMES:
        p = Path(locked[name]['path']); a.need(a.sha(p) == locked[name]['sha256'], 'wheel differs'); wheels.append(p)
    prefix = a.HERE / 'runtime-venv'; cwd = a.HERE / 'outside-checkout-cwd'
    a.need(prefix.is_dir() and cwd.is_dir(), 'original fresh runtime missing')
    own = a.probe(prefix, 'V-clean-02', cwd)
    actual_I = a.probe(a.I / 'build-01/runtime-venv', 'I-frozen-01', cwd)
    a.need(own['schema'] == actual_I['schema'], 'I/V schemas differ')
    equal = {name: a.wheel_payload_equal(prefix, path) for name, path in zip(a.RUNTIME_NAMES, wheels)}
    equal['product'] = a.wheel_payload_equal(prefix, a.WHEEL)
    a.command('V-pip-check', [prefix / 'Scripts/python.exe', '-I', '-B', '-m', 'pip', '--isolated', 'check', '--disable-pip-version-check'],
              cwd, a.clean_env(a.HERE / '.absent-pipcheck-cache'))
    a.need(a.check_freeze() == before, 'I packet drifted'); a.need(a.source_snapshot() == root_before, 'root changed')
    report = {'state': 'PASSED_INDEPENDENT_CLEAN_RUNTIME_ORIGINS_RECORD_AND_SCHEMA', 'package_freeze_sha256': a.FREEZE,
              'wheel_sha256': a.WHEEL_SHA, 'V_runtime': own, 'I_runtime': actual_I, 'locked_wheel_payload_files_equal': equal,
              'I_frozen_packet_unchanged': True, 'root_product_unchanged': True, 'native_engine_launches': 0,
              'checker_error_retained': 'checker-repair-01.json', 'new_installations_this_continuation': 0,
              'commands_scope': 'Only source-only origin probes, actual public schema and pip check; no model/native preparation or execution.'}
    with (a.HERE / 'runtime-verification-01.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=2)
    print(json.dumps({'state': report['state'], 'V_product': len(own['191_product_hashes']), 'I_product': len(actual_I['191_product_hashes']), 'runtime_distributions': 7}))


if __name__ == '__main__': main()
