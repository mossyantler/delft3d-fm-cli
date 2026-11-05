"""Frozen121 corpus on actual independently installed wheel, no product overlay."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / 'SHORT-CLOSE-V-rev03-20261105-01'


def main():
    assert sys.flags.isolated and sys.dont_write_bytecode
    from dfm_cli import run_pump_lifecycle as lifecycle
    path = Path(lifecycle.__file__).resolve()
    assert path.is_relative_to(HERE / 'runtime-venv/Lib/site-packages/dfm_cli')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '49c4a6ed29b64b08342f15c76e05e4b4b7ee64379c1b237bd62d363781e68207'
    spec = importlib.util.spec_from_file_location('independent_frozen_installed_adapter', CORPUS / 'adapter.py')
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    result = adapter.run(lifecycle.native_cleanup_evidence,
        expected_freeze_sha256='a552881986d8e8de917a20c12cf6d5c705fac209c18f48e4505898033b4203d9',
        out=CORPUS / 'replay-package-f7eb-V-01')
    report = {'state': result['state'], 'cases': result['case_count'], 'failures': result['failures'],
              'actual_installed_helper': str(path), 'actual_helper_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'native_launches': 0, 'PID_queries': 0, 'original_states_reclassified': False,
              'scope': 'Installed wheel pure component; source/schema/unit/native scopes remain distinct.'}
    with (HERE / 'installed-component-01.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=2)
    print(json.dumps(report))
    return 0 if result['failures'] == 0 else 1


if __name__ == '__main__': raise SystemExit(main())
