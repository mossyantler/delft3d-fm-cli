"""TEST-ONLY constructed Job facts. No real HANDLEs, processes or native proof.

All receipts are authored at fixture construction, before launch/stop/close.
Callbacks model operations returning those receipts; none fills missing fields
in a producer result or patches a production assessment/persistence function.
"""
import copy
import json
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dfm_cli import runs, windows_exit_evidence

TOKEN = 'c' * 32
IDENTITY = {'pid': 1234, 'creation_time_100ns': '123456789000000'}
INSTANCES = []


def stamp(second):
    return (datetime(2026, 11, 5, tzinfo=timezone.utc) + timedelta(seconds=second)).isoformat()


def binding():
    return {'job_instance_token': TOKEN, 'handle_source': 'original_private_job_handle',
            'original_handle_verified': True, 'same_original_retained_handle': True, 'trace_binding_verified': True}


def accounting(total, second):
    return {'state': 'captured', 'information_class': 1, 'buffer_bytes': 48, 'returned_bytes': 48,
            'handle_source': 'original_private_job_handle', 'captured_at_utc': stamp(second),
            'job_instance_token': TOKEN, 'after_member_exit_checks': True,
            'values': {'TotalProcesses': total, 'ActiveProcesses': 0, 'TotalTerminatedProcesses': 0}}


def member(image, code):
    return {'pid': 1234, 'role': 'root', 'identity': dict(IDENTITY), 'image': image,
            'job_instance_token': TOKEN, 'identity_source': 'GetProcessTimes_same_retained_handle',
            'handle_source': 'original_launch_handle', 'captured_at_utc': stamp(4),
            'capture_wait_result': 258, 'capture_sequence': 1,
            'job_membership': {'state': 'captured', 'is_member': True, 'job_instance_token': TOKEN,
                               'query': 'IsProcessInJob_same_retained_handle'},
            'retained_until_exit_check': True, 'exit_identity': dict(IDENTITY),
            'exit': {'state': 'signalled', 'same_retained_handle': True, 'confirmed': True,
                     'wait_timeout_ms': 0, 'wait_result': 0, 'exit_code_query': 'captured',
                     'exit_code_return_value': 1, 'exit_code': code, 'checked_at_utc': stamp(40)}}


def normal_receipt(image):
    root = member(image, 0)
    events = [{'sequence': i, 'raw_message': msg, 'type': kind, 'pid': 1234, 'identity': dict(IDENTITY),
               'job_instance_token': TOKEN, 'identity_source': 'matched_same_retained_handle',
               'observed_at_utc': stamp(second)}
              for i, msg, kind, second in [(1, 6, 'NEW_PROCESS', 3), (2, 7, 'EXIT_PROCESS', 41)]]
    counts = accounting(1, 50)
    empty = {'state': 'captured', 'job_instance_token': TOKEN, 'pids': [], 'captured_at_utc': stamp(51)}
    trace = {'state': 'captured', 'termination_attempted': False,
             'job': {'instance_token': TOKEN, 'handle_source': 'original_private_job_handle',
                     **{k: True for k in ('association_before_assignment', 'assigned_before_resume',
                                         'collector_started_before_resume', 'no_breakaway', 'kill_on_close')}},
             'members': [root], 'root_identity': dict(IDENTITY), 'accounting': counts, 'job_members': empty,
             'collection': {'state': 'captured', 'errors': [], 'unavailable_members': [], 'dropped_events': 0,
                            'pending_events': 0, 'ended_after_accounting': True, 'events': events,
                            'notifications': [{'sequence': e['sequence'], 'message': e['raw_message'],
                                               'pid': e['pid'], 'job_instance_token': TOKEN,
                                               'observed_at_utc': e['observed_at_utc']} for e in events]},
             'all_owned_members_exit_confirmed': True, 'retained_member_handle_count': 1,
             'confirmed_member_exit_count': 1, 'unobserved_member_count': 0}
    return {'state': 'captured', 'termination_attempted': False, 'member_trace': trace,
            'all_owned_members_exit_confirmed': True, 'root_exit_confirmed': True, 'job_empty': True,
            'job_accounting': counts, 'job_members': empty,
            'root': {'identity': dict(IDENTITY), 'pid': 1234, 'handle_source': 'original_subprocess.Popen._handle',
                     'state': 'signalled', 'exit_confirmed': True, 'wait_result': 0, 'exit_code': 0,
                     'exit_code_query': {'state': 'captured'}}}


