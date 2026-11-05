"""Portable independent terminal-write regressions: stdlib, no suite/processes.

The full controller/order/raw-receipt checks are separate. These tests exercise
the terminal persistence barrier on actual temporary file bytes. No research
paths or imports; suitable for tests/ after the reviewed helper is integrated.
"""
from contextlib import ExitStack
import copy
import ctypes
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli.common import DfmError, write_json
from dfm_cli.run_pump_lifecycle import publish_terminal


class PumpTerminalPublicationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="dfm-terminal-")
        self.addCleanup(tmp.cleanup);self.path=Path(tmp.name)/"manifest.json"
        guards=ExitStack();self.addCleanup(guards.close)
        guards.enter_context(patch.object(subprocess,"Popen",side_effect=AssertionError("No process allowed")))
        guards.enter_context(patch.object(ctypes,"WinDLL",side_effect=AssertionError("No WinAPI allowed"),create=True))
        self.record={"schema_version":3,"run_id":"a"*32,"state":"completed",
                     "updated_at_utc":"2001-01-01T00:02:01+00:00","returncode":0,
                     "ownership":{"job_close":{"attempted":True,"succeeded":True,"return_value":1}},
                     "verification":{"state":"passed","axes":{"history":{"last":"2001-01-01T00:02:00+00:00"},"map":{"last":"2001-01-01T00:02:00+00:00"}}},
                     "literal_text":"Unicode μ; preserved explicit terminal image"}

    def encoded(self,record):
        return (json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+"\n").encode("utf-8")

    def test_normal_persisted_exact_image(self):
        original=copy.deepcopy(self.record);publish_terminal(self.path,self.record,write_json)
        self.assertEqual(self.path.read_bytes(),self.encoded(original))
        self.assertEqual(self.record,original)

    def test_exact_commit_then_error_acknowledged_once(self):
        for exception in (OSError,KeyboardInterrupt):
            with self.subTest(exception=exception.__name__):
                calls=[];original=copy.deepcopy(self.record)
                def writer(path,record):
                    calls.append(True);write_json(path,record);raise exception("Synthetic error after actual replacement")
                publish_terminal(self.path,self.record,writer)
                self.assertEqual(calls,[True]);self.assertEqual(self.path.read_bytes(),self.encoded(original))
                self.assertEqual(self.record,original)

    def test_precommit_error_refuses_and_preserves_previous(self):
        prior={"run_id":"a"*32,"state":"verifying","unchanged":"close receipt already retained"}
        for exception in (OSError,KeyboardInterrupt):
            with self.subTest(exception=exception.__name__):
                write_json(self.path,prior);before=self.path.read_bytes();calls=[]
                def writer(path,record):calls.append(True);raise exception("Synthetic storage refusal before commit")
                with self.assertRaises(DfmError) as caught:publish_terminal(self.path,self.record,writer)
                self.assertEqual(caught.exception.code,"terminal_write_unconfirmed")
                self.assertEqual(calls,[True]);self.assertEqual(self.path.read_bytes(),before)

    def test_foreign_lookalikes_refused_and_entire_bytes_preserved(self):
        for defect in ("id","time","close","timestamp"):
            with self.subTest(defect=defect):
                wrong=copy.deepcopy(self.record)
                if defect=="id":wrong["run_id"]="f"*32
                elif defect=="time":wrong["verification"]["axes"]["history"]["last"]="1970-01-01T00:00:00+00:00"
                elif defect=="close":wrong["ownership"].pop("job_close")
                else:wrong["updated_at_utc"]="1970-01-01T00:00:00+00:00"
                raw=self.encoded(wrong);calls=[]
                def writer(path,record):
                    calls.append(True);path.write_bytes(raw);raise OSError("Synthetic unowned lookalike, intended commit refused")
                with self.assertRaises(DfmError) as caught:publish_terminal(self.path,self.record,writer)
                self.assertEqual(caught.exception.code,"terminal_write_unconfirmed")
                self.assertEqual(calls,[True]);self.assertEqual(self.path.read_bytes(),raw)

    def test_corrupt_or_trailing_data_not_matching_commit(self):
        for raw in (b"\xffcorrupt",b"",self.encoded(self.record)+b"FOREIGN TRAILER"):
            with self.subTest(bytes=len(raw)):
                def writer(path,record):path.write_bytes(raw);raise OSError("Synthetic wrong image")
                with self.assertRaises(DfmError) as caught:publish_terminal(self.path,self.record,writer)
                self.assertEqual(caught.exception.code,"terminal_write_unconfirmed")
                self.assertEqual(self.path.read_bytes(),raw)

    def test_failed_terminal_reason_preserved_after_exact_commit(self):
        self.record.update(state="cleanup_failed",stop_reason="run_timeout",error={"code":"pump_cleanup_failed","details":{"trigger":"run_timeout"}})
        self.record["verification"]={"state":"not_completed","reason":"run_timeout"}
        original=copy.deepcopy(self.record)
        def writer(path,record):write_json(path,record);raise OSError("Synthetic after-commit failure")
        publish_terminal(self.path,self.record,writer)
        self.assertEqual(self.path.read_bytes(),self.encoded(original));self.assertEqual(self.record,original)


if __name__=="__main__":unittest.main()
