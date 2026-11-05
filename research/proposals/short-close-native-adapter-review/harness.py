"""Independent offline harness for NATIVE-ADAPTER-V.

Drives the adapter's REAL Warm/Active/Driver/Replay classes, the pinned REAL
RetainedProcess observer class and the frozen REAL reader, with:

* a scripted fake public CLI process (subprocess.Popen is replaced; nothing is spawned),
* a fake kernel32 (ctypes.WinDLL is replaced; no foreign function is ever called),
* a virtual monotonic clock shared by the adapter and the observer module,
* labelled SYNTHETIC metadata copies of the five immutable #227 records.

Nothing here is native, process, Job or HANDLE evidence.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import types

sys.dont_write_bytecode = True  # never write __pycache__ into the read-only adapter/reader folders

REPO = Path(__file__).resolve().parents[3]
import os  # noqa: E402
# Only the mutation-sensitivity run sets this to a scratch COPY of the adapter; the review itself always targets the frozen folder.
ADAPTER = Path(os.environ.get('NATIVE_ADAPTER_V_ADAPTER_DIR') or (REPO / 'research/proposals/short-close-native-adapter'))
READER = REPO / 'research/proposals/short-close-native-reader'
HISTORY = REPO / 'research/experiments/SHORT-CLOSE-G-native-227-01'
OBSERVER_SOURCE = REPO / 'research/workflows/verification/verify_water_quality_offline_lifecycle_observe.py'
BASE = datetime(2026, 11, 5, 1, 0, 0, tzinfo=timezone.utc)  # virtual timeline origin

sys.path.insert(0, str(ADAPTER))  # the adapter's own private modules, read only


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def original(name):
    return json.loads((HISTORY / name / 'manifest.json').read_bytes())


class Clock:
    """One virtual clock for adapter stamps and observer snapshots (UTC + monotonic agree)."""

    def __init__(self, start=BASE):
        self.t = start
        self.mono = 5_000_000_000

    def tick(self):
        self.t += timedelta(milliseconds=1)
        self.mono += 1_000_000

    def now(self):
        self.tick()
        return self.t

    def iso(self):
        return self.now().isoformat()

    def monotonic_ns(self):
        self.tick()
        return self.mono

    def at(self, seconds):
        return BASE + timedelta(seconds=seconds)

    def jump_to(self, when):
        if when < self.t:
            return  # clocks never run backwards
        self.mono += int((when - self.t).total_seconds() * 1e9)
        self.t = when


class FakeFn:
    def __init__(self, impl):
        self.impl, self.argtypes, self.restype = impl, None, None

    def __call__(self, *args):
        return self.impl(*args)


class FakeKernel:
    """Pure-python kernel32 stand-in for the pinned RetainedProcess; scriptable failures."""

    def __init__(self):
        self.procs, self.handles, self.closed, self.calls = {}, {}, [], []
        self.next_handle = 0x400
        self.fail = set()
        for name in ('OpenProcess', 'CloseHandle', 'GetProcessTimes', 'WaitForSingleObject',
                     'QueryFullProcessImageNameW', 'IsProcessInJob'):
            setattr(self, name, FakeFn(getattr(self, '_' + name)))

    def add_process(self, pid, creation, image):
        self.procs[pid] = {'creation': int(creation), 'image': image, 'exited': False, 'in_job': True}

    def _OpenProcess(self, access, inherit, pid):
        self.calls.append('OpenProcess')
        if pid not in self.procs or 'open' in self.fail:
            return 0
        self.next_handle += 4
        self.handles[self.next_handle] = pid
        return self.next_handle

    def _CloseHandle(self, handle):
        self.calls.append('CloseHandle')
        if 'close' in self.fail or handle not in self.handles:
            return 0
        del self.handles[handle]
        self.closed.append(handle)
        return 1

    def _GetProcessTimes(self, handle, creation, exit_time, system, user):
        if 'times' in self.fail or handle not in self.handles:
            return 0
        value = self.procs[self.handles[handle]]['creation']
        creation._obj.dwHighDateTime, creation._obj.dwLowDateTime = value >> 32, value & 0xffffffff
        return 1

    def _QueryFullProcessImageNameW(self, handle, flags, buffer, length):
        if 'image' in self.fail or handle not in self.handles:
            return 0
        text = self.procs[self.handles[handle]]['image']
        buffer.value = text
        length._obj.value = len(text)
        return 1

    def _WaitForSingleObject(self, handle, milliseconds):
        self.calls.append('Wait')
        if 'snapshot' in self.fail:
            raise OSError('synthetic snapshot failure')
        if handle not in self.handles:
            return 0xFFFFFFFF
        return 0 if self.procs[self.handles[handle]]['exited'] else 258

    def _IsProcessInJob(self, handle, job, member):
        if handle not in self.handles:
            return 0
        member._obj.value = 1 if self.procs[self.handles[handle]]['in_job'] else 0
        return 1


# ---------------------------------------------------------------------------
# metadata copies of the immutable #227 records
# ---------------------------------------------------------------------------
ISO = re.compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$')


def relabel(src, *, tag, run_dir, state, route='direct', exe_new=None, sha_new=None, request_at=None):
    """Distinct synthetic copy: new PIDs/births/tokens/paths; forced timeline moved so the stop request is at request_at."""
    record = copy.deepcopy(src)
    old_dir, old_exe, old_sha = record['run_directory'], record['argv'][0], record['executable_sha256']
    members = (record['termination']['retained_members'] if 'termination' in record
               else record['ownership']['normal_exit']['member_trace']['members'])
    pids = sorted({record['pid']} | {m['identity']['pid'] for m in members})
    pidmap = {p: 300000 + 100 * tag + i for i, p in enumerate(pids)}
    shift = timedelta(0)
    if request_at is not None:
        shift = request_at - datetime.fromisoformat(record['termination']['termination_request']['started_at_utc'])

    def walk(value):
        if isinstance(value, dict):
            return {(str(pidmap[int(k)]) if k.isdigit() and int(k) in pidmap else k): walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if type(value) is int and value in pidmap:
            return pidmap[value]
        if isinstance(value, str):
            if re.fullmatch('[0-9a-f]{32}', value):
                return hashlib.sha256(('%d:%s' % (tag, value)).encode()).hexdigest()[:32]
            if re.fullmatch(r'\d{17,19}', value):
                return str(int(value) + tag * 10 ** 9 + 1)
            if ISO.match(value):
                return (datetime.fromisoformat(value) + shift).isoformat()
            if value == old_sha:
                return sha_new or old_sha
            return value.replace(old_dir, str(run_dir)).replace(old_exe, exe_new or old_exe)
        return value

    record = walk(record)
    record.update(state=state, route=route, SYNTHETIC_METADATA_COPY_NOT_NATIVE_EVIDENCE=True)
    if route == 'dimr':
        record['argv'] = [exe_new, 'dimr_config.xml']
        record['working_directory'] = str(run_dir)
    return record


class Owner:
    """Scripted stand-in for the installed `dfm run start` owner (never a real process)."""

    def __init__(self, harness, case, record, *, go_at, final_at, end, returncode):
        self.h, self.case, self.record = harness, case, record
        self.go_at, self.final_at, self.end, self.returncode = go_at, final_at, end, returncode
        self.folder = harness.root / case['case_id']
        self.cancel_requested, self.polls, self.phase = False, 0, 'new'
        self.go_count = 0
        self.payload_override = None  # None | dict | 'EMPTY'

    def go(self):
        self.go_count += 1
        self.h.clock.jump_to(self.go_at)
        self.folder.mkdir()
        (self.folder / 'manifest.json').write_text(json.dumps({'state': 'starting', 'run_id': self.record['run_id']}))
        self.phase = 'started'

    def advance(self):
        """One poll of the owner process; returns exit code or None."""
        self.polls += 1
        ident = self.record['ownership']['native_identity']
        if self.phase == 'started':
            self.h.kernel.add_process(ident['pid'], ident['creation_time_100ns'], self.record['argv'][0])
            (self.folder / 'stdout.log').write_bytes(b'** INFO   : Done writing initial output to file(s).\n')
            (self.folder / 'manifest.json').write_text(json.dumps(
                {'state': 'running', 'pid': ident['pid'], 'argv': self.record['argv'], 'ownership': {'native_identity': ident}}))
            self.h.clock.jump_to(self.go_at + timedelta(milliseconds=100))
            self.phase = 'running'
            self.h.live += 1
            self.h.max_live = max(self.h.max_live, self.h.live)
            return None
        if self.phase != 'running':
            return None
        due = (self.end[0] == 'polls' and self.polls >= self.end[1]) or (self.end[0] == 'cancel' and self.cancel_requested)
        if not due:
            return None
        self.h.clock.jump_to(self.final_at)
        (self.folder / 'manifest.json').write_text(json.dumps(self.record))
        self.h.kernel.procs[ident['pid']]['exited'] = True
        self.phase = 'done'
        self.h.live -= 1
        if self.case['family'] == 'natural':
            model = self.folder / 'model'
            model.mkdir()
            for name in ('f34_his.nc', 'f34_map.nc', 'f34_19900805_000000_rst.nc', 'f34_19900805_001000_rst.nc'):
                (model / name).write_bytes(b'SYNTHETIC')
        return self.returncode


class FakeStdin:
    def __init__(self, process):
        self.process, self.closed = process, False

    def write(self, data):
        if self.process.break_pipe:
            raise BrokenPipeError('synthetic broken pipe')
        self.process.lines.append(data)
        self.process.on_line(data)

    def flush(self):
        if self.process.break_pipe:
            raise BrokenPipeError('synthetic broken pipe')

    def close(self):
        self.closed = True


class FakeProcess:
    """Replaces subprocess.Popen for the warm public CLI; behaviour is scripted per command."""

    def __init__(self, harness, argv, stdout, stderr):
        self.h, self.stdout, self.stderr = harness, stdout, stderr
        arguments = json.loads(Path(argv[argv.index('--arguments') + 1]).read_bytes())
        self.arguments = arguments
        self.kind = arguments[1]  # start | cancel
        self.folder_name = Path(arguments[arguments.index('--out') + 1] if self.kind == 'start' else arguments[2]).name
        self.lines, self.code, self.break_pipe, self.started = [], None, False, False
        self.stdin = FakeStdin(self)
        self.owner = harness.owners[self.folder_name]
        self.nodes = None
        if self.kind == 'start' and harness.hold_ready.get(self.folder_name) == 'never':
            return
        ready = Path(argv[argv.index('--ready') + 1])
        ready.write_text(json.dumps({'state': 'installed_public_cli_imported_command_NOT_started', 'argv': arguments,
                                      'python': str(harness.context['python']),
                                      'package_origin': str(harness.context['python'].parent.parent / 'Lib/site-packages/dfm_cli/__init__.py')}))

    def on_line(self, data):
        if data == b'abort\n':
            self.code = 2
        elif data == b'go\n':
            self.started = True
            if self.kind == 'start':
                self.owner.go()
            else:
                self.owner.cancel_requested = True
                self.finish(0, {'protocol_version': 2, 'ok': True})

    def finish(self, code, payload):
        self.stdout.write(json.dumps(payload).encode())
        self.stdout.flush()
        self.code = code

    def poll(self):
        if self.code is not None:
            return self.code
        if self.kind == 'start' and self.started:
            code = self.owner.advance()
            if code is not None:
                ok = self.owner.record['state'] == 'completed'
                override = self.owner.payload_override
                if override == 'EMPTY':
                    self.code = code
                else:
                    self.finish(code, override if override is not None else {'protocol_version': 2, 'ok': ok})
        return self.code

    def wait(self, timeout=None):
        for _ in range(50):
            if self.poll() is not None:
                return self.code
        raise subprocess.TimeoutExpired('synthetic', timeout)


class Harness:
    """Builds a real Replay over fake processes/kernel and scripted owners."""

    def __init__(self, root, auditor, *, routes=('direct',), observer_fail=None):
        from prepare import matrix
        import public_driver
        import replay_adapter
        self.root, self.auditor = Path(root), auditor
        self.clock, self.kernel = Clock(), FakeKernel()
        self.owners, self.hold_ready = {}, {}
        self.live = self.max_live = 0
        self.public_driver, self.replay_adapter = public_driver, replay_adapter
        self.exe = {'direct': original('natural-direct')['argv'][0]}
        self.exe['dimr'] = self.exe['direct'].replace('dflowfm-cli.exe', 'dimr.exe')
        self.sha = {'direct': original('natural-direct')['executable_sha256'], 'dimr': 'd' * 64}
        for name in ('commands', 'attempts', 'audits', 'observations', 'cleanup-errors', 'audit-errors'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / 'stub').mkdir(exist_ok=True)
        stub = self.root / 'stub/raw_outputs_stub.py'
        stub.write_text("VARS={'f34_his.nc':68,'f34_map.nc':55}\n"
                        "def raw_outputs(folder, record):\n"
                        "    return {'history':{'final_time_matches':True},'map':{'final_time_matches':True},'final_restart_present':True,'SYNTHETIC_STUB':True}\n"
                        "def compare_native_data(a, b):\n"
                        "    return {'variables':VARS.get(a.name,34),'SYNTHETIC_STUB':True}\n")
        self.context = {
            'run_root': self.root, 'predeclared': {'cases': matrix()},
            'predeclared_path': ADAPTER.parent.parent / 'experiments/SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01/prepared-02/predeclared.json',
            'python': self.root / 'venv/Scripts/python.exe',
            'grant': {'installation': 'C:/synthetic/install', 'executables': dict(self.exe),
                      'engine_files': [{'path': self.exe[r], 'sha256': self.sha[r]} for r in ('direct', 'dimr')]},
            'dependencies': {'observer': OBSERVER_SOURCE, 'raw_output_reader': stub}}

    # --- scripted cases -----------------------------------------------------
    def script(self, case, *, tag, end, go_at, final_at, request_at=None, source=None, state=None, returncode=None, record=None):
        folder = self.root / case['case_id']
        route = case['route']
        family = case['family']
        source = source or {'natural': 'natural-direct', 'bad-mesh': 'bad-mesh-direct', 'empty-bc': 'empty-bc-direct',
                            'timeout': 'timeout-direct', 'control': 'control-direct', 'cancel': 'control-direct'}[family]
        state = state or {'natural': 'completed', 'bad-mesh': 'failed', 'empty-bc': 'failed', 'timeout': 'timed_out',
                          'control': 'cancelled', 'cancel': 'cancelled'}[family]
        record = record or relabel(original(source), tag=tag, run_dir=folder, state=state, route=route,
                                   exe_new=self.exe[route], sha_new=self.sha[route],
                                   request_at=self.clock.at(request_at) if request_at is not None else None)
        owner = Owner(self, case, record, go_at=self.clock.at(go_at), final_at=self.clock.at(final_at), end=end,
                      returncode=returncode if returncode is not None else (0 if state == 'completed' else 5))
        self.owners[case['case_id']] = owner
        return owner

    def script_default(self, route='direct'):
        """The nominal twelve-case timeline (per route offset 1000 s)."""
        off = 0 if route == 'direct' else 1000
        cases = {c['case_id']: c for c in self.context['predeclared']['cases']}
        spec = [('natural', ('polls', 3), 100, 101, None), ('bad-mesh', ('polls', 3), 110, 111, None),
                ('empty-bc', ('polls', 3), 120, 121, None), ('control', ('cancel',), 130, 190.06, 190.0),
                ('timeout', ('polls', 6), 140, 160.06, 160.0), ('cancel', ('cancel',), 170, 180.06, 180.0)]
        for i, (family, end, go, final, request) in enumerate(spec):
            self.script(cases['%s-%s' % (family, route)], tag=i + (6 if route == 'dimr' else 0), end=end, go_at=go + off,
                        final_at=final + off, request_at=None if request is None else request + off)

    # --- patching -------------------------------------------------------------
    def patches(self):
        from unittest.mock import patch
        harness = self

        def popen(argv, cwd=None, stdin=None, stdout=None, stderr=None, **kw):
            return FakeProcess(harness, argv, stdout, stderr)

        def fake_load(path, name):
            module = load(path, name)
            if Path(path).name == OBSERVER_SOURCE.name:
                module.datetime = types.SimpleNamespace(now=lambda tz=None: harness.clock.now())
                module.time = types.SimpleNamespace(monotonic_ns=harness.clock.monotonic_ns)
            return module
        import ctypes
        return [patch('subprocess.Popen', side_effect=popen),
                patch.object(ctypes, 'WinDLL', create=True, new=lambda *a, **k: harness.kernel),
                patch.object(ctypes, 'CDLL', create=True, side_effect=AssertionError('NO FFI')),
                patch('admission.recheck_start', return_value=None),
                patch.object(self.public_driver, 'now', new=self.clock.iso),
                patch.object(self.public_driver, 'load_module', new=fake_load),
                patch.object(self.replay_adapter, 'load_module', new=fake_load)]

    def replay(self):
        return self.replay_adapter.Replay(self.context, self.auditor)


def reader():
    return load(READER / 'raw_audit.py', 'frozen_reader_under_review')