def pre(second, image=None):
    value = {'state': 'captured', 'observed_at_utc': stamp(second), 'identity': dict(IDENTITY),
             'identity_query': 'captured', 'wait_result': 258,
             'job_membership': {'state': 'captured', 'return_value': 1, 'job_instance_token': TOKEN, 'is_member': True},
             'wait': {'state': 'not_signalled', 'same_retained_handle': True, 'wait_timeout_ms': 0,
                      'checked_at_utc': stamp(second), 'wait_result': 258}}
    if image is not None:
        value['image'] = image
    return value


def timeout_receipt(image):
    root = member(image, 99)
    root['pre_request'] = pre(12, image)
    root['prospective_qualified'] = True
    root['exit_image'] = image
    root['exit_image_query'] = {'state': 'captured', 'matches_capture_image': True, 'checked_at_utc': stamp(39)}
    original = {'pid': 1234, 'role': 'root', 'identity': dict(IDENTITY),
                'identity_source': 'GetProcessTimes_same_retained_handle', 'handle_source': 'original_launch_handle',
                'original_handle_verified': True, 'job_instance_token': TOKEN, 'pre_request': pre(11),
                'retained_until_exit_check': True, 'exit_identity': dict(IDENTITY),
                'exit': {**root['exit'], 'checked_at_utc': stamp(32), 'wait_timeout_ms': 5000}}
    return {'method': 'windows_job_object', 'pid': 1234, 'job_pids_before': [1234],
            'forced': True, 'graceful': False, 'tree_terminated': True, 'owned_process_exited': True,
            'errors': [], 'trace_errors': [], 'member_acquisition_failures': [], 'cleanup_members': [],
            'prospective_handle_coverage_complete': True, 'retained_members': [root], 'root_handle': original,
            'prospective_handles_observed_at_utc': stamp(10),
            'prospective_job': {'instance_token': TOKEN, 'handle_source': 'original_private_job_handle',
                                'initial_members': [], 'initial_accounting': accounting(0, 0),
                                'associated_at_utc': stamp(0), 'collector_started_at_utc': stamp(1),
                                'root_assigned_at_utc': stamp(3),
                                **{k: True for k in ('association_before_assignment', 'assigned_before_resume',
                                                    'collector_started_before_resume', 'no_breakaway', 'kill_on_close')}},
            'termination_request': {'schema_version': 1, 'api': 'TerminateJobObject', 'request_id': 'd' * 32,
                                    'attempted': True, 'succeeded': True, 'return_value': 1, 'return_type': 'int',
                                    'winerror': None, 'requested_exit_code': 1, 'reason': 'run_timeout',
                                    'started_at_utc': stamp(30), 'finished_at_utc': stamp(31),
                                    'original_root_identity': dict(IDENTITY), 'observed_before_job_members': [1234],
                                    'before_original_root_state': copy.deepcopy(original['pre_request']), 'job_binding': binding()},
            'job_accounting': accounting(1, 50), 'job_pids_after': [],
            'job_members_after': {'state': 'captured', 'pids': [], 'job_instance_token': TOKEN,
                                  'after_accounting': True, 'captured_at_utc': stamp(51)}}


