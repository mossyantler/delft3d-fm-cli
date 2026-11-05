"""Run pure tests and file-only preparation under explicit native-entry denial."""
import argparse
import importlib
import io
import sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import files as f
import admission as a
import runner

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-out',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();denied=[];patches=[]
    for target in ('subprocess.Popen','ctypes.CDLL','ctypes.WinDLL'):
        def refuse(*args,_target=target,**kwargs):denied.append(_target);raise AssertionError('Forbidden native/process entry: '+_target)
        item=patch(target,side_effect=refuse);item.start();patches.append(item)
    try:
        modules=runner.runtime({'runtime':f.inventory(f.HERE/'runtime')})
        def nojob(*args,**kwargs):denied.append('OwnedJob');raise AssertionError('Forbidden Job construction')
        item=patch.object(modules['windows_job'].OwnedJob,'__init__',side_effect=nojob);item.start();patches.append(item)
        log=io.StringIO();suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name))
                                                   for name in ('test_private','test_deadlines','test_lifecycle','test_forced','test_member_consistency'))
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        report={'schema':'B14-runner-pure-I-check-1','state':'passed' if result.wasSuccessful() else 'failed',
                'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
                'native_started':False,'Jobs_constructed':False,'dispatch_written':False,'root_product_written':False,
                'native_entry_attempts':denied,'test_log':log.getvalue()}
        if result.wasSuccessful():report['preparation']=a.prepare(args.prepared_out)
        f.need(not denied,'Pure test attempted native entry')
        f.save(args.report,report,fresh=True)
        print(__import__('json').dumps({k:v for k,v in report.items() if k!='test_log'},indent=2))
        return 0 if report['state']=='passed' else 1
    finally:
        for item in reversed(patches):item.stop()

if __name__=='__main__':raise SystemExit(main())
