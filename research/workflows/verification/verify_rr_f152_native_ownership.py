"""Prospective RR trace binding only; never backfills historical RR ownership.

Read actual successful RTC lifecycle evidence using the independent raw adapter,
and statically verify the exact profile switch that will apply on a FUTURE RR run.
No product imports, executable launches, reconstructed RR handles or PID scans.
"""
import argparse
import ast
import copy
import json
from pathlib import Path

from .verify_rr_f152_native import ROOT, require, sha, write, fingerprints
from .verify_rtc_exchange_native import terminal_receipt
from .verify_rtc_exchange_ownership import bind_raw_member_trace


def same_ast(a, b): return ast.dump(a, include_attributes=False) == ast.dump(b, include_attributes=False)


def profile_switch(raw):
    tree = ast.parse(raw); funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'execute_native']
    require(len(funcs) == 1, 'Exactly one native executor required'); function = funcs[0]
    expected = ast.parse('record.get("profile_name") == "coupling" and record.get("coupling", {}).get("profile", {}).get("name") in {"fm_rtc", "rr_f152"}', mode='eval').body
    assignments = [n for n in ast.walk(function) if isinstance(n, ast.Assign)]
    switches = [n for n in assignments if any(isinstance(t, ast.Name) and t.id == 'trace_exchange' for t in n.targets)]
    require(len(switches) == 1 and same_ast(switches[0].value, expected), 'Trace guard broadened or not exactly coupling RTC/RR f152')
    expected_job = ast.parse('run.job = OwnedJob(trace_members=True) if trace_exchange else OwnedJob()').body[0]
    jobs = [n for n in assignments if any(same_ast(t, expected_job.targets[0]) for t in n.targets)]
    require(len(jobs) == 1 and same_ast(jobs[0].value, expected_job.value), 'Trace must attach to fresh Job before launch')
    launches = [n for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'launch']
    require(len(launches) == 1 and switches[0].lineno < jobs[0].lineno < launches[0].lineno, 'Trace setup must precede native thread execution')
    captures = [n for n in ast.walk(function) if isinstance(n, ast.IfExp) and isinstance(n.test, ast.Name) and n.test.id == 'trace_exchange'
                and isinstance(n.body, ast.Call) and isinstance(n.body.func, ast.Name) and n.body.func.id == 'capture_normal_exit']
    expected_capture = ast.parse('capture_normal_exit(run.job, run.process, trace=run.job.member_trace) if trace_exchange else capture_normal_exit(run.job, run.process)', mode='eval').body
    require(len(captures) == 1 and same_ast(captures[0], expected_capture), 'Normal return must bind original member trace')
    return {'state': 'prospective_exact_profile_switch_verified', 'profiles': ['fm_rtc', 'rr_f152'],
            'trace_setup_line': jobs[0].lineno, 'launch_line': launches[0].lineno, 'capture_line': captures[0].lineno,
            'RR_native_ownership_established': False}


def exercise(rtc, rr):
    before = {str(p): fingerprints(p) for p in (rtc, rr)}
    rtc_manifest = rtc / 'runs/positive/manifest.json'; rtc_root = rtc / 'commands/positive-native-independent-native-exit.json'
    m = json.loads(rtc_manifest.read_bytes()); independent = json.loads(rtc_root.read_bytes())
    raw = m['ownership']['normal_exit']['member_trace']; binding = bind_raw_member_trace(raw, independent)
    full_binding = terminal_receipt(m, independent)
    mutations = []
    for case in ('missing_member', 'late_association', 'wrong_root', 'missing_notification'):
        changed = copy.deepcopy(raw); witness = copy.deepcopy(independent)
        if case == 'missing_member': changed['members'].pop()
        elif case == 'late_association': changed['job']['association_before_assignment'] = False
        elif case == 'wrong_root': witness['identity']['creation_time_100ns'] = '1'
        else:
            # ACTIVE_PROCESS_ZERO is supplemental: exact same-Job queries and
            # retained signalled handles establish emptiness/exit. Remove an
            # actual member lifecycle notification to test the required binding.
            notifications = changed['collection']['notifications']
            index = next(i for i, notice in enumerate(notifications) if notice['message'] in (6, 7, 8))
            notifications.pop(index)
        try: bind_raw_member_trace(changed, witness)
        except (AssertionError, KeyError, IndexError) as exc: mutations.append({'case': case, 'refused': True, 'reason': str(exc)})
        else: raise AssertionError('Incomplete prospective trace accepted: ' + case)
    old = json.loads((rr / 'runs/wet/manifest.json').read_bytes())
    old_root = json.loads((rr / 'commands/wet-native-independent-native-exit.json').read_bytes())
    try: terminal_receipt(old, old_root)
    except AssertionError as exc: historical = {'state': 'original_gate_still_failed', 'error': str(exc)}
    else: raise AssertionError('Historical RR ownership was incorrectly promoted')
    frozen = json.loads((rtc / 'frozen-product-hashes.json').read_bytes()); runtime = {}
    for name in ('windows_job.py', 'windows_job_trace.py', 'windows_exit_evidence.py'):
        key = 'src\\dfm_cli\\' + name; path = ROOT / 'src/dfm_cli' / name
        runtime[name] = {'sha256': sha(path), 'same_as_real_RTC_trial': frozen.get(key) == sha(path)}
        require(runtime[name]['same_as_real_RTC_trial'], 'Trace runtime changed since actual RTC validation: ' + name)
    runs = ROOT / 'src/dfm_cli/runs.py'; source = profile_switch(runs.read_text())
    require(all(fingerprints(p) == before[str(p)] for p in (rtc, rr)), 'Read-only ownership review changed native evidence')
    return {'status': 'passed_prospective_binding_not_historical_RR_acceptance', 'native_started': False,
            'source_switch': dict(source, path=str(runs), sha256=sha(runs)), 'unchanged_trace_runtime': runtime,
            'actual_RTC_binding': binding, 'actual_RTC_full_terminal_gate': full_binding['state'],
            'actual_RTC_manifest_sha256': sha(rtc_manifest), 'actual_RTC_root_receipt_sha256': sha(rtc_root),
            'adversarial_actual_trace_copies': mutations, 'historical_RR': historical,
            'historical_files_unchanged': True, 'scope': 'Existing real RTC2-member proof exercises the unchanged adapter. Exact source branch applies prospectively to RR. A new actual RR lifetime trace is still required.'}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--rtc-trial', type=Path, required=True); p.add_argument('--rr-trial', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv); out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    try: result = exercise(a.rtc_trial.resolve(), a.rr_trial.resolve()); code = 0
    except Exception as exc: result = {'status': 'failed_prospective_binding', 'native_started': False, 'error': str(exc)}; code = 1
    write(out / 'verification.json', result); print(json.dumps({'status': result['status'], 'error': result.get('error'), 'verification': str(out / 'verification.json')}, indent=2)); return code


if __name__ == '__main__': raise SystemExit(main())
