"""Run the exact frozen 18 tests against the clean installed package only."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
import dfm_cli
from dfm_cli import wind_drag,wind_drag_graph,wind_drag_text
site=HERE/'venv/Lib/site-packages/dfm_cli'
assert Path(dfm_cli.__file__).resolve().parent==site
assert all(Path(m.__file__).resolve().parent==site for m in (wind_drag,wind_drag_graph,wind_drag_text))
assert not any('S07-I-' in p or p.replace('\\','/').endswith('/src') for p in sys.path)
(HERE/'test-runs').mkdir()
tempfile.tempdir=str(HERE/'test-runs')
suite=unittest.defaultTestLoader.discover(str(HERE/'checks'),pattern='test_wind_drag.py')
with (HERE/'installed-tests.log').open('w',encoding='utf-8') as out:
    result=unittest.TextTestRunner(stream=out,verbosity=2).run(suite)
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
    'modules':{m.__name__:{'path':m.__file__,'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
               for m in (dfm_cli,wind_drag,wind_drag_graph,wind_drag_text)},
    'sys_path':sys.path,'python':sys.executable,'overlay':False,'root_import':False,'native_launches':0}
(HERE/'installed-tests.json').write_text(json.dumps(report,indent=2)+'\n')
assert result.testsRun==18 and result.skipped==[]
print((HERE/'installed-tests.log').read_text())
raise SystemExit(not result.wasSuccessful())
