"""Prospective entry ordering/typed-byte counters; run only on exact freeze."""
from unittest.mock import patch
import test_admission as a
import test_storage_entry as entry


class EntryOrder(a.Full):
    prepared = entry.StorageEntry.prepared

    def test_invalid_lifecycle_refuses_before_canonical_storage_read(self):
        for mode in ('state', 'member_wait', 'close'):
            with self.subTest(mode=mode):
                path, receipt, events = self.prepared()
                if mode == 'state': receipt['state'] = 'running'
                if mode == 'member_wait': receipt['normal_exit']['member_trace']['members'][1]['exit']['wait_result'] = 258
                if mode == 'close': receipt['job_close']['succeeded'] = False
                self.r.save(path, receipt); before = path.read_bytes()
                with patch.object(self.r, 'read', side_effect=OSError('storage must not mask invalid lifecycle')) as read:
                    with self.assertRaises(ValueError) as caught: self.r.terminal_write(path, receipt, 'native_failed')
                a.OBS.append({'test': self._testMethodName, 'mode': mode, 'canonical_reads': read.call_count,
                              'exception_type': type(caught.exception).__name__, 'fake_boundary_events': events})
                self.assertNotIsInstance(caught.exception, self.r.EvidenceStorageError)
                self.assertEqual(read.call_count, 0)
                self.assertEqual(path.read_bytes(), before); self.assertEqual(events.count('close_original_job'), 1)
                path.unlink()

    def test_preterminal_boolean_zero_alias_is_unacknowledged_storage(self):
        path, receipt, events = self.prepared(); before = path.read_bytes()
        needle = b'"native_returncode": 0'
        self.assertIn(needle, before)
        aliased = before.replace(needle, b'"native_returncode": false', 1)
        with patch.object(self.r, 'read', return_value=aliased), patch.object(self.r, 'save', side_effect=AssertionError('no terminal save')) as save:
            with self.assertRaises(self.r.EvidenceStorageError) as caught: self.r.terminal_write(path, receipt, 'native_failed')
        details = caught.exception.details
        self.assertEqual(details['canonical_commit'], 'unacknowledged'); self.assertEqual(details['job_close'], receipt['job_close'])
        self.assertIs(details['cleanup_retry_attempted'], False); self.assertEqual(save.call_count, 0)
        self.assertEqual(path.read_bytes(), before); self.assertEqual(events.count('close_original_job'), 1)
