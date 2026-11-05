"""Run only synthetic adapter tests; no native process or FFI boundary allowed."""
import argparse
from contextlib import ExitStack
import ctypes
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from prepare import EXPERIMENTS, no_alias, save, sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();out=no_alias(args.out,absent=True)
    if not out.is_relative_to(EXPERIMENTS):raise ValueError('Fresh experiment output required')
    out.mkdir(parents=True)
    blocked=[]
    def forbidden(*args,**kwargs):
        blocked.append('process_or_FFI_boundary');raise AssertionError(blocked[-1])
    log=io.StringIO()
    with ExitStack() as stack:
        for name in ('subprocess.Popen','ctypes.CDLL','ctypes.WinDLL'):
            stack.enter_context(patch(name,side_effect=forbidden,create=True))
        suite=unittest.defaultTestLoader.loadTestsFromNames(['test_portable','test_flow'])
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (out/'tests.log').write_bytes(log.getvalue().encode())
    receipt={'node':'NATIVE-ADAPTER-I','tests':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'skips':len(result.skipped),'passed':result.wasSuccessful(),
        'blocked_attempts':blocked,'native_launches':0,
        'sources':{p.name:sha(p) for p in sorted(HERE.glob('*.py'))},
        'scope':'Synthetic adapter control-flow and file admission checks only; exact-reader composition is separate.'}
    save(out/'verification.json',receipt)
    print(json.dumps(receipt))
    if not result.wasSuccessful():print(log.getvalue())
    return 0 if result.wasSuccessful() and not blocked else 1


if __name__=='__main__':raise SystemExit(main())
