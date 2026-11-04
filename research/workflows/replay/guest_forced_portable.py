"""Author portable integration checks; synthetic Win32 ONLY, never a launcher.

Run with python -B -m research.workflows.replay.guest_forced_portable --out NEW.
No process constructor or Windows DLL loader is allowed. This is not the
independent V oracle or native/guest/IOCP evidence. It is NOT bundled runtime.
"""
from __future__ import annotations
import argparse
import copy
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
from unittest.mock import patch

from dfm_cli import windows_job as w, windows_job_trace as t
from . import dimr_project_export as p, guest_forced_cleanup as f

TOKEN = 'a' * 32
IMAGE = r'C:\fixture\python.exe'


class Handle(int):
    def __new__(cls, number):
        obj = int.__new__(cls, number); obj.closed = False; obj.fail = False
        return obj

    def Close(self):
        self.closed = True
        if self.fail: raise OSError(5, 'Synthetic root wrapper close failure')


class Kernel:
    """Explicit unit fake, not OS handles. Every BOOL/DWORD is concrete."""
    def __init__(self, image_error=False):
        self.stopped = False; self.image_error = image_error; self.job_close_return = 1; self.cleanup = None
    def GetProcessId(self, handle): return 1002 if handle == 3002 else int(handle)
    def GetProcessTimes(self, handle, creation, *rest):
        data = c.cast(creation, c.POINTER(w.w.FILETIME)).contents
        data.dwLowDateTime = 100000 + self.GetProcessId(handle); data.dwHighDateTime = 0
        return 1
    def IsProcessInJob(self, handle, job, result):
        c.cast(result, c.POINTER(w.w.BOOL)).contents.value = int(job == 100 and self.GetProcessId(handle) in (1001, 1002))
        return 1
    def QueryFullProcessImageNameW(self, handle, flags, buf, size):
        if self.stopped and self.image_error: raise OSError(31, 'Synthetic observed post-exit ERROR31')
        buf.value = IMAGE; c.cast(size, c.POINTER(w.w.DWORD)).contents.value = len(IMAGE)
        return 1
    def WaitForSingleObject(self, handle, ms): return 0 if self.stopped else 258
    def GetExitCodeProcess(self, handle, result):
        c.cast(result, c.POINTER(w.w.DWORD)).contents.value = 1
        return 1
    def OpenProcess(self, rights, inherit, pid): return 3002 if pid == 1002 else 0
    def CloseHandle(self, handle): return self.job_close_return if handle == 100 else 1
    def TerminateJobObject(self, handle, code):
        assert handle == 100 and code == 1
        self.stopped = True
        return 1
    def QueryInformationJobObject(self, handle, kind, data, size, returned):
        numbers = c.cast(data, c.POINTER(w._ForceAccounting)).contents
        numbers.TotalProcesses = 2; numbers.ActiveProcesses = 0 if self.stopped else 2
        c.cast(returned, c.POINTER(c.c_uint32)).contents.value = 48
        return 1


def fixture(image_error=False):
    process = subprocess.Popen.__new__(subprocess.Popen)
    process.pid = 1001; process._handle = Handle(1001); process._child_created = False; process.returncode = None
    kernel = Kernel(image_error); process.wait = lambda timeout: 1
    process.poll = lambda: 1 if kernel.stopped else None
    job = w.OwnedJob.__new__(w.OwnedJob)
    job.kernel = kernel; job.handle = job._owned_job_handle = 100
    job._root_process = process; job._root_handle = 1001
    root = {'pid': 1001, 'creation_time_100ns': '101001'}; job._root_identity = root
    job.members = lambda: [] if kernel.stopped else [1001, 1002]
    trace = t.JobMemberTrace.__new__(t.JobMemberTrace)
    trace.job = job; trace.kernel = kernel; trace.process = process; trace.job_handle = 100
    trace._closed = False; trace.instance_token = TOKEN
    trace._operation = threading.RLock(); trace._lock = threading.RLock()
    trace._root_candidate = {'handle': 1001, 'identity': root, 'image': IMAGE}
    trace._job_record = {'instance_token': TOKEN, 'handle_source': 'original_private_job_handle', 'limit_flags': 8192,
        'initial_accounting': {'state': 'captured', 'information_class': 1, 'buffer_bytes': 48, 'returned_bytes': 48,
            'handle_source': 'original_private_job_handle', 'values': {'TotalProcesses': 0, 'ActiveProcesses': 0, 'TotalTerminatedProcesses': 0}},
        'initial_members': []}
    trace._job_record.update({key: True for key in ('association_before_assignment', 'collector_started_before_resume', 'assigned_before_resume', 'no_breakaway', 'kill_on_close')})
    trace._members = {}
    for i, pid in enumerate((1001, 1002)):
        data = {'identity': {'pid': pid, 'creation_time_100ns': str(100000 + pid)}, 'image': IMAGE,
            'role': 'root' if i == 0 else 'descendant', 'handle_source': 'original_launch_handle' if i == 0 else 'owned_job_member_retained_handle',
            'identity_source': 'GetProcessTimes_same_retained_handle', 'capture_wait_result': 258, 'capture_sequence': 2 + i * 3,
            'captured_at_utc': '2001-01-01T00:00:00+00:00', 'retained_until_exit_check': False,
            'job_membership': {'state': 'captured', 'job_instance_token': TOKEN, 'is_member': True, 'query': 'IsProcessInJob_same_retained_handle'}}
        trace._members[pid] = {'handle': pid, 'owned': bool(i), 'data': data}
    job.member_trace = trace
    actual = w.OwnedJob.terminate
    def terminate(*args, **kwargs):
        kernel.cleanup = actual(job, *args, **kwargs)
        return kernel.cleanup
    job.terminate = terminate
    trace.snapshot = lambda *args, **kwargs: raw_for(job, kernel.cleanup)
    def close():
        trace._closed = True
        return {'state': 'closed', 'collector_stopped': True, 'errors': [], 'borrowed_root_closed': False,
                'borrowed_job_closed': False, 'termination_attempted': False}
    trace.close = close
    return job, process


