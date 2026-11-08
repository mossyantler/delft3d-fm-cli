# Contract: G15 structure export/import, finish and merge

Beads: `G15-I` (`dfm-h9c.3`), `G15-V-Run` (`dfm-h9c.4`), `G15-G` (`dfm-h9c.5`). `G15-ENGINE-Contract`
(`dfm-h9c.6`) stays a separate later plan. Status: proposal by the coordinator, 2026-11-08. Product verification
rules apply in full. No native engine or GUI run belongs to this Contract.

## Background

- G15 adds `structure inspect` (read-only), `structure export` and `structure import` (preview, then apply bound to
  the preview hash). The behaviour is the approved proposal rev02
  (`research/experiments/G15-PROPOSAL-I-20261105-rev02/contract.json`, `PROPOSAL.md`, `ADDENDUM.md`; G approval
  `G15-PROPOSAL-G-final-01/verification.json`): 23 obligations and 16 scope rows. Writes cover W2D (planar weir,
  scalar or TIM crest) and P2D (scalar pump); the other 14 rows stay visible as deferred or unsupported.
- The private candidate is **incomplete and not frozen**
  (`research/checkpoints/20261105-quota-pause/pending/G15-I/CHECKPOINT.md`). Package-02 (wheel `f3f1686f…`, 191-file
  base) passed its own 17 tests. After that, `structure_transfer_graph.py` gained explicit non-MDU container
  grammar admission (unknown EXT/INI keys defer visibly) and 6 private tests were added; none of this was compiled
  or run. Checkpoint copies (sha256, first 16 hex):

  | `src/dfm_cli/` file | sha256 |
  | --- | --- |
  | `structure_transfer.py` | `210fb75c977f9a85…` |
  | `structure_transfer_contract.py` | `e0247d840ee7f8eb…` |
  | `structure_transfer_text.py` | `d20465f9e0c8bc9a…` |
  | `structure_transfer_paths.py` | `b25cc02139fd3eb9…` |
  | `structure_transfer_graph.py` | `75513ebab2c1568a…` (package-02 had `ec63d83d…`) |
  | `structure_transfer_bundle.py` | `97202a8a4efe3775…` |
  | `structure_transfer_edit.py` | `dbfa548fa75360af…` |
  | `structure_transfer_write.py` | `93a2e6be4330850d…` |

  Full hashes are in `CHECKPOINT.md`. Private tests: `test_private.py` (`e3d318cf…`, 23 methods; class `Faults`
  inherits from `Public` and so re-runs every public test). cli glue: `prepare_package.py` (`db1b1a43…`).
- Independent V material (Lovelace, `G15-V-Plan` `dfm-h9c.2`): `research/experiments/G15-TRANSFER-V-20261105-01/ready-01/`
  (`freeze.json` `642653dd…`): 30 public methods (`test_public_transfer.py`), 11 publication-fault methods
  (`test_publication_faults.py`), an independent raw-bytes oracle, 43 hand-made adverse fixtures, expected bytes in
  `predeclared-02`, three hand-serialized bundles, and an ACL helper (`win_file_acl.py`).
- Every product module the candidate imports (`common`, `model`, `observation_inputs`, `observation_transfer_io`,
  `boundary_export_stage`, `boundary_support_write`, `pump_edit_contract`, `pump_edit_security`, `pump_edit_write`)
  is byte-identical on main to the candidate's base (static check, 2026-11-08). `runs.py` and
  `run_pump_lifecycle.py` are reachable only through an import chain; the candidate never calls them.

## R1. Product change

- Start from the eight checkpoint modules, including the current `structure_transfer_graph.py` (`75513eba…`): the
  post-package-02 grammar admission is part of the candidate.
- I may change the eight modules only to fix a defect that a test shows. Each fix is a separate commit with a test
  that fails before it, and is listed in the receipt with the obligation or scope row it serves. No behaviour
  beyond rev02, no change to any other product module.
- `cli.py`: three added lines only, at the anchors `prepare_package.py` uses: `from . import structure_transfer`
  after `from . import source_sink`; `COMMAND_MODULES["structure"] = structure_transfer` after
  `COMMAND_MODULES["source"] = source_sink`; `"structure_transfer": structure_transfer.contract(),` after
  `"source_sink": source_sink.contract(),`. Each new line uses the line ending of the line above it; no existing
  line changes a byte (do not run `prepare_package.py`, which rewrites every line ending).
- Result: 209 product files, 105 public commands, schema `structure_transfer` equal to the frozen `contract()`,
  every existing schema entry and command parameter unchanged.

## R2. Tests and README

- `tests/test_structure_transfer.py`, ported from `test_private.py`, with every one of its 23 methods and the same
  assertions. Allowed adjustments, each listed in the receipt:
  1. run under `unittest discover -s tests` from any directory: fixtures under `tempfile`, the CLI through
     `python -m dfm_cli` with the current interpreter or in-process `cli.main` instead of an installed `dfm.exe`;
  2. fix the `Faults(Public)` inheritance so each public test runs once and the two classes use separate folders;
  3. base facts (file or command counts, schema key set, paths).
  A change to an assertion about `structure` behaviour, bounds, errors or bytes is a defect.
- `README.md`: one paragraph on the three commands next to the section transfer paragraph, stating the W2D/P2D
  write scope and that the other rows are reported, not written. No new example folder.
- Full `unittest discover -s tests`: no new failures against main (1,806 tests, 33 geo skips).

## R3. Independent verification (V-Run, portable)

- Build the wheel from the frozen candidate, install it in a clean venv (`--no-index --no-deps`), and run Lovelace's
  `test_public_transfer.py` and `test_publication_faults.py` against that install, unchanged except:
  `--base-schema` comes from current main (102 commands), not `accepted-base-01` (98); the test's "new commands are
  exactly the three `structure` commands, every base parameter equal" rule then applies to main. Any other change to
  those scripts is listed with its reason and checked by G.
- The fault tests hook `CollectionStage.write/verify`, `_make_stage`, `_commit_new_directory` and
  `_verify_published`. If the frozen candidate renamed one, that is a finding to report, not something to adapt.
- **ACL writes:** `win_file_acl.set_protected` toggles DACL inheritance protection and restores the exact SDDL, only on
  paths inside V's own experiment folder. It runs only with the user's explicit approval recorded as a HUMAN node;
  without it, V reports those cases as not run.
- Regression on the candidate and on main with the same setup, listing every differing test.

## R4. Out of scope

- Native engine or GUI runs (G15-ENGINE-Contract);
- the 14 deferred or unsupported scope rows;
- coordinate conversion; POSIX behaviour; an examples folder.

## Done when

- **I:** R1 and R2; the eight modules listed with final sha256 and every change from the checkpoint justified;
  `compileall` clean; `python -m dfm_cli schema inspect` shows 105 commands and `structure_transfer`; the 23 ported
  tests pass; full regression as R2.
- **V-Run:** R3, PASS or REJECT with reproducing commands.
- **G:** wheel identity with 209 files; full regression; merge; a new verification note
  `research/notes/verification/structure-transfer.md`.
