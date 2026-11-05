"""Private candidate tests on fake native boundaries; no engine/Job/FFI."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'src'))
import dfm_cli
dfm_cli.__path__.insert(0,str(HERE/'src/dfm_cli'))
sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'checks'))
(HERE/'test-runs').mkdir(exist_ok=True);tempfile.tempdir=str(HERE/'test-runs')
history=HERE/'check-history';history.mkdir(exist_ok=True)
receipt=history/('run-'+str(1+sum(p.name.startswith('run-') for p in history.iterdir())).zfill(3));receipt.mkdir()
modules=['test_native_cleanup','test_short_close_contract','test_common_contract','test_canonical_gate','test_optional_forced_binding','test_pump_run_lifecycle','test_pump_close_attribution','test_pump_terminal_publication','test_weir_run_profile']
suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
with (HERE/'tests.log').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
    'failed_ids':[t.id() for t,_ in result.failures],'error_ids':[t.id() for t,_ in result.errors],
    'native_launches':0,'root_writes':False,'scope':'Fake process/Job boundaries with actual private Run/start/save and portable file writes'}
(HERE/'tests.json').write_bytes((json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report,indent=2))
for name in ('tests.log','tests.json'):shutil.copyfile(HERE/name,receipt/name)
(receipt/'source-pins.json').write_text(json.dumps({p.relative_to(HERE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
    for root in (HERE/'src',HERE/'checks') for p in root.rglob('*.py')},indent=2)+'\n')
raise SystemExit(not result.wasSuccessful())