def raw_for(job, cleanup):
    now = lambda: datetime.now(timezone.utc).isoformat()
    trace = {'schema_version': 1, 'classification': 'windows_job_member_handle_trace', 'state': 'incomplete',
        'all_owned_members_exit_confirmed': False, 'job': copy.deepcopy(job.member_trace._job_record),
        'root_identity': copy.deepcopy(job._root_identity), 'members': copy.deepcopy(cleanup['retained_members']),
        'retained_member_handle_count': 2, 'confirmed_member_exit_count': 2, 'unobserved_member_count': 0,
        'collection': {'state': 'incomplete', 'errors': [], 'unavailable_members': [], 'dropped_events': 0,
            'pending_events': 0, 'ended_after_accounting': True, 'events': [], 'notifications': []}}
    for i, member in enumerate(trace['members']):
        sequence = i + 3; pid = member['identity']['pid']
        trace['collection']['events'].append({'sequence': sequence, 'type': 'NEW_PROCESS', 'raw_message': 6, 'pid': pid, 'identity': member['identity'], 'job_instance_token': TOKEN})
        trace['collection']['notifications'].append({'sequence': sequence, 'message': 6, 'pid': pid, 'job_instance_token': TOKEN})
    trace['accounting'] = copy.deepcopy(cleanup['job_accounting']); trace['accounting']['captured_at_utc'] = now()
    trace['job_members'] = copy.deepcopy(cleanup['job_members_after']); trace['job_members']['captured_at_utc'] = now()
    return trace


