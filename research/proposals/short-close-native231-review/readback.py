"""NATIVE231-RELEASE-V: file-only postmortem of the real lease-231 V6 trial (all twelve cases, both routes).

Reads only retained JSON/log/NetCDF files with the hash-pinned frozen reader and the pinned original numerical reader
(verify_serial_exit.py: numpy/netCDF4 file reads). No process, PID, Job, HANDLE, FFI, native or GUI query; nothing is written
outside the fresh --out folder; no Git.

  python -I -B readback.py --out research/experiments/SHORT-CLOSE-NATIVE231-RELEASE-V-<stamp>/<fresh-child>
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
RUN = EXP / 'SHORT-CLOSE-G-native-rev04-231-20261105-01'
GRANT_DIR = EXP / 'SHORT-CLOSE-NATIVE-G-20261105-02'
RUN229 = EXP / 'SHORT-CLOSE-G-native-rev04-229-20261105-01'
GRANT_DIR229 = EXP / 'SHORT-CLOSE-NATIVE-G-20261105-01'
DISPATCH = EXP / 'roadmap-coordinator-20261104/dispatch.json'
READER_DIR = REPO / 'research/proposals/short-close-native-reader'
ADAPTER_V6 = REPO / 'research/proposals/short-close-native-adapter-v6'
SERIAL = REPO / 'research/workflows/verification/verify_serial_exit.py'
OBSERVER = REPO / 'research/workflows/verification/verify_water_quality_offline_lifecycle_observe.py'
READER_FREEZE = '980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62'
ADAPTER_FREEZE = '53a1db831f37b6a09b925711cd0beb19f0dd8b325e0d26f6f4436fd6776e82e5'
GRANT_SHA = '8789014b3bfad0ade281108254671ab0d101a51dbc88cfe2538097b21d4a0c5a'
PLAN_SHA = 'd5427cb066def06b7291c419ee8f5030d973a52e5e78f6be56146d78339a1913'
RUN229_LISTING = 'e0e3520a866441d1707b005b7385916dd6a5c934c8dfe2bc4fec87dc4fb04c82'
FAMILIES = ['natural', 'bad-mesh', 'empty-bc', 'control', 'timeout', 'cancel']
ROUTES = ['direct', 'dimr']
CASES = ['%s-%s' % (f, r) for r in ROUTES for f in FAMILIES]
EXPECTED_STATE = {'natural': 'completed', 'bad-mesh': 'failed', 'empty-bc': 'failed', 'control': 'cancelled', 'timeout': 'timed_out', 'cancel': 'cancelled'}
INIT = 'Done writing initial output to file(s).'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def jload(p):
    return json.loads(Path(p).read_bytes())


def tree(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args(argv).out.resolve()
    if out.parent.parent != EXP.resolve() or not out.parent.name.startswith('SHORT-CLOSE-NATIVE231-RELEASE-V-'):
        print('output must be research/experiments/SHORT-CLOSE-NATIVE231-RELEASE-V-*/<fresh child>', file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    watched = {'run231': tree(RUN), 'grant231': tree(GRANT_DIR), 'run229': tree(RUN229), 'grant229': tree(GRANT_DIR229), 'dispatch': sha(DISPATCH),
               'reader': tree(READER_DIR), 'adapter_v6': tree(ADAPTER_V6), 'serial_reader': sha(SERIAL), 'observer': sha(OBSERVER)}
    checks, facts = [], {}

    def check(name, ok, detail=None):
        checks.append({'check': name, 'passed': bool(ok), **({'detail': detail} if detail is not None else {})})
        return bool(ok)

    # ---- pins: frozen reader, adapter V6, fresh grant, dispatch slot ---------------------------------------------------------
    check('reader freeze hash and files', sha(READER_DIR / 'freeze.json') == READER_FREEZE and
          all(sha(READER_DIR / n) == r['sha256'] for n, r in jload(READER_DIR / 'freeze.json')['artifact_files'].items()))
    check('adapter V6 freeze hash and files', sha(ADAPTER_V6 / 'freeze.json') == ADAPTER_FREEZE and
          all(sha(ADAPTER_V6 / n) == r['sha256'] for n, r in jload(ADAPTER_V6 / 'freeze.json')['artifact_files'].items()))
    reader = load_module(READER_DIR / 'raw_audit.py', 'frozen_reader_231')
    serial = load_module(SERIAL, 'pinned_serial_reader_231')
    grant = jload(GRANT_DIR / 'admitted-grant.json')
    slot = jload(DISPATCH)['native_slot']
    check('fresh grant hash equals the canonical slot grant_sha256', sha(GRANT_DIR / 'admitted-grant.json') == GRANT_SHA == slot['grant_sha256'])
    check('grant binds adapter V6, plan, reader, run root and bounds', grant['adapter_freeze_sha256'] == ADAPTER_FREEZE and grant['predeclared_sha256'] == PLAN_SHA and
          grant['auditor_freeze']['sha256'] == READER_FREEZE and Path(grant['run_root']) == RUN and grant['lease_sequence'] == 231 and grant['native_authorized'] is True and
          grant['max_native_launches'] == 12 and grant['max_concurrent_native'] == 2 and grant['retry'] is False and grant['one_attempt_per_case'] is True and
          grant['coordinator_review_receipt_sha256'] == sha(GRANT_DIR / 'composition-review.json'))
    check('every file pin in the grant still hashes to its pin (package, runtime contract, reader, review, engines, research dependencies)', all(
        sha(row['path']) == row['sha256'] for row in [grant['package_freeze'], grant['runtime_contract'], grant['auditor_freeze'], grant['audit_module'],
                                                      grant['composition_review'], *grant['engine_files'], *grant['research_dependencies'].values()]))
    check('observer and numerical reader are the pinned canonical sources', Path(grant['research_dependencies']['observer']['path']) == OBSERVER and
          Path(grant['research_dependencies']['raw_output_reader']['path']) == SERIAL)
    check('canonical slot is still the active 231 lease for this grant and run (not yet released)', slot['owner'] == grant['owner'] and slot['sequence'] == 231 and
          Path(slot['grant']) == GRANT_DIR / 'admitted-grant.json' and Path(slot['run_root']) == RUN)
    lease = jload(GRANT_DIR / 'lease-activated.json')
    check('lease record matches the grant and recorded no launches at activation', lease['grant_sha256'] == GRANT_SHA and lease['lease_sequence'] == 231 and lease['native_launches'] == 0)

    # ---- run-level report ------------------------------------------------------------------------------------------------------
    top = jload(RUN / 'verification.json')
    facts['run_state'] = top['state']
    check('report: passed_all12, 12 distinct attempts, 12 manifests, no retry, bounds as granted', top['state'] == 'passed_all12_lifetime_close_isolation_and_raw191' and
          top['attempts'] == sorted(CASES) and top['actual_manifest_count'] == 12 and top['max_native_launches'] == 12 and top['max_concurrent_native'] == 2 and top['retry'] is False)
    check('no cleanup, audit or client errors; no manifest-polling errors; no unstarted/uncertain-client receipts', not list((RUN / 'cleanup-errors').iterdir()) and
          not list((RUN / 'audit-errors').iterdir()) and top['manifest_polling_errors'] == [] and 'client_errors' not in top and
          not list((RUN / 'observations').glob('*unstarted-client*')))

    def expected_for(case):
        route = case.rsplit('-', 1)[1]
        folder = RUN / case
        exe = grant['executables'][route]
        engine = next(r for r in grant['engine_files'] if Path(r['path']).resolve() == Path(exe).resolve())
        return {'route': route, 'argv': [exe, '--autostartstop', 'f34.mdu'] if route == 'direct' else [exe, 'dimr_config.xml'],
                'working_directory': str(folder / 'model' if route == 'direct' else folder), 'run_directory': str(folder),
                'executable_sha256': engine['sha256'], 'profile_name': 'short'}

    # ---- (1) twelve original lifetime / Job / collector closures + states ----------------------------------------------------------
    records, audits = {}, {}
    for case in CASES:
        fam, route = case.rsplit('-', 1)[0], case.rsplit('-', 1)[1]
        record = jload(RUN / case / 'manifest.json')
        records[case] = record
        raw = reader.audit_record(record, expected_for(case))
        state = reader.assert_public_state(record, {'family': fam, 'route': route, 'allow_natural_race': fam in ('timeout', 'cancel', 'control'),
                                                    **({'control_terminal_states': ['cancelled']} if fam == 'control' else {})})
        saved = jload(RUN / 'audits' / (case + '.json'))
        job_close = record['ownership']['job_close']
        acct = (record['termination']['job_accounting'] if 'termination' in record else record['ownership']['normal_exit']['job_accounting'])['values']
        audits[case] = {
            'route': route, 'recorded_state': record['state'], 'expected_state': EXPECTED_STATE[fam], 'returncode_recorded': record['returncode'],
            'audit_state': raw['audit_state'], 'lifetime_passed': raw['lifetime_passed'], 'original_job_empty': raw['original_job_empty'],
            'actual_job_close_passed': raw['actual_job_close_passed'], 'collector_close_passed': raw['collector_close_passed'],
            'original_member_count': raw.get('original_member_count'), 'notification_evidence': raw.get('notification_evidence'),
            'kill_attribution_claimed': raw['kill_attribution_claimed'], 'physics_assessed': raw['physics_assessed'],
            'state_passed': state['passed'], 'state_case_success': state['case_success'], 'stop_achieved': state['stop_achieved'],
            'members': [{'pid': m['identity']['pid'], 'role': m['role'], 'exit_code': m['exit_code'], 'exit_confirmed': m['exit_confirmed'],
                         'pre_request_category': m['pre_request_category']} for m in raw['members']],
            'job_accounting_final': {'TotalProcesses': acct['TotalProcesses'], 'ActiveProcesses': acct['ActiveProcesses']},
            'CloseHandle_Job': {'return_value': job_close['return_value'], 'return_type': job_close['return_type'], 'succeeded': job_close['succeeded']},
            'collector_close': job_close['collector_close']['return_value']['state'],
            'stop_reason': record.get('stop_reason'), 'request_reason': (record.get('termination') or {}).get('termination_request', {}).get('reason'),
            'rerun_equals_adapter_saved_result': raw == saved['independent_raw_audit'] and state == saved['independent_state_assertion'],
            'manifest_sha256': sha(RUN / case / 'manifest.json'), 'manifest_sha256_equals_adapter_receipt': sha(RUN / case / 'manifest.json') == saved['manifest_sha256']}
    check('twelve raw audits: qualified_full_lifetime_close, Job empty, real Job CloseHandle (int nonzero), collector closed, final accounting Active=0 and Total=members',
          all(a['audit_state'] == 'qualified_full_lifetime_close' and a['lifetime_passed'] and a['original_job_empty'] and a['actual_job_close_passed'] and a['collector_close_passed'] and
              a['job_accounting_final']['ActiveProcesses'] == 0 and a['job_accounting_final']['TotalProcesses'] == a['original_member_count'] and
              a['CloseHandle_Job']['succeeded'] is True and type(a['CloseHandle_Job']['return_value']) is int and a['CloseHandle_Job']['return_value'] != 0 and
              a['collector_close'] == 'closed' for a in audits.values()), {c: (a['audit_state'], a['original_member_count']) for c, a in audits.items()})
    check('every retained member HANDLE exit is confirmed (all twelve)', all(m['exit_confirmed'] for a in audits.values() for m in a['members']),
          {c: len(a['members']) for c, a in audits.items()})
    check('frozen-reader reruns equal the adapter-saved audits and state assertions exactly (twelve)',
          all(a['rerun_equals_adapter_saved_result'] and a['manifest_sha256_equals_adapter_receipt'] for a in audits.values()))
    check('public states match case outcomes (completed/failed/failed/cancelled/timed_out/cancelled per route); none cleanup_failed; no natural race',
          all(a['recorded_state'] == a['expected_state'] and a['state_passed'] and a['state_case_success'] for a in audits.values()),
          {c: a['recorded_state'] for c, a in audits.items()})
    check('all four forced targets/controls achieved a stop with the declared reason (timeout -> run_timeout, cancel/control -> run_cancelled)',
          all(audits[c]['stop_achieved'] if c.startswith(('timeout', 'cancel')) else True for c in CASES) and
          all(audits[c]['request_reason'] == ('run_timeout' if c.startswith('timeout') else 'run_cancelled') and audits[c]['stop_reason'] == audits[c]['request_reason']
              for c in CASES if c.startswith(('timeout', 'cancel', 'control'))))
    check('natural: root and every member exit 0 on both routes; failures: native nonzero root', all(
        all(m['exit_code'] == 0 for m in audits['natural-' + r]['members']) and audits['bad-mesh-' + r]['returncode_recorded'] != 0 and
        audits['empty-bc-' + r]['returncode_recorded'] != 0 for r in ROUTES))
    check('no kill attribution or physics claimed by the lifetime reader', not any(a['kill_attribution_claimed'] or a['physics_assessed'] for a in audits.values()))
    check('no record is non-terminal', all(r['state'] in reader.TERMINAL_STATES for r in records.values()))

    spans = []
    for case, r in records.items():
        spans.append((reader.stamp(r['started_at_utc']), 1))
        spans.append((reader.stamp(r['ownership']['job_close']['finished_at_utc']), -1))
    live = peak = 0
    for _, delta in sorted(spans, key=lambda x: (x[0], x[1])):
        live += delta
        peak = max(peak, live)
    facts['peak_concurrent_native_owners_from_raw_timelines'] = peak
    check('grant bound: peak concurrent owners <= 2 and exactly 12 launches', peak <= 2 and len(records) == 12, peak)

    # ---- physical initialization / diagnostic markers --------------------------------------------------------------------------------
    markers = {}
    for case in CASES:
        fam = case.rsplit('-', 1)[0]
        text = (RUN / case / 'stdout.log').read_text(encoding='utf-8', errors='replace')
        primary = ((records[case].get('diagnostics') or {}).get('primary_error') or {}).get('text', '')
        markers[case] = {'initial_output_written': INIT in text, 'primary_error_text': primary[:80],
                         'failed_open_netcdf': 'Failed to open: f34_net.nc' in primary, 'no_signals_polyline': 'No signals for polyline' in primary}
    check('initialization marker present for natural/control/timeout/cancel on both routes (engine reached initial output)',
          all(markers[c]['initial_output_written'] for c in CASES if c.split('-')[0] in ('natural', 'control', 'timeout', 'cancel')))
    check('failure families carry their specific initialization diagnostics and no initial output on both routes (bad-mesh: Failed to open f34_net.nc; empty-bc: No signals for polyline)',
          all(markers['bad-mesh-' + r]['failed_open_netcdf'] and not markers['bad-mesh-' + r]['initial_output_written'] and
              markers['empty-bc-' + r]['no_signals_polyline'] and not markers['empty-bc-' + r]['initial_output_written'] for r in ROUTES))

    # ---- (2) twelve observer CloseHandle receipts joined to captures -----------------------------------------------------------------
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
            final = reader.observer(wrapper['final_snapshot'], key, record['argv'][0], cap['observer_id'], live=False)
            reader.observer_close(wrapper, cap['observer_id'], key, record['argv'][0], wrapper['final_snapshot'], final)
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
    check('twelve observer CloseHandle receipts: real nonzero int, same observer object/birth/image as each live capture, exited final sample, ordered, accepted by the frozen reader',
          all(o['capture_live'] and o['same_birth_as_original_owner'] and o['image_equals_argv0'] and o['api'] == 'CloseHandle' and o['attempted'] is True and o['succeeded'] is True and
              o['return_type'] == 'int' and type(o['return_value']) is int and o['return_value'] != 0 and o['same_observer_object'] and o['identity_matches'] and o['ordered'] and
              o['final_snapshot_state'] == 'exited' and o['frozen_reader_accepts_close_wrapper'] for o in observers.values()), {c: o['return_value'] for c, o in observers.items()})
    check('twelve distinct observer objects', len({o['observer_id'] for o in observers.values()}) == 12)

    # ---- (3) sixteen public-client invocations ---------------------------------------------------------------------------------------
    inv = {}
    for folder in sorted((RUN / 'commands').iterdir()):
        d = jload(folder / 'invocation.json')
        payload = d['payload']
        kind = 'start' if folder.name.endswith('-start') else 'cancel'
        case = folder.name.rsplit('-', 1)[0]
        want_code, want_ok = (0, True) if kind == 'cancel' or records[case]['state'] == 'completed' else (5, False)
        inv[folder.name] = {'returncode': d['returncode'], 'protocol_version': payload.get('protocol_version'), 'ok': payload.get('ok'),
                            'error_code': (payload.get('error') or {}).get('code'), 'command_started': d['command_started'], 'command_delivery': d['command_delivery'],
                            'go_attempted': d['go_attempted'], 'expected_returncode': want_code, 'expected_ok': want_ok,
                            'stdout_matches_receipt': sha(folder / 'stdout.json') == d['stdout_sha256'], 'stderr_matches_receipt': sha(folder / 'stderr.txt') == d['stderr_sha256'],
                            'stderr_bytes': (folder / 'stderr.txt').stat().st_size, 'invocation_sha256': sha(folder / 'invocation.json')}
    check('sixteen public invocations (12 starts + 4 cancel requests), each returned an integer code with parsed protocol-2 JSON',
          len(inv) == 16 and sum(k.endswith('-start') for k in inv) == 12 and all(type(v['returncode']) is int and v['protocol_version'] == 2 for v in inv.values()), sorted(inv))
    check('exit codes and ok flags match terminal states (0 completed/cancel-request, 5 for failed/timed_out/cancelled starts)',
          all(v['returncode'] == v['expected_returncode'] and v['ok'] is v['expected_ok'] for v in inv.values()), {k: (v['returncode'], v['error_code']) for k, v in inv.items()})
    check('every go delivered exactly once; no unstarted or unknown-delivery client', all(v['command_started'] is True and v['command_delivery'] == 'delivered' and v['go_attempted'] is True for v in inv.values()))
    check('invocation receipts match their stdout/stderr files and stderr is empty', all(v['stdout_matches_receipt'] and v['stderr_matches_receipt'] and v['stderr_bytes'] == 0 for v in inv.values()))

    # ---- (4) four control-survival verdicts recomputed from the saved COMPLETE raw bundles ------------------------------------------------
    survival = {}
    required = {'schema', 'target_case_id', 'target_before', 'target_exit', 'control_before', 'control_after', 'control_pre_cleanup', 'control_final', 'target_observer_close', 'control_observer_close'}
    for route in ROUTES:
        for target in ('timeout-' + route, 'cancel-' + route):
            bundle = jload(RUN / 'observations' / (target + '-survival-final.json'))
            saved = jload(RUN / 'audits' / (target + '-control-survival.json'))
            control_case = 'control-' + route
            again = reader.audit_control_survival(records[target], records[control_case], bundle, expected_for(control_case))
            gates = per_gate(reader, bundle, records[target], records[control_case], expected_for(control_case))
            ca, cp = bundle['control_after'], bundle['control_pre_cleanup']
            survival[target] = {'bundle_keys_complete': set(bundle) == required, 'bundle_sha256': sha(RUN / 'observations' / (target + '-survival-final.json')),
                                'saved_audit_state': saved['audit_state'], 'rerun_audit_state': again['audit_state'], 'rerun_passed': again['passed'],
                                'rerun_equals_saved': again == saved, 'saved_digest_matches_bundle': saved['observations_sha256'] == reader.digest(bundle),
                                'errors': again['errors'], 'gates_total': len(gates), 'gates_passed': sum(g['passed'] for g in gates),
                                'adjacent_monotonic_strict': ca['monotonic_ns'] < cp['monotonic_ns'] and bundle['control_before']['monotonic_ns'] < ca['monotonic_ns'] <
                                cp['monotonic_ns'] < bundle['control_final']['monotonic_ns'] and bundle['target_before']['monotonic_ns'] < bundle['target_exit']['monotonic_ns'] <
                                bundle['target_observer_close']['final_snapshot']['monotonic_ns'] and
                                bundle['control_final']['monotonic_ns'] < bundle['control_observer_close']['final_snapshot']['monotonic_ns'],
                                'control_after_state': ca['state'], 'control_pre_cleanup_state': cp['state'], 'control_final_state': bundle['control_final']['state']}
    check('all four saved survival bundles are complete (10 keys) and their saved digests match the bundle content', all(s['bundle_keys_complete'] and s['saved_digest_matches_bundle'] for s in survival.values()), sorted(survival))
    check('frozen reader recomputed from the raw bundles: all four independent_control_survival_confirmed, equal to the saved verdicts',
          all(s['rerun_audit_state'] == 'independent_control_survival_confirmed' and s['rerun_passed'] and s['rerun_equals_saved'] and s['errors'] == [] for s in survival.values()),
          {t: s['rerun_audit_state'] for t, s in survival.items()})
    check('each survival verdict, evaluated gate by gate, passes all 20 gates; every adjacent transition is strictly increasing; control live at both post-target samples, exited at the end',
          all(s['gates_total'] == 20 and s['gates_passed'] == 20 and s['adjacent_monotonic_strict'] and s['control_after_state'] == s['control_pre_cleanup_state'] == 'live' and
              s['control_final_state'] == 'exited' for s in survival.values()))

    # ---- (5) independent NetCDF reread with the pinned original numerical reader --------------------------------------------------------
    numeric = {}
    for route in ROUTES:
        folder = RUN / ('natural-' + route)
        raw = serial.raw_outputs(folder, records['natural-' + route])
        saved = jload(RUN / 'audits' / ('natural-%s-outputs.json' % route))
        numeric[route] = {'history_final_time_matches': raw['history']['final_time_matches'], 'map_final_time_matches': raw['map']['final_time_matches'],
                          'history_seconds_first_last': [raw['history']['seconds'][0], raw['history']['seconds'][-1]], 'map_seconds_first_last': [raw['map']['seconds'][0], raw['map']['seconds'][-1]],
                          'history_units_calendar': [raw['history']['units'], raw['history']['calendar']], 'elevation_unit': raw['history']['elevation_unit'],
                          'final_restart_present': raw['final_restart_present'], 'restarts': [(Path(r['path']).name, r['final_time_matches']) for r in raw['restarts']],
                          'recomputed_equals_adapter_saved': raw == saved, 'raw_sha': {Path(raw[k]['path']).name: raw[k]['sha256'] for k in ('history', 'map')}}
    check('each natural route (600 s): CF history/map clocks span 0..600 s and match, final restart at 600 s present, elevation unit m; equal to the adapter-saved raw-output receipts',
          all(n['history_final_time_matches'] and n['map_final_time_matches'] and n['final_restart_present'] and n['history_seconds_first_last'] == [0.0, 600.0] and
              n['map_seconds_first_last'] == [0.0, 600.0] and n['elevation_unit'] == 'm' and sorted(n['restarts']) == [('f34_19900805_000000_rst.nc', False), ('f34_19900805_001000_rst.nc', True)] and
              n['recomputed_equals_adapter_saved'] for n in numeric.values()), numeric)
    left, right = {}, {}
    for route, store in (('direct', left), ('dimr', right)):
        for pattern in ('*_his.nc', '*_map.nc', '*_rst.nc'):
            for path in (RUN / ('natural-' + route) / 'model').rglob(pattern):
                assert path.name not in store, 'ambiguous dataset ' + path.name
                store[path.name] = path
    check('four corresponding datasets exist on both routes with identical names', set(left) == set(right) and len(left) == 4, sorted(left))
    comparisons = {name: serial.compare_native_data(left[name], right[name]) for name in sorted(left)}
    total = sum(c['variables'] for c in comparisons.values())
    saved_cmp = jload(RUN / 'comparison191.json')
    check('independent comparison direct vs dimr: all four datasets passed_exact_raw_variable_comparison (variables, dimensions, units, masks, unmasked values) and 191 variables',
          total == 191 and all(c['state'] == 'passed_exact_raw_variable_comparison' for c in comparisons.values()), {n: c['variables'] for n, c in comparisons.items()})
    check('recomputed comparison equals the saved comparison191.json (datasets, counts, hashes)', saved_cmp['variables'] == 191 and
          [(Path(d['left']).name, d['variables'], d['left_sha256'], d['right_sha256']) for d in saved_cmp['datasets']] ==
          [(n, c['variables'], c['left_sha256'], c['right_sha256']) for n, c in comparisons.items()])
    facts['dataset_variables'] = {n: c['variables'] for n, c in comparisons.items()}
    facts['natural_numerics'] = numeric

    # ---- (6) trial 229 stays NOT_ACCEPTED and refused --------------------------------------------------------------------------------------------
    listing229 = tree(RUN229)
    check('trial 229 run root unchanged (192 files, listing digest e0e3520a...)', len(listing229) == 192 and hashlib.sha256(json.dumps(listing229, sort_keys=True).encode()).hexdigest() == RUN229_LISTING)
    g229 = jload(GRANT_DIR229 / 'admitted-grant.json')
    exe229 = g229['executables']['direct']
    engine229 = next(r for r in g229['engine_files'] if Path(r['path']).resolve() == Path(exe229).resolve())
    control229 = jload(RUN229 / 'control-direct/manifest.json')
    expected229 = {'route': 'direct', 'argv': [exe229, '--autostartstop', 'f34.mdu'], 'working_directory': str(RUN229 / 'control-direct' / 'model'), 'run_directory': str(RUN229 / 'control-direct'),
                   'executable_sha256': engine229['sha256'], 'profile_name': 'short'}
    verdict229 = reader.audit_control_survival(jload(RUN229 / 'cancel-direct/manifest.json'), control229, jload(RUN229 / 'observations/cancel-direct-survival-final.json'), expected229)
    top229 = jload(RUN229 / 'verification.json')
    check('trial 229 preserved: report stopped_no_retry_NOT_ACCEPTED and its cancel verdict is still refused by the same frozen reader for the same tie reason',
          top229['state'] == 'stopped_no_retry_NOT_ACCEPTED' and verdict229['audit_state'] == 'refused' and
          [e['reason'] for e in verdict229['errors']] == ['control_after->control_pre_cleanup: monotonic stamp reused by a different snapshot'])

    # ---- immutability --------------------------------------------------------------------------------------------------------------------------
    after = {'run231': tree(RUN), 'grant231': tree(GRANT_DIR), 'run229': tree(RUN229), 'grant229': tree(GRANT_DIR229), 'dispatch': sha(DISPATCH), 'reader': tree(READER_DIR),
             'adapter_v6': tree(ADAPTER_V6), 'serial_reader': sha(SERIAL), 'observer': sha(OBSERVER)}
    check('every original byte unchanged during the readback (231 run + grant, 229 run + grant, dispatch, reader, adapter V6, numerical reader, observer)', after == watched,
          {'run231_files': len(after['run231']), 'grant231_files': len(after['grant231'])})
    failed = [c for c in checks if not c['passed']]
    result = {'schema': 'SHORT-CLOSE-NATIVE231-RELEASE-V-readback-1', 'node': 'NATIVE231-RELEASE-V', 'native_launches': 0,
              'reader_freeze_sha256': READER_FREEZE, 'adapter_freeze_sha256': ADAPTER_FREEZE, 'grant_sha256': GRANT_SHA, 'plan_sha256': PLAN_SHA,
              'dispatch_sha256_at_readback': watched['dispatch'], 'run_root': str(RUN), 'checks_total': len(checks), 'checks_failed': len(failed), 'checks': checks,
              'cases': audits, 'markers': markers, 'observer_close_receipts': observers, 'public_invocations': inv, 'control_survival': survival, 'facts': facts,
              'run231_file_count': len(after['run231'])}
    (out / 'verification.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'checks_total': len(checks), 'checks_failed': len(failed), 'failed': [c['check'] for c in failed]}))
    return 0 if not failed else 1


def per_gate(reader, b, target, control, expected_control):
    """Each audit_control_survival gate on its own, with the frozen reader's helpers unchanged."""
    gates = []

    def gate(name, fn):
        try:
            fn()
            gates.append({'gate': name, 'passed': True})
        except Exception as exc:  # noqa: BLE001
            gates.append({'gate': name, 'passed': False, 'reason': '%s: %s' % (type(exc).__name__, exc)})
    exe = control['argv'][0]
    tb_id, cb_id = reader.birth(target['ownership']['native_identity']), reader.birth(control['ownership']['native_identity'])
    to, co = b['target_before']['observer_id'], b['control_before']['observer_id']
    s = {}
    gate('control original lifetime/Job/collector audit', lambda: reader.need(reader.audit_record(control, expected_control)['audit_state'] == 'qualified_full_lifetime_close', 'control audit'))
    gate('distinct runs, births and private Jobs', lambda: reader.need(target['run_id'] != control['run_id'] and tb_id != cb_id and
                                                                          target['ownership']['job_close']['job_instance_token'] != control['ownership']['job_close']['job_instance_token'], 'not distinct'))
    gate('same selected executable and route', lambda: reader.need(reader.image(target['argv'][0]) == reader.image(exe) and target['route'] == control['route'] and
                                                                      target['executable_sha256'] == control['executable_sha256'], 'differs'))
    gate('target and control use distinct observer objects', lambda: reader.need(to != co, 'shared'))
    for key, ident, oid, live in (('target_before', tb_id, to, True), ('target_exit', tb_id, to, False), ('control_before', cb_id, co, True),
                                  ('control_after', cb_id, co, True), ('control_pre_cleanup', cb_id, co, True), ('control_final', cb_id, co, False)):
        gate('sample ' + key + (' live' if live else ' exited'), lambda key=key, ident=ident, oid=oid, live=live: s.__setitem__(key, reader.observer(b[key], ident, exe, oid, live=live)))
    if len(s) == 6:
        gate('control_before->control_after', lambda: reader.later(b['control_before'], s['control_before'], b['control_after'], s['control_after'], 'control_before->control_after'))
        gate('control_after->control_pre_cleanup', lambda: reader.later(b['control_after'], s['control_after'], b['control_pre_cleanup'], s['control_pre_cleanup'], 'control_after->control_pre_cleanup', identical_ok=True))
        gate('control_pre_cleanup->control_final', lambda: reader.later(b['control_pre_cleanup'], s['control_pre_cleanup'], b['control_final'], s['control_final'], 'control_pre_cleanup->control_final'))
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
