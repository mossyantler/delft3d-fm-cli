# Contract: G18 section export/import on the current product

Beads: `G18-NATIVE-I` (`dfm-vbl.3`), `G18-REBIND-V-Plan` (new), `G18-NATIVE-V-Run` (`dfm-vbl.4`, lease),
`G18-G` (`dfm-vbl.5`). Status: proposal by the coordinator, 2026-11-08. Product verification rules apply in full.

## Background

- G18 adds `section export` and `section import`: whole-record copy of observation cross-section PLI records
  between a model and an external PLI, preview then apply bound to the preview hash. The file behaviour was approved
  as G18-FILE-G (`dfm-vbl.1`, [section-transfer.md](../verification/section-transfer.md)) on a held 196-file wheel
  (`63e4b869…`, base 191 files / 98 commands). It was never merged. It is not approved product code.
- Frozen source (local, Git-ignored), pinned by `hold.json` (`876e21a2…`) and
  `research/experiments/G18-TRANSFER-I-20261105-rev02/freeze.json`, copies in
  `research/checkpoints/20261105-quota-pause/pending/G18-I/`:

  | File | sha256 |
  | --- | --- |
  | `src/dfm_cli/section_transfer.py` | `fd0d78ba0121a1633423bded978cef2351d468b13cf595ee11970f4060f06d2d` |
  | `src/dfm_cli/section_transfer_contract.py` | `75ba299e6b7a4f25622b5790cbc8425adf0c743199d6a2da1e3932fb6f485460` |
  | `src/dfm_cli/section_transfer_graph.py` | `514d1af0713add23a4a4cfad9bcfda9a6c3cc812a053ff8d49cefb9b32fab023` |
  | `src/dfm_cli/section_transfer_text.py` | `cb8ded0729be6a8c032f5f3f77fc0ceb5106d4acd77fe11bed1722dd02e7eabc` |
  | `src/dfm_cli/section_transfer_write.py` | `d8af6e7b53f596385545353ee2b398de15e342ca6370c76e0791ebf3698dfb9d` |
  | `integration.patch` | `d1bae9043df6f034d6306cb631311a7560160680fb7ddf455932612cd53129af` |
  | `test_section_transfer.py` (25 tests) | `0c8b08d3b51dc5a6451dfd28f01595e680a081301e4b4b08c56a9e863bf6cd41` |

- Docs candidate: `research/experiments/G18-DOCS-I-20261105-01/` — `documentation.patch` (`a82cd467…`),
  `proposed/examples/section_transfer/` (README `a3244f34…`, `make_example.py` `17eec18a…`),
  `proposed/tests/test_section_transfer_usage.py` (7 tests, `6b09741c…`).
- Native plan (Mill, G18-NATIVE-V-Plan `dfm-vbl.2`, re-checked by G in `G18-NATIVE-PLAN-G-final-01`):
  `research/experiments/G18-NATIVE-PLAN-V-20261105-01/` — `plan.json` `bbcd59cb…`, `predeclared.json` `b89105f9…`,
  `freeze.json` `fc3f3ba7…`, `science.py` `6150efd9…`. This is the only oracle. The producer plan in
  `G18-TRANSFER-I-native-plan-20261105-01` (`3a1b9aa5…`) predicts other edits and is not used.

## R1. Product change

- Add the five modules **byte-identical** to the table. Every module they import exists unchanged on main
  (`common`, `model`, `observation_inputs`, `observation_transfer_io`, `section_orientation_graph`,
  `boundary_support_write`, `pump_edit_contract`, `pump_edit_security`, `pump_edit_write`); if one does not, stop
  and ask.
- `section_orientation.py`: the `integration.patch` hunk only (5 added lines: register, and dispatch of
  `export`/`import`). The result must equal the candidate's `section_orientation.py` byte for byte.
- `cli.py`: two added lines only, applied by hand because S07 changed the import-line context:
  `from . import section_transfer` as its own line directly after the `boundary_preview, boundary_vertical,
  weir_series, wind_drag` import line, and `"section_transfer": section_transfer.contract(),` directly after the
  `"section_orientation"` schema line. No existing line changes a byte (the `"section_orientation"` line keeps its
  current line ending). Each new line uses the line ending of the line above it. `COMMAND_MODULES` is unchanged.
- No other product file changes. Result: 201 product files, 102 public commands, schema `section_transfer` equal
  to the frozen `contract()`, every existing schema entry and command parameter unchanged.

## R2. Tests, example, README

- `tests/test_section_transfer.py` from the frozen 25-test file and `tests/test_section_transfer_usage.py` from the
  proposed 7-test file. Allowed adjustments (each listed in the I receipt with its reason; V-Run checks the diff
  against the list):
  1. base facts that changed since the old base (product file count, command count, schema key set, paths);
  2. fixture location: write fixtures under a `tempfile` directory instead of the current directory or
     `G18_DOCS_TEST_WORKSPACE`, so both run under `unittest discover -s tests` from any directory;
  3. imports needed to run under discover.
  Any change to an assertion about `section export`/`section import` behaviour, bounds, errors or bytes is a defect.
- `examples/section_transfer/` from the proposed example. Its commands must run as written in Windows PowerShell 5.1
  against the rebuilt CLI (run once that way); only quoting may change if they do not.
- `README.md`: the `documentation.patch` README hunk only. The `AGENTS.md` and `gui-workflows.md` hunks are dropped
  (G updates the verification note and the GUI notes after merge).
- Full `unittest discover -s tests`: no new failures against the current base (1,774 tests, 33 geo skips on main).

## R3. Public-edit replay