def checks():
    results = []
    job, process = fixture(); life = p.monitor_owned_export(job, process, timeout=.001)
    assert life['state'] == 'timed_out' and life['cleanup']['termination_request']['reason'] == 'timed_out'
    good = life['forced_cleanup']; raw = life['post_cleanup_exit']['member_trace']; cleanup = life['cleanup']
    assert good['producer_retained_handle_coverage_confirmed'] is True and good['independent_contract_complete'] is False
    assert good['notification_history_complete'] is False and raw['all_owned_members_exit_confirmed'] is False
    results.append('real_source_monitor_core_capture_consumer_with_synthetic_kernel_only')
    cases = [
        ('missing_request', lambda x, y: x.pop('termination_request')),
        ('bool_request', lambda x, y: x['termination_request'].update(return_value=True)),
        ('zero_request', lambda x, y: x['termination_request'].update(return_value=0)),
        ('wrong_reason', lambda x, y: x['termination_request'].update(reason='completed')),
        ('foreign_token', lambda x, y: x['termination_request']['job_binding'].update(job_instance_token='b'*32)),
        ('missing_child', lambda x, y: x['retained_members'].pop()),
        ('bool_wait', lambda x, y: x['retained_members'][1]['exit'].update(wait_result=False)),
        ('unsignalled_wait', lambda x, y: x['retained_members'][1]['exit'].update(wait_result=258)),
        ('bool_code_query', lambda x, y: x['retained_members'][1]['exit'].update(exit_code_return_value=True)),
        ('observed_image_mismatch', lambda x, y: x['retained_members'][1].update(exit_image='C:/foreign.exe')),
        ('unknown_image_without_error', lambda x, y: x['retained_members'][1].update(exit_image_query={'state':'unavailable'})),
        ('changed_birth', lambda x, y: x['retained_members'][1]['exit_identity'].update(creation_time_100ns='999')),
        ('late_handle', lambda x, y: x['retained_members'][1].update(handle_source='stop_time_OpenProcess')),
        ('lifetime_count', lambda x, y: x['job_accounting']['values'].update(TotalProcesses=3)),
        ('bool_active_count', lambda x, y: x['job_accounting']['values'].update(ActiveProcesses=False)),
        ('accounting_size', lambda x, y: x['job_accounting'].update(returned_bytes=32)),
        ('nonempty_job', lambda x, y: x['job_members_after'].update(pids=[1002])),
        ('acquisition_error', lambda x, y: x['member_acquisition_failures'].append({'winerror':5})),
        ('trace_error', lambda x, y: y['collection']['errors'].append({'operation':'acquire_member_handle'})),
        ('unknown_queue', lambda x, y: y['collection'].update(pending_events=None)),
        ('dropped_events', lambda x, y: y['collection'].update(dropped_events=1)),
    ]
    before = f._fingerprint({'cleanup':cleanup, 'trace':raw})
    for name, mutate in cases:
        a, b = copy.deepcopy(cleanup), copy.deepcopy(raw); mutate(a, b)
        refused = f.observe(job, process, a, raw_trace=b)
        assert refused['state'] == 'incomplete' and refused['producer_retained_handle_coverage_confirmed'] is False, name
        results.append(name + '_refused')
    assert before == f._fingerprint({'cleanup':cleanup, 'trace':raw}); results.append('raw_evidence_immutable')
    closed = p.close_owned_export(job, process)
    assert closed['job']['native_close_result_confirmed'] and closed['root']['raw_return'] is None
    assert closed['state'] == 'controller_close_calls_returned_native_receipt_requires_verification'
    results.append('actual_core_close_receipt_and_None_root_wrapper_kept_distinct')
    assert f.observe(job, process, cleanup, raw_trace=raw)['state'] == 'incomplete'; results.append('closed_handles_refused')
    job, process = fixture(image_error=True); life = p.monitor_owned_export(job, process, timeout=.001)
    assert life['forced_cleanup']['producer_retained_handle_coverage_confirmed'] is True
    for member in life['cleanup']['retained_members']:
        assert 'exit_image' not in member and member['exit_image_query']['error']['winerror'] == 31
        assert member['exit']['confirmed'] is True and member['exit']['wait_result'] == 0
    results.append('explicit_optional_post_exit_ERROR31_with_mandatory_same_handle_proofs')
    p.close_owned_export(job, process)
    for returned in (0, False, True, None):
        job, process = fixture(); p.monitor_owned_export(job, process, timeout=.001); job.kernel.job_close_return = returned
        closed = p.close_owned_export(job, process)
        assert closed['state'] == 'incomplete' and not closed['job']['native_close_result_confirmed']
        results.append('non_native_job_close_' + repr(returned) + '_refused')
    job, process = fixture(); p.monitor_owned_export(job, process, timeout=.001); process._handle.fail = True
    closed = p.close_owned_export(job, process)
    assert closed['state'] == 'incomplete' and closed['root']['closed_attribute_after'] is True and 'error' in closed['root']
    results.append('root_closed_attribute_after_wrapper_error_is_not_success')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv); out = p.fresh(args.out, p.ROOT / 'src', Path(__file__))
    report = {'state':'failed_portable_mock_checks', 'native_started':False,
              'scope':'Synthetic Popen/Job via __new__; Win32 calls mocked. No OS handle, IOCP, guest, exporter or independent acceptance.'}
    try:
        with patch.object(subprocess.Popen, '__init__', side_effect=AssertionError('NO PROCESS CREATION')), patch.object(c, 'WinDLL', side_effect=AssertionError('NO DLL LOAD')):
            report['checks'] = checks()
        report.update(state='passed_portable_mock_checks', count=len(report['checks']))
    except Exception as exc:
        report['error'] = {'type':type(exc).__name__, 'message':str(exc)}
        raise
    finally:
        report['source_hashes'] = {str(path):p.sha(path) for path in (p.HERE, Path(f.__file__), Path(w.__file__), Path(__file__))}
        p.write_new(out / 'verification.json', report)
        print(json.dumps({'state':report['state'], 'count':report.get('count'), 'native_started':False, 'receipt':str(out/'verification.json')}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
