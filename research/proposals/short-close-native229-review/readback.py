"""NATIVE229-CLOSE-V: pure read-only JSON postmortem of the real lease-229 trial.

Reads only retained JSON/log files. The frozen reader (raw_audit.py, hash-pinned) is used unchanged.
No process, PID, Job, HANDLE, FFI, native or GUI query; no write outside the fresh --out folder; no Git.

  python -I -B readback.py --out research/experiments/SHORT-CLOSE-NATIVE229-CLOSE-V-<stamp>/<fresh-child>
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import sys

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / 'research/experiments'
RUN = EXP / 'SHORT-CLOSE-G-native-rev04-229-20261105-01'
GRANT_DIR = EXP / 'SHORT-CLOSE-NATIVE-G-20261105-01'
DISPATCH = EXP / 'roadmap-coordinator-20261104/dispatch.json'
READER_DIR = REPO / 'research/proposals/short-close-native-reader'
ADAPTER_V3 = REPO / 'research/proposals/short-close-native-adapter-v3'
READER_FREEZE = '980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62'
ADAPTER_FREEZE = 'daffc237b80eb5c35b49dcb445e11cda03ae91f86ba080b9a2177253d3aa8c16'
GRANT_SHA = '552ebe0a9b987d2d5d3ef63b5540bb8862cde2a2b9d072af4d583222a9659171'
CASES = ['natural-direct', 'bad-mesh-direct', 'empty-bc-direct', 'control-direct', 'timeout-direct', 'cancel-direct']
FAMILY = {c: c.rsplit('-', 1)[0] for c in CASES}
EXPECTED_STATE = {'natural': 'completed', 'bad-mesh': 'failed', 'empty-bc': 'failed', 'control': 'cancelled', 'timeout': 'timed_out', 'cancel': 'cancelled'}
TICK_NS = 15_625_000  # GetTickCount64 granularity reported by observed-clock.json (0.015625 s)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def jload(p):
    return json.loads(Path(p).read_bytes())


def tree(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args(argv).out.resolve()
    if out.parent.parent != EXP.resolve() or not out.parent.name.startswith('SHORT-CLOSE-NATIVE229-CLOSE-V-'):
        print('output must be research/experiments/SHORT-CLOSE-NATIVE229-CLOSE-V-*/<fresh child>', file=sys.stderr)
        return 2
    out.mkdir(parents=True)

    watched = {'run_root': tree(RUN), 'grant_dir': tree(GRANT_DIR), 'dispatch': sha(DISPATCH),
               'reader': tree(READER_DIR), 'adapter_v3': tree(ADAPTER_V3)}
    checks, facts = [], {}

    def check(name, ok, detail=None):
        checks.append({'check': name, 'passed': bool(ok), **({'detail': detail} if detail is not None else {})})
        return bool(ok)

    # ---- pins: frozen reader, adapter, grant, dispatch slot --------------------------------------------------------
    check('reader freeze hash', sha(READER_DIR / 'freeze.json') == READER_FREEZE)
    rf = jload(READER_DIR / 'freeze.json')
    check('reader files match their freeze', all(sha(READER_DIR / n) == r['sha256'] for n, r in rf['artifact_files'].items()))
    check('adapter V3 freeze hash', sha(ADAPTER_V3 / 'freeze.json') == ADAPTER_FREEZE)
    spec = importlib.util.spec_from_file_location('frozen_reader_229', READER_DIR / 'raw_audit.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    grant = jload(GRANT_DIR / 'admitted-grant.json')
    check('grant hash equals dispatch grant_sha256', sha(GRANT_DIR / 'admitted-grant.json') == GRANT_SHA == jload(DISPATCH)['native_slot']['grant_sha256'])
    check('grant binds adapter V3, reader and this run root', grant['adapter_freeze_sha256'] == ADAPTER_FREEZE and
          grant['auditor_freeze']['sha256'] == READER_FREEZE and Path(grant['run_root']) == RUN and grant['lease_sequence'] == 229 and
          grant['max_native_launches'] == 12 and grant['max_concurrent_native'] == 2 and grant['retry'] is False and grant['one_attempt_per_case'] is True)
    slot = jload(DISPATCH)['native_slot']
    check('dispatch slot still the 229 lease for this run (not yet released)', slot['owner'] == grant['owner'] and slot['sequence'] == 229 and Path(slot['run_root']) == RUN)
    lease = jload(GRANT_DIR / 'lease-activated.json')
    check('lease record matches grant', lease['grant_sha256'] == GRANT_SHA and lease['lease_sequence'] == 229 and lease['native_launches'] == 0)
    exe = grant['executables']['direct']
    engine = next(r for r in grant['engine_files'] if Path(r['path']).resolve() == Path(exe).resolve())

    # ---- run-level report --------------------------------------------------------------------------------------------
    top = jload(RUN / 'verification.json')
    facts['run_state'] = top['state']
    facts['run_error'] = top['error']
    check('trial stopped with no retry, six attempts, no DIMR', top['state'] == 'stopped_no_retry_NOT_ACCEPTED' and top['attempts'] == sorted(CASES) and
          top['actual_manifest_count'] == 6 and top['retry'] is False and not any('dimr' in p.name for p in RUN.iterdir()))
    check('no cleanup/audit errors and no manifest-polling errors', not list((RUN / 'cleanup-errors').iterdir()) and
          not list((RUN / 'audit-errors').iterdir()) and top['manifest_polling_errors'] == [] and 'client_errors' not in top)

    def expected_for(case):
        folder = RUN / case
        return {'route': 'direct', 'argv': [exe, '--autostartstop', 'f34.mdu'], 'working_directory': str(folder / 'model'),
                'run_directory': str(folder), 'executable_sha256': engine['sha256'], 'profile_name': 'short'}

    # ---- (1) six original lifetime / Job / collector closures --------------------------------------------------------
    records, audits = {}, {}
    for case in CASES:
        record = jload(RUN / case / 'manifest.json')
        records[case] = record
        raw = reader.audit_record(record, expected_for(case))
        fam = FAMILY[case]
        state = reader.assert_public_state(record, {'family': fam, 'route': 'direct', 'allow_natural_race': fam in ('timeout', 'cancel', 'control'),
                                                    **({'control_terminal_states': ['cancelled']} if fam == 'control' else {})})
        saved = jload(RUN / 'audits' / (case + '.json'))
        audits[case] = {
            'recorded_state': record['state'], 'expected_state': EXPECTED_STATE[fam],
            'audit_state': raw['audit_state'], 'lifetime_passed': raw['lifetime_passed'], 'original_job_empty': raw['original_job_empty'],
            'actual_job_close_passed': raw['actual_job_close_passed'], 'collector_close_passed': raw['collector_close_passed'],
            'original_member_count': raw.get('original_member_count'), 'notification_evidence': raw.get('notification_evidence'),
            'kill_attribution_claimed': raw['kill_attribution_claimed'], 'physics_assessed': raw['physics_assessed'],
            'state_passed': state['passed'], 'state_case_success': state['case_success'], 'stop_achieved': state['stop_achieved'],
            'members': [{'pid': m['identity']['pid'], 'role': m['role'], 'exit_code': m['exit_code'], 'exit_confirmed': m['exit_confirmed'],
                         'pre_request_category': m['pre_request_category']} for m in raw['members']],
            'rerun_equals_adapter_saved_result': raw == saved['independent_raw_audit'] and state == saved['independent_state_assertion'],
            'manifest_sha256': sha(RUN / case / 'manifest.json'), 'manifest_sha256_equals_adapter_receipt': sha(RUN / case / 'manifest.json') == saved['manifest_sha256']}
        acct = (record['termination']['job_accounting'] if 'termination' in record else record['ownership']['normal_exit']['job_accounting'])['values']
        audits[case]['job_accounting_final'] = {'TotalProcesses': acct['TotalProcesses'], 'ActiveProcesses': acct['ActiveProcesses']}
        job_close = record['ownership']['job_close']
        audits[case]['CloseHandle_Job'] = {'return_value': job_close['return_value'], 'return_type': job_close['return_type'], 'succeeded': job_close['succeeded']}
        audits[case]['collector_close'] = job_close['collector_close']['return_value']['state']
    check('six raw audits: qualified_full_lifetime_close with Job empty, real Job CloseHandle and collector closed',
          all(a['audit_state'] == 'qualified_full_lifetime_close' and a['lifetime_passed'] and a['original_job_empty'] and a['actual_job_close_passed'] and
              a['collector_close_passed'] and a['job_accounting_final']['ActiveProcesses'] == 0 and
              a['job_accounting_final']['TotalProcesses'] == a['original_member_count'] and a['CloseHandle_Job']['succeeded'] is True and
              type(a['CloseHandle_Job']['return_value']) is int and a['CloseHandle_Job']['return_value'] != 0 and a['collector_close'] == 'closed'
              for a in audits.values()), {c: a['audit_state'] for c, a in audits.items()})
    check('every retained member HANDLE exit confirmed (all six)', all(m['exit_confirmed'] for a in audits.values() for m in a['members']),
          {c: len(a['members']) for c, a in audits.items()})
    check('reruns with the frozen reader equal the adapter-saved results byte-for-byte (six)',
          all(a['rerun_equals_adapter_saved_result'] and a['manifest_sha256_equals_adapter_receipt'] for a in audits.values()))
    check('public states match the declared case outcomes and none is cleanup_failed',
          all(a['recorded_state'] == a['expected_state'] and a['state_passed'] and a['state_case_success'] for a in audits.values()),
          {c: a['recorded_state'] for c, a in audits.items()})
    check('both forced targets achieved a stop (not natural races)', audits['timeout-direct']['stop_achieved'] and audits['cancel-direct']['stop_achieved'])
    check('no kill attribution or physics claimed by the reader', not any(a['kill_attribution_claimed'] or a['physics_assessed'] for a in audits.values()))
    check('no record is non-terminal', all(r['state'] in reader.TERMINAL_STATES for r in records.values()))

    # concurrency bound (grant: <= 2 native owners at once) from the raw owner timelines
    spans = []
    for case, r in records.items():
        spans.append((reader.stamp(r['started_at_utc']), 1, case))
        spans.append((reader.stamp(r['ownership']['job_close']['finished_at_utc']), -1, case))
    live = peak = 0
    for _, delta, _ in sorted(spans, key=lambda x: (x[0], x[1])):
        live += delta
        peak = max(peak, live)
    facts['peak_concurrent_native_owners_from_raw_timelines'] = peak
    check('grant bound: peak concurrent owners <= 2 and launches <= 12', peak <= 2 and len(records) <= 12, peak)

    # ---- (2) six observer CloseHandle receipts -----------------------------------------------------------------------
    observers = {}
    for case in CASES:
        cap = jload(RUN / 'observations' / (case + '-capture.json'))
        wrapper = jload(RUN / 'observations' / (case + '-observer-close.json'))
        record = records[case]
        ident = record['ownership']['native_identity']
        key = (ident['pid'], ident['creation_time_100ns'])
        row = {'capture_live': cap['state'] == 'live' and cap['in_a_job'] is True, 'same_birth_as_original_owner': (cap['pid'], cap['creation_time_100ns']) == key,
               'image_equals_argv0': PureWindowsPath(cap['image']) == PureWindowsPath(record['argv'][0]), 'observer_id': cap['observer_id']}
        try:
            reader.observer(cap, key, record['argv'][0], cap['observer_id'], live=True)
            reader.observer_close(wrapper, cap['observer_id'], key, record['argv'][0], wrapper['final_snapshot'], reader.observer(wrapper['final_snapshot'], key, record['argv'][0], cap['observer_id'], live=False))
            row['frozen_reader_accepts_close_wrapper'] = True
        except Exception as exc:  # noqa: BLE001
            row['frozen_reader_accepts_close_wrapper'] = False
            row['reader_error'] = '%s: %s' % (type(exc).__name__, exc)
        close = wrapper['close']
        row.update(final_snapshot_state=wrapper['final_snapshot']['state'], api=close['api'], attempted=close['attempted'], succeeded=close['succeeded'],
                   return_value=close['return_value'], return_type=close['return_type'], same_observer_object=close['observer_id'] == cap['observer_id'],
                   identity_matches=(close['identity']['pid'], close['identity']['creation_time_100ns']) == key,
                   ordered=reader.stamp(wrapper['final_snapshot']['observed_at_utc']) <= reader.stamp(close['started_at_utc']) <= reader.stamp(close['finished_at_utc']),
                   receipt_sha256=sha(RUN / 'observations' / (case + '-observer-close.json')))
        observers[case] = row
    check('six observer CloseHandle receipts: real int nonzero, same object/birth/image, exited final sample, ordered, accepted by the frozen reader',
          all(o['capture_live'] and o['same_birth_as_original_owner'] and o['image_equals_argv0'] and o['api'] == 'CloseHandle' and o['attempted'] is True and
              o['succeeded'] is True and o['return_type'] == 'int' and type(o['return_value']) is int and o['return_value'] != 0 and o['same_observer_object'] and
              o['identity_matches'] and o['ordered'] and o['final_snapshot_state'] == 'exited' and o['frozen_reader_accepts_close_wrapper'] for o in observers.values()),
          {c: o['return_value'] for c, o in observers.items()})
    check('six distinct observer objects', len({o['observer_id'] for o in observers.values()}) == 6)

    # ---- (3) eight public-client invocations -------------------------------------------------------------------------
    inv = {}
    for folder in sorted((RUN / 'commands').iterdir()):
        d = jload(folder / 'invocation.json')
        payload = d['payload']
        kind = 'start' if folder.name.endswith('-start') else 'cancel'
        case = folder.name.rsplit('-', 1)[0]
        record_state = records[case]['state']
        want_code, want_ok = (0, True) if kind == 'cancel' or record_state == 'completed' else (5, False)
        inv[folder.name] = {
            'returncode': d['returncode'], 'protocol_version': payload.get('protocol_version'), 'ok': payload.get('ok'),
            'error_code': (payload.get('error') or {}).get('code'), 'command_started': d['command_started'], 'command_delivery': d['command_delivery'],
            'go_attempted': d['go_attempted'], 'expected_returncode': want_code, 'expected_ok': want_ok,
            'stdout_sha256_matches_file': sha(folder / 'stdout.json') == d['stdout_sha256'], 'stderr_sha256_matches_file': sha(folder / 'stderr.txt') == d['stderr_sha256'],
            'stderr_bytes': (folder / 'stderr.txt').stat().st_size, 'argv_head': Path(d['argv'][3]).name,
            'invocation_sha256': sha(folder / 'invocation.json')}
    check('eight public invocations exist, each exited with an integer code and parsed protocol-2 JSON', len(inv) == 8 and all(
        type(v['returncode']) is int and v['protocol_version'] == 2 for v in inv.values()), sorted(inv))
    check('exit codes and ok flags match the recorded terminal states (0 completed/cancel-request, 5 for failed/timed_out/cancelled starts)',
          all(v['returncode'] == v['expected_returncode'] and v['ok'] is v['expected_ok'] for v in inv.values()),
          {k: (v['returncode'], v['error_code']) for k, v in inv.items()})
    check('every go was delivered exactly once (no unknown/unstarted client)', all(v['command_started'] is True and v['command_delivery'] == 'delivered' and v['go_attempted'] is True
                                                                                  for v in inv.values()))
    check('invocation receipts match their stdout/stderr files', all(v['stdout_sha256_matches_file'] and v['stderr_sha256_matches_file'] for v in inv.values()))
    facts['stderr_bytes_nonzero'] = {k: v['stderr_bytes'] for k, v in inv.items() if v['stderr_bytes']}

    # ---- (4) control survival: reader verdicts, then each gate separately -------------------------------------------
    survival = {}
    for target in ('timeout-direct', 'cancel-direct'):
        bundle = jload(RUN / 'observations' / (target + '-survival-final.json'))
        saved = jload(RUN / 'audits' / (target + '-control-survival.json'))
        again = reader.audit_control_survival(records[target], records['control-direct'], bundle, expected_for('control-direct'))
        gates = per_gate(reader, bundle, records[target], records['control-direct'], expected_for('control-direct'))
        survival[target] = {'saved_verdict': {k: saved[k] for k in ('audit_state', 'passed', 'control_lifetime_passed', 'observer_same_handle_confirmed')},
                            'saved_errors': saved['errors'], 'rerun_audit_state': again['audit_state'], 'rerun_equals_saved': again == saved,
                            'bundle_sha256': sha(RUN / 'observations' / (target + '-survival-final.json')),
                            'saved_observations_digest_matches_bundle': saved['observations_sha256'] == reader.digest(bundle), 'gates': gates}
    check('frozen reader rerun reproduces both saved survival verdicts', all(s['rerun_equals_saved'] and s['saved_observations_digest_matches_bundle'] for s in survival.values()))
    check('timeout survival: independent_control_survival_confirmed', survival['timeout-direct']['rerun_audit_state'] == 'independent_control_survival_confirmed')
    check('cancel survival: refused by the frozen reader (NOT confirmed)', survival['cancel-direct']['rerun_audit_state'] == 'refused' and
          [e['reason'] for e in survival['cancel-direct']['saved_errors']] == ['control_after->control_pre_cleanup: monotonic stamp reused by a different snapshot'])
    check('gate-by-gate method agrees with the reader on the timeout bundle (all gates pass)', all(g['passed'] for g in survival['timeout-direct']['gates']))
    failed = [g['gate'] for g in survival['cancel-direct']['gates'] if not g['passed']]
    check('cancel bundle: exactly one gate fails (control_after -> control_pre_cleanup); every other gate passes', failed == ['control_after->control_pre_cleanup'], failed)

    # monotonic stamps: whole milliseconds that advance in ~one GetTickCount64 tick (15.625 ms: 15/16 ms steps)
    per_observer = {}
    for path in sorted((RUN / 'observations').glob('*.json')):
        stack = [jload(path)]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if 'monotonic_ns' in item:
                    per_observer.setdefault(item['observer_id'], set()).add(item['monotonic_ns'])
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    all_values = [v for values in per_observer.values() for v in values]
    gaps = [b2 - a2 for values in per_observer.values() for a2, b2 in zip(sorted(values), sorted(values)[1:])]
    facts['monotonic_stamps'] = {'observers': len(per_observer), 'distinct_values': len(all_values), 'all_whole_milliseconds': all(v % 1_000_000 == 0 for v in all_values),
                                 'min_gap_between_distinct_stamps_ms': min(gaps) / 1e6, 'reported_tick_ms': TICK_NS / 1e6}
    check('monotonic stamps are whole milliseconds and distinct stamps of one observer differ by at least ~one 15.625 ms tick',
          facts['monotonic_stamps']['all_whole_milliseconds'] and min(gaps) >= 15_000_000, facts['monotonic_stamps'])
    bundle = jload(RUN / 'observations/cancel-direct-survival-final.json')
    ca, cp = bundle['control_after'], bundle['control_pre_cleanup']
    facts['cancel_tie'] = {'control_after': {'state': ca['state'], 'utc': ca['observed_at_utc'], 'monotonic_ns': ca['monotonic_ns']},
                           'control_pre_cleanup': {'state': cp['state'], 'utc': cp['observed_at_utc'], 'monotonic_ns': cp['monotonic_ns']},
                           'same_observer_object': ca['observer_id'] == cp['observer_id'], 'monotonic_equal': ca['monotonic_ns'] == cp['monotonic_ns'],
                           'utc_delta_ms': (reader.stamp(cp['observed_at_utc']) - reader.stamp(ca['observed_at_utc'])).total_seconds() * 1000,
                           'tick_ms': TICK_NS / 1e6,
                           'distinct_snapshots': ca != cp}
    check('tie is two distinct live samples of one observer within one coarse tick', facts['cancel_tie']['monotonic_equal'] and facts['cancel_tie']['same_observer_object'] and
          facts['cancel_tie']['distinct_snapshots'] and 0 < facts['cancel_tie']['utc_delta_ms'] < facts['cancel_tie']['tick_ms'] and ca['state'] == cp['state'] == 'live')

    # separate numerical gate presence (not part of the release verdict)
    outputs = jload(RUN / 'audits/natural-direct-outputs.json')
    facts['natural_outputs_present'] = {'history_final_time_matches': outputs['history']['final_time_matches'], 'map_final_time_matches': outputs['map']['final_time_matches'],
                                        'final_restart_present': outputs['final_restart_present'], 'comparison191_exists': (RUN / 'comparison191.json').exists()}

    # ---- immutability of every input ----------------------------------------------------------------------------------
    after = {'run_root': tree(RUN), 'grant_dir': tree(GRANT_DIR), 'dispatch': sha(DISPATCH), 'reader': tree(READER_DIR), 'adapter_v3': tree(ADAPTER_V3)}
    check('every original byte unchanged during readback (run root, grant folder, dispatch, reader, adapter V3)', after == watched,
          {'run_root_files': len(after['run_root']), 'grant_files': len(after['grant_dir'])})

    release_checks = [c for c in checks if c['passed'] is False]
    result = {
        'schema': 'SHORT-CLOSE-NATIVE229-CLOSE-V-readback-1', 'node': 'NATIVE229-CLOSE-V', 'native_launches': 0,
        'reader_freeze_sha256': READER_FREEZE, 'adapter_freeze_sha256': ADAPTER_FREEZE, 'grant_sha256': GRANT_SHA,
        'dispatch_sha256': watched['dispatch'], 'run_root': str(RUN),
        'checks_total': len(checks), 'checks_failed': len(release_checks), 'checks': checks,
        'cases': audits, 'observer_close_receipts': observers, 'public_invocations': inv, 'control_survival': survival, 'facts': facts,
        'run_root_manifest_sha256': {c: audits[c]['manifest_sha256'] for c in CASES}, 'run_root_file_count': len(after['run_root'])}
    (out / 'verification.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'checks_total': len(checks), 'checks_failed': len(release_checks), 'failed': [c['check'] for c in release_checks]}))
    return 0 if not release_checks else 1


def per_gate(reader, b, target, control, expected_control):
    """Evaluate each audit_control_survival gate on its own, using the frozen reader's helpers unchanged."""
    gates = []

    def gate(name, fn):
        try:
            fn()
            gates.append({'gate': name, 'passed': True})
        except Exception as exc:  # noqa: BLE001
            gates.append({'gate': name, 'passed': False, 'reason': '%s: %s' % (type(exc).__name__, exc)})
    exe = control['argv'][0]
    tb_id = reader.birth(target['ownership']['native_identity'])
    cb_id = reader.birth(control['ownership']['native_identity'])
    to, co = b['target_before']['observer_id'], b['control_before']['observer_id']
    s = {}

    def sample(key, ident, oid, live):
        s[key] = reader.observer(b[key], ident, exe, oid, live=live)
    gate('control original lifetime/Job/collector audit', lambda: reader.need(reader.audit_record(control, expected_control)['audit_state'] == 'qualified_full_lifetime_close', 'control audit'))
    gate('distinct runs, births and private Jobs', lambda: reader.need(
        target['run_id'] != control['run_id'] and tb_id != cb_id and target['ownership']['job_close']['job_instance_token'] != control['ownership']['job_close']['job_instance_token'], 'not distinct'))
    gate('same selected executable and route', lambda: reader.need(
        reader.image(target['argv'][0]) == reader.image(exe) and target['route'] == control['route'] and target['executable_sha256'] == control['executable_sha256'], 'differs'))
    gate('target and control use distinct observer objects', lambda: reader.need(to != co, 'shared'))
    for key, ident, oid, live in (('target_before', tb_id, to, True), ('target_exit', tb_id, to, False), ('control_before', cb_id, co, True),
                                  ('control_after', cb_id, co, True), ('control_pre_cleanup', cb_id, co, True), ('control_final', cb_id, co, False)):
        gate('sample ' + key + (' live' if live else ' exited'), lambda key=key, ident=ident, oid=oid, live=live: sample(key, ident, oid, live))
    if len(s) == 6:
        gate('control_before->control_after', lambda: reader.later(b['control_before'], s['control_before'], b['control_after'], s['control_after'], 'control_before->control_after'))
        gate('control_after->control_pre_cleanup', lambda: reader.later(b['control_after'], s['control_after'], b['control_pre_cleanup'], s['control_pre_cleanup'],
                                                                         'control_after->control_pre_cleanup', identical_ok=True))
        gate('control_pre_cleanup->control_final', lambda: reader.later(b['control_pre_cleanup'], s['control_pre_cleanup'], b['control_final'], s['control_final'],
                                                                         'control_pre_cleanup->control_final'))
        gate('target_before->target_exit', lambda: reader.later(b['target_before'], s['target_before'], b['target_exit'], s['target_exit'], 'target_before->target_exit'))
        terminal = reader.stamp(target['ownership']['job_close']['finished_at_utc'])
        gate('control_after and target_exit follow the actual original target close', lambda: reader.need(terminal <= s['target_exit'][0] and terminal <= s['control_after'][0], 'order'))
        trigger = reader.stamp(target['termination']['termination_request']['started_at_utc'])
        gate('target/control live samples precede the actual target trigger', lambda: reader.need(s['target_before'][0] <= trigger and s['control_before'][0] <= trigger, 'order'))
        creq = reader.stamp(control['termination']['termination_request']['started_at_utc'])
        gate('control_pre_cleanup precedes the control own stop request', lambda: reader.need(s['control_pre_cleanup'][0] <= creq, 'order'))
        gate('control_final follows the control original close', lambda: reader.need(s['control_final'][0] >= reader.stamp(control['ownership']['job_close']['finished_at_utc']), 'order'))
        gate('target observer close wrapper', lambda: reader.observer_close(b['target_observer_close'], to, tb_id, exe, b['target_exit'], s['target_exit']))
        gate('control observer close wrapper', lambda: reader.observer_close(b['control_observer_close'], co, cb_id, exe, b['control_final'], s['control_final']))
    return gates


if __name__ == '__main__':
    raise SystemExit(main())