`public_append` and `public_replace` (and the `all_roundtrip` export/import) were made with the held wheel through
8 public calls (`G18-NATIVE-PLAN-V-20261105-01/public-preparation/calls.json`, `ab77980c…`). Replay the same calls
with the rebuilt CLI on fresh copies of their base inputs: a fresh preview, then apply with that preview's
`input_sha256`. The resulting model files must be byte-identical to the retained prepared inputs
(`inputs/<case>/`). A preview hash that differs only because of paths is not a defect; differing result bytes are.

## R4. Native acceptance (V-Run; needs a lease and user approval)

Six sequential runs in Mill's `case_order` — `baseline`, `all_roundtrip`, `manual_append`, `public_append`,
`manual_replace`, `public_replace` — each
`dfm run start <fresh copy>\f34.mdu --profile short --route direct --install <suite> --timeout <T> --out <fresh>`,
with `public` and `all_roundtrip` inputs from the R3 replay. Acceptance is Mill's plan unchanged:

- **Clock:** 0 to 600 s; history and map at 11 times (every 60 s); restart files at 0 and 600 s.
- **Exact pairs:** `baseline`/`all_roundtrip`, `manual_append`/`public_append`, `manual_replace`/`public_replace`:
  all compared variables equal, except the named provenance globals.
- **Replace:** Entrance's 8 vertices reversed; discharge, cumulative discharge and velocity flip sign within
  8·eps32·max(1,|a|,|b|); area equal; baseline Entrance discharge above 0.001 m³/s somewhere in 60–600 s.
- **Append:** `G18_new_cut-A.1 (subset)`, 4 vertices; the original three section signals unchanged.
- **Terminal state:** `completed` through the current SHORT-CLOSE lifecycle; the close receipt is the manifest's
  (`ownership.job_close`, `ownership.short_lifecycle`).
- **Stop rule:** stop at the first failure. No retries.

The V-Plan rebind (below) fixes `T`, the admission-receipt fields and the restart-file question before any launch.

## R5. Out of scope

- GUI parity; coordinate conversion; POSIX behaviour;
- other section formats or partial-record edits;
- scientific calibration; the installed engine's source commit.

## R6. Clarifications (coordinator, after V-Plan; binding for I and V)

1. **Fresh-path bindings (V-Plan A1).** Mill's `plan.json` stores historical absolute MDU paths and the frozen
   `science.py` compares the run's MDU to them literally. For R4, V-Run uses the rebind adapter
   (`reader_rebind.py`) with a bindings JSON that maps each case to its fresh copy. The bindings file is written and
   hashed before the first launch, it changes only the source path, and the copy's bytes must equal the plan's
   recorded hashes. `plan.json`, `predeclared.json`, every digest, prediction and tolerance stay unchanged.
2. **Area under reversal (V-Plan A2).** R4's "area equal" paraphrases Mill's predeclared statement ("area
   unchanged", with the frozen 8·eps32·max(1,|a|,|b|) roundoff bound and no other threshold). Mill's frozen reader
   governs: area is checked against that same bound. Exact manual/public pairs keep zero tolerance.
3. **Admission and timeout.** The admission receipt is the mapping in the V-Plan's `NATIVE-PLAN.md` (engine,
   201-file wheel built from the frozen candidate, `common_freeze` = the SHORT-CLOSE root verification record,
   `dfm.exe` of a clean install of that wheel, candidate commit), frozen with its sha256 before the first launch.
   `T` = 60 s per run, no extension or retry.
4. **Runner environment (coordinator review before the native packet).** `dfm run start` needs the `run` extra
   (`netCDF4==1.7.5.1.post1`, `runs.py:136`), which the clean `--no-deps` install does not have. The six runs use
   `C:\Users\minyeop\project\delft3d-fm-cli\.venv\Scripts\python.exe -m dfm_cli` (netCDF4 1.7.5.1.post1) with
   `PYTHONPATH` set to the clean venv's `Lib\site-packages`, so `dfm_cli` is the installed 201-file payload of wheel
   `f4edd82d…`; V confirms `dfm_cli.__file__` before the first launch. The admission's `dfm` entry records that
   python and the payload folder, and V re-freezes the admission with its new sha256 before the first launch.
   Nothing else in the admission, bindings, plan or reader changes.

## Done when

- **I:**
  - R1 and R2, with sha256 identity of the five modules and of `section_orientation.py` against the candidate;
  - `compileall` clean;
  - `python -m dfm_cli schema inspect` shows 102 commands and `section_transfer`;
  - R3 replay identical;
  - the example run once in Windows PowerShell 5.1.
- **G18-REBIND-V-Plan:** re-binds Mill's plan to the current product without changing any prediction or tolerance:
  1. a portable `verify_g18.py` for R1–R3 (module identity, the two cli.py lines and the section_orientation hunk,
     201/102, every other schema entry and command parameter equal to main, the R2 test-diff rule, the R3 replay);
  2. the admission receipt Mill's reader expects (`plan_sha256`, `common_short_gate_accepted`, `engine`, `wheel`,
     `common_freeze`, `dfm`), mapped to the current setup: the 201-file wheel built from the frozen candidate, the
     SHORT-CLOSE-ROOT-G acceptance for the common gate, and the candidate commit;
  3. whether `--profile short` on `f34.mdu` writes restart files at 0 and 600 s (from the profile code and the
     earlier f34 runs, `MDU-ID-G-f34-156-01`), and the timeout `T` with its basis;
  4. the reader run against a current SHORT-CLOSE manifest (synthetic pass and one altered copy that fails).
  No native launch.
- **V-Run:** portable checks on the frozen candidate, then R4 after user approval.
- **G:**
  - wheel identity with 201 files;
  - full regression;
  - merge, and a record in the section-transfer verification note.