def close_receipt():
    return {'schema_version': 1, 'api': 'CloseHandle', 'attempted': True, 'succeeded': True,
            'handle_source': 'original_private_job_handle', 'borrowed_root_handle_closed': False,
            'return_value': 1, 'return_type': 'int', 'job_instance_token': TOKEN, 'job_binding': binding(),
            'collector_close': {'attempted': True, 'state': 'returned', 'return_type': 'dict',
                                'return_value': {'state': 'closed', 'collector_stopped': True, 'errors': [],
                                                 'borrowed_root_closed': False, 'borrowed_job_closed': False,
                                                 'termination_attempted': False}}}


class CliJobFixture:
    def __init__(self, image, *, outcome):
        self.image = str(image)
        assert PureWindowsPath(self.image).is_absolute()
        assert outcome in ('natural', 'timeout', 'unconfirmed')
        self.outcome = outcome
        # Build receipts now. Negative tests never get a normal capture callback.
        self.normal = normal_receipt(self.image) if outcome == 'natural' else None
        self.timeout = timeout_receipt(self.image) if outcome == 'timeout' else None
        self.closed = close_receipt()
        self.constructed = json.dumps({'normal': self.normal, 'timeout': self.timeout, 'close': self.closed}, sort_keys=True)
        self.process = None
        self.stopped = False
        self.operations = []
        self.job = SimpleNamespace(handle=17, _root_process=None, _root_identity=dict(IDENTITY),
                                   member_trace=SimpleNamespace(instance_token=TOKEN, process=None),
                                   launch=Mock(), members=Mock(), terminate=Mock(), close=self.close)
        INSTANCES.append(self)

    def snapshot(self):
        unchanged = self.constructed == json.dumps({'normal': self.normal, 'timeout': self.timeout, 'close': self.closed}, sort_keys=True)
        assert unchanged
        return {'scope': 'SYNTHETIC_ONLY_NOT_HANDLE_OR_NATIVE_EVIDENCE', 'image': self.image, 'outcome': self.outcome,
                'construction_receipts': json.loads(self.constructed), 'receipts_unchanged': unchanged,
                'operations': list(self.operations), 'job_terminate_calls': self.job.terminate.call_count,
                'job_terminate_raw': self.job.terminate.return_value if type(self.job.terminate.return_value) is dict else None,
                'job_handle_after': self.job.handle, 'original_close_result': getattr(self.job, 'close_result', None)}

    def launched(self, callback_or_process):
        def launch(*args, **kwargs):
            assert self.process is None and self.job.handle == 17
            process = callback_or_process(*args, **kwargs) if callable(callback_or_process) and not isinstance(callback_or_process, Mock) else callback_or_process
            assert process.pid == 1234
            self.operations.append('launch')
            self.process = self.job._root_process = self.job.member_trace.process = process
            return process
        return launch

    def poll(self):
        return 99 if self.stopped else None

    def stop(self, process, folder, job, *, reason):
        assert self.outcome == 'timeout'
        assert process is self.process and job is self.job and reason == 'run_timeout'
        assert self.job.handle == 17 and not self.stopped
        self.operations.append('stop')
        self.stopped = True  # Model a stop, never repair the preconstructed raw receipt.
        return copy.deepcopy(self.timeout)

    def capture(self, job, process, *, trace):
        assert self.outcome == 'natural'
        assert job is self.job and process is self.process and trace is self.job.member_trace
        assert self.job.handle == 17 and not self.stopped
        self.operations.append('normal_capture')
        return copy.deepcopy(self.normal)

    def close(self):
        assert self.job.handle == 17 and 'close' not in self.operations
        self.operations.append('close')
        self.job.close_result = copy.deepcopy(self.closed)
        self.job.handle = None
        return copy.deepcopy(self.closed)

    @contextmanager
    def patch(self, *, normal=False):
        assert normal == (self.outcome == 'natural')
        with ExitStack() as stack:
            factory = stack.enter_context(patch.object(runs, 'OwnedJob', return_value=self.job))
            if normal:
                stack.enter_context(patch.object(windows_exit_evidence, 'capture_normal_exit', side_effect=self.capture))
            yield factory
        if self.process is not None:
            assert self.operations.count('close') == 1
        assert factory.call_args.kwargs == {'trace_members': True}
