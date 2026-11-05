"""Independent preterminal readback failures; original close must not repeat."""
import copy
from unittest.mock import patch
import test_admission as a


class StorageEntry(a.Full):
    # Only inherit setup/helper methods; discovery below selects this class's
    # own tests explicitly so the old18 bodies do not accidentally count twice.
    def prepared(self):
        outcome, receipt, events = self.collect()
        self.assertEqual(outcome, 'native_returned_pending_data')
        receipt['state'] = 'verifying_owned_exit'; receipt['observed_outcome'] = outcome
        path = self.tmp / 'receipt.json'; self.r.save(path, receipt, fresh=True)
        return path, receipt, events

    def failure(self, mode):
        path, receipt, events = self.prepared(); before = path.read_bytes()
        injected = {'side_effect': OSError('Independent V preterminal read failure')} if mode == 'read_error' else {'return_value': b'{"state":"running"}\n'}
        with patch.object(self.r, 'read', **injected), patch.object(self.r, 'save', side_effect=AssertionError('must not try terminal save')) as save:
            with self.assertRaises(Exception) as caught: self.r.terminal_write(path, receipt, 'native_failed')
        details = getattr(caught.exception, 'details', {})
        row = {'test': self._testMethodName, 'mode': mode, 'exception_type': type(caught.exception).__name__,
               'details': details, 'canonical_bytes_unchanged': path.read_bytes() == before,
               'terminal_save_attempts': save.call_count, 'fake_boundary_events': events}
        a.OBS.append(row)
        self.assertEqual(path.read_bytes(), before); self.assertEqual(events.count('close_original_job'), 1)
        self.assertNotIn('terminate_original_job', events); self.assertEqual(save.call_count, 0)
        self.assertIsInstance(caught.exception, self.r.EvidenceStorageError)
        self.assertEqual(details['job_close'], receipt['job_close'])
        self.assertEqual(details['canonical_commit'], 'unacknowledged'); self.assertIs(details['cleanup_retry_attempted'], False)
        self.assertEqual(details['in_memory_receipt'], receipt)

    def test_initial_preterminal_read_error_preserves_original_raw_close(self): self.failure('read_error')

    def test_initial_preterminal_mismatched_bytes_preserves_original_raw_close(self): self.failure('different_bytes')

    def test_lifecycle_invalid_receipt_still_refuses_without_storage_reclassification(self):
        for mode in ('state', 'member_wait', 'close'):
            with self.subTest(mode=mode):
                path, receipt, events = self.prepared()
                if mode == 'state': receipt['state'] = 'running'
                if mode == 'member_wait': receipt['normal_exit']['member_trace']['members'][1]['exit']['wait_result'] = 258
                if mode == 'close': receipt['job_close']['succeeded'] = False
                self.r.save(path, receipt); before = path.read_bytes()
                with self.assertRaises(ValueError) as caught: self.r.terminal_write(path, receipt, 'native_failed')
                self.assertNotIsInstance(caught.exception, self.r.EvidenceStorageError)
                self.assertEqual(path.read_bytes(), before); self.assertEqual(events.count('close_original_job'), 1)
                path.unlink()  # Exact V-owned temporary file; next subcase is fresh.
