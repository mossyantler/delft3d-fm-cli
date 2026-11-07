# Contract: B06-RUN-PROFILE, the source-sink public run profile on the current product

Beads: `B06-RUN-PROFILE-I` (`dfm-985.5`), `-V-Plan` (`dfm-985.6`), `-V-Run` (`dfm-985.7`, lease), `-G` (`dfm-985.8`).
Status: proposal by the coordinator, 2026-11-07. Product verification rules apply in full (COORDINATOR.md,
verification weight).

## Background

- **#225 accepted** the public source input commands (`source inspect/add/set/forcing-create`) with six native
  120-second cases, each matching 170 variables ([source-sink.md](../verification/source-sink.md#public-225)). That
  record says a dedicated public run profile is a separate follow-up.
- **A run-profile candidate exists but cannot be reused as approved.** It was built on the old `23f9`/`eedd` base,
  before SHORT-CLOSE (`df447d8`) changed `runs.py`. It lives at
  `research/experiments/B06-RUN-PROFILE-I-20261105-01/` (local, Git-ignored). Its behaviour spec is `API-CONTRACT.txt`
  (sha256 `dd46cfea25714eb00f65341a5c04effd43efd5cfea72f70e40033365ec921222`), its modules are in `overlay/src/dfm_cli/`,
  and its tests are in `tests/test_source_sink_run_profile.py` (sha256 `c8677863…665e`). The later composition with the
  short fix (`B06-RUN-PROFILE-CLOSE-I-20261105-01`) was built on `23f9` too.
- **The current product** is `src/dfm_cli/` at `df447d8`, with 191 files and unchanged since then. Pump and weir run
  profiles already use the guarded-serial hooks (`TRACE_MEMBERS_REQUIRED`, `JOB_CLOSE_RECEIPT_REQUIRED`,
  `PRE_LAUNCH_HOOK_REQUIRED`, `staging_hook`, `pre_launch_hook`, `verify_outputs`); see `weir_run_profile.py`.

## R1. Public surface

```text
dfm run start MDU --profile source-sink --route direct|dimr --install SUITE --out NEW_DIRECTORY --timeout 120
```

- `source-sink` joins `runs.AUTHORED_PROFILES`, so the parser choice derives from the registry. The command count
  stays 98, and `dfm schema inspect` gains one `source_sink_run_profile` contract entry: name, routes
  `["direct", "dimr"]`, 6 required inputs, 120 s maximum and the limitations list.
- `--route` is checked first. Any other route is refused with exit 4 before the reader, the install lookup or any
  folder is touched (as `weir_run_profile.require_route`).

## R2. Admission (closed)

Exactly the sections "Closed initial admission" and "Linear BC admission" of `API-CONTRACT.txt` (pinned above). In
short:

- **Inputs:** six active inputs: MDU, NetFile, new EXT, named XYN observations, a separate fixed cross-section PLI, and
  one BC shared by `discharge` and `salinityDelta`.
- **Source:** one new-EXT SourceSink, either one inline outfall at (500095, 5700015), or an ordered intake
  (500025, 5700015) to that outfall. Zero area and no vertical ranges.
- **Grid and settings:** the measured 48-cell 12x4 120x40 m EPSG:32631 grid, flat bed -3 m, and the fixed numeric
  settings of the retained fixture.
- **Clock:** a cold UTC start at RefDate and a stop at 120 s. DtUser/DtMax/DtInit are 1 s, HIS/MAP are 1 s, and the
  `RstInterval` token sequence `120 0 120` is kept as written.
- **BC:** linear, with 2..121 integer-second knots over 0..120. Q is 0..0.1 m3/s and salinityDelta 0..15 ppt, with the
  listed unit tokens. Column order is kept, never reordered.
- **Other blocks:** known unbound forcing blocks are inventoried as not consumed. Unknown functions, properties or
  bindings and unqualified units fail closed. An unreferenced old BC stays untouched and is left out of the stage.

Errors use `source_sink_*` codes. Pump and weir error codes and messages stay byte-identical.

## R3. Staging and pre-launch identity

The section "Source byte/identity and directory bindings" of `API-CONTRACT.txt` applies:

- **Requalify after staging and again immediately before launch:**
  - the source bytes and identities, and the staged files;
  - the original and staged FM program identity;
  - the clock, the full source state, the mesh and the output schedule;
  - the selected executable and its required DLL hashes.
- **Refuse:**
  - a same-size change with the mtime restored;
  - a replacement file with the same bytes;
  - any extra staged file.
- **DIMR** also binds the generated XML bytes and identity: one DFlowFM component, process 0, workingDir `model`, and
  the exact staged inputFile. User-supplied multi-component XML is not admitted.
- **Direct and DIMR** keep distinct argv and cwd forms.

The profile uses the same hook interface as the weir profile: all three flags are true, and it defines
`staging_hook`, `pre_launch_hook` and `verify_outputs`.

## R4. Closure and terminal states

- `source-sink` joins the guarded-serial family exactly as pump and weir do in the current `runs.py`. That makes it
  part of the SHORT-CLOSE terminal path (original `Job.close()` return kept, member and collector closure assessed,
  lifecycle saved before terminal publication).
- `completed` needs complete natural member HANDLE/accounting proof plus the source notification/event bijection
  (`run_pump_lifecycle.notifications_complete`, one algorithm and no second copy).
- Missing exit or close proof can never become `completed`. There is no automatic next run after a cleanup loss.
- No change to the bodies of `Run.save`, `terminate`, `execute_native`, `verify_completion`, `fail` or `start` beyond
  the family membership.

## R5. Output verification

`verify_outputs` requires 121 history and map times 0..120 and exactly the singleton initial (0) and final (120)
restart times via `checkpoint_schedule`. It does not compare the 170 scientific variables; that is V-Run's native gate.

## R6. Files and scope

- **New:** `src/dfm_cli/source_sink_run_inputs.py`, `src/dfm_cli/source_sink_run_profile.py`. The product becomes
  193 files.
- **Changed, minimal hunks only:** `src/dfm_cli/runs.py` (import, registry, family membership, and the
  source-only route/pre-read gate that `API-CONTRACT.txt` lists for `runs.py`: `pre_read_hook(path)` before the MDU parser), `src/dfm_cli/cli.py`
  (one schema entry), `src/dfm_cli/run_pump_lifecycle.py` only if the source label needs it.
- **Tests:** `tests/test_source_sink_run_profile.py` and fixtures under `tests/`. Every process or Job boundary in
  a test is synthetic.
- The old overlay modules and tests may be used as starting material. They must be rebased onto the current
  `runs.py` and hooks, not copied over shared files.
- **Out of scope:**
  - native runs (V-Run, with a lease);
  - GUI export;
  - PLI source locations;
  - acceptance of time-varying BCs or reordered columns;
  - 3D, restart input, coupling and other geometries.

## R7. Native acceptance (V-Run, needs a lease and user approval)

There are four runs: `point_set15` and `pair_set15`, each through `direct` and `dimr`. Inputs are in
`research/experiments/B06-PUBLIC-G-inputs-01/`, and the references are the retained #225 outputs in
`research/experiments/B06-PUBLIC-RUNNER-I-native-225-01/`. V-Plan fixes the comparison before any run:
- arrays, units, masks, attributes and time for the 170 variables;
- restart times;
- original Job and CloseHandle proof.

The coordinator asks the user before the lease.

## R8. Clarifications (coordinator, after V-Plan; binding for I and V)

1. **A1, varying knots and column order.** The profile admits what R2 and the pinned "Linear BC admission" admit:
   2..121 knots with time variation, and either order of the two physical columns, bytes kept and never reordered.
   This holds for inspection and for the `run start` preflight alike; the profile does not refuse such a run.
   "Acceptance" in R6 means native and scientific acceptance only: no R7 run covers these inputs, so no claim is
   made about their results.
2. **A2, route refusal.** The exit 4 in R1 is the profile's route gate (`require_route`, reached through
   `runs.prepare`). The public parser keeps its existing `--route` choices `direct` and `dimr`, so an unknown public
   route is a parser error with exit 2, as today. Both parser choices are supported by `source-sink`, so no public
   route reaches the exit-4 gate; it is tested at the `runs.prepare` level.

## Done when

- **I:**
  - `python -m unittest discover -s tests` shows no new failures against the baseline of 1,715 tests (1,679 pass,
    36 skips), plus the new tests;
  - `python -m compileall -q src tests` is clean;
  - `dfm schema inspect` lists the profile;
  - all six retained #225 inputs are admitted statically for both routes (12 checks), with the originals unchanged.
- **V-Plan:** derives cases from this Contract alone and builds a portable verifier (no native launch). It also fixes
  the R7 native comparison and wires its comparator on the retained #225 outputs.
- **V-Run (portable part):** PASS on the frozen candidate. The native part waits for R7.
- **G:**
  - builds a wheel and checks that it matches the 193-file product;
  - runs the full regression;
  - after the native V-Run, merges and records the result in `source-sink.md`.
