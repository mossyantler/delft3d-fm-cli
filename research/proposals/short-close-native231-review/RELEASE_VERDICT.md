# NATIVE231-RELEASE-V release verdict

Reviewer: **Claude Sonnet 5.5 (`claude-sonnet-5-5`), high effort**; AGENTS.md read first.
File-only postmortem of `research/experiments/SHORT-CLOSE-G-native-rev04-231-20261105-01` (388 files) and grant folder
`SHORT-CLOSE-NATIVE-G-20261105-02` (5 files) with the exact frozen reader `980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62`
and the pinned original numerical reader `verify_serial_exit.py` (numpy/netCDF4 file reads only). No process/PID/Job/HANDLE/FFI/native/GUI
query or launch, no Git, no edit to any record, output, source, dispatch or shared doc. All 388 + 5 files, the 229 run and grant, the dispatch
(`3ce2f989…`, lease 231 still active when read), reader, adapter V6 (`53a1db83…`), numerical reader and observer source re-hashed **byte-identical**.

Review freeze `freeze.json` sha256 **`21abd9ef0b7ca9b97bf188ef806b69b9cfb37168635ad4145c3e240d933688ff`**
(`readback.py` `40fe89b1…` 34760 B; `VERIFICATION.json` `7047aafc…` 13276 B). Run-root listing digest `e1a2bfa4…`. Final run `readback-01`: **37/37 checks pass**.

## Verdict

1. **RELEASE-SAFE BY RAW RECEIPTS: lease 231 can be released.** Every owner this lease started is terminal and its original Job, members and collector are closed;
   every observer handle and every public client has an actual receipt.
2. **BOUNDED FIXTURE ACCEPTED** for the scope below. This is an acceptance of the f34 short-profile trial, not of anything general.
3. Trial **229 stays NOT_ACCEPTED** (preserved: run root unchanged, report `stopped_no_retry_NOT_ACCEPTED`, its cancel verdict is still refused by the same frozen reader for the same coarse-tick tie).

## What the raw receipts establish

- **Twelve original closures** (natural, bad-mesh, empty-bc, control, timeout, cancel × direct, DIMR): `qualified_full_lifetime_close`; two retained members each with
  same-HANDLE exit confirmed; final original-Job accounting `Total=2 Active=0`; Job empty; real Job `CloseHandle` (nonzero int); collector closed; my frozen-reader reruns
  equal the adapter-saved audits and state assertions exactly. States completed / failed / failed / cancelled / timed_out / cancelled per route; none `cleanup_failed`; no natural race.
- **Twelve observer `CloseHandle` receipts** joined to twelve distinct live captures by object, birth and image; exited final sample before each close; accepted by the frozen reader.
- **Sixteen public invocations** (12 starts + 4 cancel requests) all returned: naturals 0; bad-mesh/empty-bc 5 `native_failure`; timeouts 5 `run_timeout`; cancel/control starts 5 `run_cancelled`; cancel requests 0; protocol 2; every `go` delivered once; stderr empty.
- **Initialization markers**: the eight natural/control/timeout/cancel runs reached `Done writing initial output` on both routes; bad-mesh shows `Failed to open: f34_net.nc` and empty-bc `No signals for polyline` on both routes, with no initial output.
- **Four survival verdicts recomputed from the saved complete 10-key raw bundles** (not from derived flags): timeout and cancel, direct and DIMR, all `independent_control_survival_confirmed`, 20/20 gates each,
  every adjacent transition strictly increasing, control live at both post-target samples and exited at the end; each saved digest matches its bundle.
- **Numerics, reread from the actual NetCDF**: both natural routes have CF history/map clocks 0→600 s (`seconds since 1990-08-05`), final restart at 600 s, elevation unit `m`, equal to the saved receipts.
  The four corresponding datasets (his 68, map 55, restart 34 + 34) are exactly equal between direct FM and DIMR: **191 variables** equal in values, masks, units and dimensions; equal to `comparison191.json`.
- **Grant `8789014b…`** binds adapter V6, plan `d5427cb0…`, reader, run root and bounds (12 launches, 2 concurrent, no retry); every pinned file (package, contract, reader, review, five engine files, observer, numerical reader) still hashes; peak concurrency 2 from the raw timelines.

## Bounded fixture acceptance (scope)

Accepted: the f34 2D UTC cold-start fixture, short profile, 600 s model time; direct FM and single-component DIMR; lifetime/Job/collector closure; isolation of an independent control across a
forced timeout and a forced cancel on both routes; failure initialization (bad mesh, empty BC); and exact route-to-route raw equality (191 variables).

## Not established (do not infer)

- Native closure is **not** clean forced finalization: forced roots exit nonzero and the stop cause is only `live_then_signalled_cause_not_proven`; no usable restart or physical meaning follows from a forced stop.
- Physics is not assessed: the numerics show a valid CF clock/final restart and exact equality between two routes, not agreement with observations or calibration.
- Other models, CRS, MPI, restart-resume, coupling and GUI parity; the 229 trial.
- Liveness after the recorded times: by instruction no live query was made; receipts bound the state at record time.

Evidence: `research/experiments/SHORT-CLOSE-NATIVE231-RELEASE-V-20261105-01/{readback-01,freeze-01,run-root-before.sha256,grant-folder-before.sha256}` (git-ignored); portable receipt with all key hashes (12 manifests, 12 observer receipts, 16 invocations, 4 bundles and verdicts, 8 NetCDF files, comparison191): `VERIFICATION.json`.
