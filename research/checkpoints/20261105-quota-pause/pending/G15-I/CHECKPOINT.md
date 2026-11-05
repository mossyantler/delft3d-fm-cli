# G15 private I1 checkpoint — explicitly paused by user

Workspace: `C:/Users/minyeop/project/delft3d-fm-cli`.
Owned folder: `research/experiments/G15-TRANSFER-I-20261105-01` only.
Status: **incomplete; not frozen for acceptance; no native/GUI launches**.
All file/test operations have ended. No live sessions, native processes, Job
objects or retained process handles from this worker. Build session 61871 was
polled closed with exit0; test session52353 completed exit0. No root/common,
dispatch, documentation or Git changes. Coordinator owns backup/push.

## Inputs and implemented scope

Approved proposal rev02 freeze4265b4fabad0679208a3cae5ebfe841e4b4f773297f72cc9380c8a26103de898;
Vfinal60c317d678dc0f5ad18e60d9bfa2d7bccad80e2003419116770698ed2548b313;
G approval `G15-PROPOSAL-G-final-01/verification.json`.
Accepted base wheel eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d;
exact191 payload retained in `accepted-base/dfm_cli`, hashes in
`base-provenance.json`. Never compose latest unapproved common files.

Eight private modules implement inspect, both exports and both one-target
imports, full input/security consent, strict indices/maps, raw core framing,
existing byte-identical hydraulic child mapping, actual unchanged pump publisher,
and new-directory OwnedStage adapter. Stable policy identifiers; no runtime
implementation-source hashing. All16 coverage rows remain visible/deferred.

Public API in `structure_transfer.py`: inspect; export_structures;
import_structures; register; execute; contract. Closed geometry/bundle/map
serialization agreed with Lovelace. Writer fault points:
`CollectionStage.write/verify`, `_make_stage`, `_commit_new_directory`,
`_verify_published`; file publication delegates actual pump_edit_write.replace.

## Current source hashes (SHA256)

Relative to `src/dfm_cli/`:

| File | SHA256 |
|---|---|
| structure_transfer.py | 210fb75c977f9a8598b821fe8c56eb491713cbe43900d2dfcf5408d531fe1dc8 |
| structure_transfer_contract.py | e0247d840ee7f8ebd7f83b762adeb4a0561e78888eedb3e6a846c7e9240b1834 |
| structure_transfer_text.py | d20465f9e0c8bc9a43e4a33483844444ef54ab67274bc33b6a7725e7cb1446b0 |
| structure_transfer_paths.py | b25cc02139fd3eb9c81acecdbfc1ef1c636981f663389560622fcc690bf3903c |
| structure_transfer_graph.py | 75513ebab2c1568a81bed36946dfe42cbb9abc9f0b44906a3fe7f8e5a76f0f92 |
| structure_transfer_bundle.py | 97202a8a4efe3775cc19ecc722d88d0f9f622fa5fd275b041538b05e7f47d614 |
| structure_transfer_edit.py | dbfa548fa75360afc83f5a2c12153eca12557fc250e080b8584a6945fa6b6824 |
| structure_transfer_write.py | 93a2e6be4330850d9f2b6e1e4b73db1bf76e86f993961f9137bba7066fdbfc9b |

`prepare_package.py`: db1b1a43d8f5c804a78b1795d4884f5aadc69c2843cba255dc240f5093398a1d.
`test_private.py`: e3d318cfff894953374396153ea8dbb138cd23b1571dae1e58c30b01d8fb5c9b.

## Packages and executed checks

`package-01`: initial wheel78ee248c9fe175c4c5eda1ce06cb18d736efbc7bc41fc8d51c1d2a32fa92aa33.
Installed smoke refused ancestor security because read-only metadata binding
reused target ACL admission. Fixed privately: read-only Windows descriptor
fingerprint; unchanged publisher target ACL admission remains strict.

`package-02`: wheelf3f1686f570cd2584c77c6ec60d33bd9055c0d8ae5347dc4be88bc9ff8974a8c.
Clean no-deps venv installed; composition199 payload,190 unchanged base,
CLI-only changes (three registered structure commands/schema metadata).
`composition.json` pins payload. Installed actual examples/pump inspect passed
full six-file inventory; source unchanged. No solver or NetCDF decoding.

Own portable run `own-test-02`:17methods,11failures from incorrect test INI
comment marker `*`; raw fixtures/argv/stdout/stderr retained in commands.json.
Corrected private fixtures to valid `#` comments; did not loosen product parser.
`own-test-03`: **17/17 passed**,15.802s, package-02 installed registry.
Coverage: exact raw exports/source order, geometry label not identity, changed
one file, full no-op bytes/inode/mtime, stale source/unselected same-byte new
identity, units/inventory, unknown numeric consumers/type, root whitespace,
strict index/tree, sentinel XY, hydraulic replacement/no-op, no-overwrite,
missing-consent JSON errors. Public argv/stdout/stderr retained.

## Last completed atomic edit — NOT TESTED/PACKAGED

After17passed, graph._walk gained explicit non-MDU container grammar admission
(new EXT General/Boundary/Meteo vocabulary; unknown logical/numeric keys and
other INI grammars visibly defer rather than rely only on filenames).
Private tests added append/asset mismatch/unknown-container cases and three
actual installed writer/source-read guards. These last changes were applied
completely, but no compile/test/package ran afterward due user stop.
Current source therefore differs from package-02 graph module.

Known test-harness issue spotted before stop, **not edited**: Faults subclasses
Public, inherits every public test and uses the same own-test label/root.
Before resuming tests, factor common helpers into Harness(unittest.TestCase),
Public(Harness), Faults(Harness), and use class-qualified fresh output roots.
This is unfinished test plumbing, not an executed publication result.

## Resume after explicit user resume only

First read checkpoint and verify hashes, without running a solver:

```powershell
Set-Location C:/Users/minyeop/project/delft3d-fm-cli
Get-Content research/experiments/G15-TRANSFER-I-20261105-01/CHECKPOINT.md
Get-FileHash research/experiments/G15-TRANSFER-I-20261105-01/src/dfm_cli/structure_transfer*.py -Algorithm SHA256
```

Then fix own harness issue above, review untested graph vocabulary against full
approved contract, compile, prepare **fresh** package-03 using
`.venv/Scripts/python.exe -B research/experiments/G15-TRANSFER-I-20261105-01/prepare_package.py package-03`;
build/install new clean wheel, run targeted own tests under a fresh label with
installed venv Python. Retain package01/02 and all failed receipts unchanged.
Need own append/no-EOL/path mapping/clock/actual publication fault checks,
schema old98 exact+3, full11-file real weir inspect, no implementation-source
reads and optional no-NetCDF dependency guard. Inspect multi/legacy visibility
should be reviewed against approved all16 scope without widening I1 writes.

After meaningful checks: freeze exactsource/payload/tests/CLI semantic patch/
wheel/RECORD/schema/entrypoints; share pins with Lovelace for independent ready01
tests, resolve actual findings in new revision if frozen, then handoff to G.
No candidate acceptance/freezing/independent V run yet.

Lovelace thread01a1a56e-570f-7451-86c6-50a8f2be0221;
ready01 freeze642653dd9a8cf1ad8d70b8633acaeda2cfc9d70f577c81aad825989f635ba66f
(30public+11publication methods,23obligations/43fixtures/all16scope rows).
They received API/writer details and await exact candidate freeze. Do not edit V
fixtures or use their expected values to manufacture candidate output.

This checkpoint is a pause/backup record, not completion or launch approval.
