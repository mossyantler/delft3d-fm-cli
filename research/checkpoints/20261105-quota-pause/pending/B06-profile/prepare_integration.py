"""Stage three shared-file deltas only; never clone or mutate the frozen root."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE / 'shared-base'
TARGET = HERE / 'overlay/src/dfm_cli'
BASE.mkdir(exist_ok=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


files = sorted((ROOT / 'src/dfm_cli').rglob('*.py')) + [ROOT / 'src/dfm_cli/fields_registry.json']
pins = [{'path': str(p), 'relative_path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in files]
assert len(pins) == 191, f'Expected reviewed 191-file product, got {len(pins)}'
(HERE / 'base191-pins.json').write_text(json.dumps({'files': pins}, indent=2) + '\n', encoding='utf-8')
patch = ''
for name in ('runs.py', 'run_pump_lifecycle.py', 'cli.py'):
    raw = (ROOT / 'src/dfm_cli' / name).read_bytes()
    (BASE / name).write_bytes(raw)
    old = raw.decode('utf-8').replace('\r\n', '\n')
    new = old
    if name == 'runs.py':
        new = new.replace('network, pump_run_profile, weir_run_profile', 'network, pump_run_profile, weir_run_profile, source_sink_run_profile')
        new = new.replace('(network, layers, morph, pump_run_profile, weir_run_profile)', '(network, layers, morph, pump_run_profile, weir_run_profile, source_sink_run_profile)')
        new = new.replace('in (pump_run_profile, weir_run_profile)', 'in (pump_run_profile, weir_run_profile, source_sink_run_profile)')
        new = new.replace('    mdu = Mdu(path)\n    identity = require_fm_identity(mdu)',
                          '    if AUTHORED_PROFILES.get(profile_name) is source_sink_run_profile:\n        source_sink_run_profile.pre_read_hook(path)\n    mdu = Mdu(path)\n    identity = require_fm_identity(mdu)')
    elif name == 'run_pump_lifecycle.py':
        new = new.replace('    return "weir_lifecycle" if run.record.get("profile_name") == "weir-series" else "pump_lifecycle"',
                          '    if run.record.get("profile_name") == "source-sink":\n        return "source_sink_lifecycle"\n    return "weir_lifecycle" if run.record.get("profile_name") == "weir-series" else "pump_lifecycle"')
        new = new.replace('    family = "Weir" if run.record.get("profile_name") == "weir-series" else "Pump"',
                          '    family = ("Source/sink" if run.record.get("profile_name") == "source-sink" else\n              "Weir" if run.record.get("profile_name") == "weir-series" else "Pump")')
        new = new.replace('DfmError(family.lower() + "_" + kind', 'DfmError(family.lower().replace("/", "_") + "_" + kind')
        new = new.replace('        valid = valid and seen == expected\n',
                          '        valid = valid and seen == expected\n        if record.get("profile_name") == "source-sink":\n            from .source_sink_run_profile import notifications_complete\n            valid = valid and notifications_complete(trace)\n')
    else:
        new = new.replace('                "fm_model_identity": fm_model_identity.contract(),',
                          '                "source_sink_run_profile": runs.source_sink_run_profile.contract(),\n                "fm_model_identity": fm_model_identity.contract(),')
    assert new != old
    ast.parse(new)
    (TARGET / name).write_text(new, encoding='utf-8', newline='\n')
    patch += ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                         fromfile='a/src/dfm_cli/' + name, tofile='b/src/dfm_cli/' + name))
(HERE / 'shared-integration.patch').write_text(patch, encoding='utf-8', newline='\n')
additions = ''
for path in sorted(TARGET.glob('source_sink_run_*.py')):
    ast.parse(path.read_text(encoding='utf-8'))
    additions += ''.join(difflib.unified_diff([], path.read_text(encoding='utf-8').splitlines(True),
                         fromfile='/dev/null', tofile='b/src/dfm_cli/' + path.name))
(HERE / 'new-modules.patch').write_text(additions, encoding='utf-8', newline='\n')
print(json.dumps({'base_payloads': len(pins), 'shared_files': 3, 'new_modules': 2}))
