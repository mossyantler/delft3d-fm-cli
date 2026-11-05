"""Source-only clean-runtime probe, executed only after exact wheel audit."""
from contextlib import ExitStack
import ctypes
import importlib
import importlib.metadata
from importlib.machinery import PathFinder
import json
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    assert sys.flags.isolated and sys.dont_write_bytecode
    prefix = Path(sys.prefix).resolve(); package = prefix / 'Lib/site-packages/dfm_cli'
    assert package.is_dir(); assert sys.pycache_prefix and not Path(sys.pycache_prefix).exists()
    assert not list((prefix / 'Lib/site-packages').glob('*.pth'))
    forbidden = []
    def deny(*a, **k): forbidden.append('process/engine loading'); raise AssertionError(forbidden[-1])
    origins = {}; resolvers = {}
    with ExitStack() as stack:
        stack.enter_context(patch('subprocess.Popen', side_effect=deny))
        stack.enter_context(patch.object(ctypes, 'CDLL', side_effect=deny))
        stack.enter_context(patch.object(ctypes, 'WinDLL', side_effect=deny, create=True))
        for name in ('dfm_cli', 'dfm_cli.cli', 'dfm_cli.common', 'dfm_cli.model', 'dfm_cli.runs',
                     'dfm_cli.run_pump_lifecycle', 'dfm_cli.windows_job', 'dfm_cli.windows_exit_evidence',
                     'dfm_cli.windows_job_trace', 'dfm_cli.simulation_progress'):
            module = importlib.import_module(name); path = Path(module.__file__).resolve()
            assert path.is_relative_to(package), (name, path)
            origins[name] = str(path)
        for p in sorted(package.glob('*.py')):
            if p.name == '__init__.py': continue
            name = 'dfm_cli.' + p.stem; spec = PathFinder.find_spec(name, [str(package)])
            assert spec is not None and Path(spec.origin).resolve() == p.resolve(), name
            resolvers[name] = spec.origin
    assert not forbidden
    import numpy
    import netCDF4
    import cftime
    extensions = {name: str(Path(mod.__file__).resolve()) for name, mod in list(sys.modules.items())
                  if getattr(mod, '__file__', None) and str(mod.__file__).endswith('.pyd')}
    for name, path in extensions.items():
        assert Path(path).is_relative_to(prefix) or Path(path).is_relative_to(Path(sys.base_prefix)), (name, path)
    print(json.dumps({'prefix': str(prefix), 'base_prefix': sys.base_prefix, 'python': sys.executable,
        'isolated': bool(sys.flags.isolated), 'source_only_absent_pycache_prefix': sys.pycache_prefix,
        'sys_path': sys.path, 'critical_origins': origins, 'all_product_resolvers': resolvers,
        'extension_origins': extensions, 'product_metadata': {'name': importlib.metadata.metadata('delft3d-fm-cli')['Name'],
            'version': importlib.metadata.version('delft3d-fm-cli')},
        'dependency_versions': {n: importlib.metadata.version(n) for n in ('numpy', 'netCDF4', 'cftime', 'packaging', 'certifi', 'pip')},
        'forbidden_calls': forbidden, 'native_engine_launches': 0}))


if __name__ == '__main__': main()
