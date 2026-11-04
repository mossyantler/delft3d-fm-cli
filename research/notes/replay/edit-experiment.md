# E003/E005: independent scalar and boundary edits

**Date:** 2026-11-04, Asia/Seoul. **Result:** passed, including a fresh sequential
replay. Both experiments used the normalized f34 project from E001/E002.

The scalar edit changes one MDU value. The boundary edit changes one numeric BC
cell. Re-export also updates the MDU generation timestamp and can change spacing
in the target BC block. All other model values and input data checked below were
preserved. The original baseline and all accepted project copies remained
unchanged: edits were made in memory and exported, not saved back to the project.

See the [machine-readable summary](../../catalog/edit-experiment-summary.json) for
the exact deltas, per-run file changes, and retained negative probes.

## Fixture and controls

Baseline: `E001-E002-replay-20261103/gui-project/gui-baseline.dsproj` and its full
companion directory. It derives from the official f34 example in
`Deltares/Delft3D`, commit `5a4649830b1e5072caf019fb4850bbdefd9ad431`.

Three separate copies were opened in separate console processes:

| Case | Operation |
| --- | --- |
| Control | Open and export without editing |
| E003 scalar | Change the history output interval only |
| E005 boundary | Change one harmonic amplitude at one support point only |

Each accepted case exported twice. A second experiment replayed all three cases
sequentially using the tracked scripts. Comparison was against an unchanged
control exported through the same installed application, avoiding the old-MDU
migration differences already established in E001/E002.

The console executable SHA-256 remained
`7d16e799fcb19aeff11f0a9738eb6a067e17af3fa9c82d53511feea33cfeb4d0`.
The installed FlowFM plugin remains the 4.19.0.9954 component; the FM executable
reports 1.2.184.Unknown. No source-revision equivalence is inferred.

## E003: history interval 300 -> 600 seconds

Confirmed exported change at `f34.mdu`, line 162 in this fixture:

```ini
[output]
HisInterval = 300
```

becomes:

```ini
[output]
HisInterval = 600
```

Only `output/hisinterval` changes in the parsed MDU section/key/value comparison.
No keys are added or removed, and no other numeric values are reformatted. All
nine other input files are byte-identical to the control. The raw MDU diff also
contains a changed `# Generated on ...` timestamp.

The interval is **seconds**, even though the model's `TUnit` is `M`. Model dates,
`DtUser = 30`, numerical settings, other output intervals, file references, and all
boundary data remain unchanged. The selected 600-second value is a controlled
test value, not a model calibration recommendation.

### Application property ownership matters

The first attempt used:

```python
model.ModelDefinition.GetModelProperty('HisInterval').SetValueFromString('600')
```

Read-back before export reported `600`, and export returned success, but the
written MDU still contained `300`. This is retained as a **failed edit**, despite
the process and script reporting success at that stage.

Runtime inspection found two separate properties:

| Property | Runtime value type | Role observed |
| --- | --- | --- |
| `HisInterval` | `List[Double]` | Raw interval representation; direct mutation did not survive export in this probe |
| `HisOutputDeltaT` | `System.TimeSpan` | Interval owner whose mutation produced the intended exported value |

The verified application edit is:

```python
from System import TimeSpan
model.ModelDefinition.GetModelProperty('HisOutputDeltaT').Value = TimeSpan.FromSeconds(600)
```

In the accepted run, the raw interval still read `300` before export while the
owning property read `600`; the exported file then contained `600`. The working
script now checks the exported interval before declaring completion. This is a
version-specific mapping for this installation, not a universal rule for every
MDU key.

## E005: one harmonic amplitude 1.5 -> 1.75 m

The boundary is `L1`, linked by the unchanged new-style EXT file to
`f34_001.pli` and `f34_001.bc`. The PLI contains thirteen points. The BC has sparse
forcing blocks for points 1, 7 and 13, named `L1_0001`, `L1_0007`, and `L1_0013`.

Only the following numeric address changes:

| Address | Before | After |
| --- | --- | --- |
| `[Forcing] Name=L1_0001`, period 750 minutes, `waterlevelbnd amplitude` column, unit m | 1.5 | 1.75 |

The exported row is line 15 in this fixture. Its numeric row change is:

```text
750  1.5   0
750  1.75  0
```

The actual unified diff also shows column alignment changing spaces in the
unchanged zero row:

```diff
-0    0    0
-750  1.5  0
+0    0     0
+750  1.75  0
```

This is one changed numeric cell plus collateral formatting in the target block,
not two changed boundary values.

### Internal API and exported file use different coordinates

| Concept | Model API | Exported BC/PLI |
| --- | --- | --- |
| Selected point | Zero-based index `0` | One-based suffix `L1_0001` |
| Populated points | `DataPointIndices = [0, 6, 12]` | Names `L1_0001`, `L1_0007`, `L1_0013` |
| Harmonic argument | `Frequency`, unit `deg/h`, value `28.8` | Component period `750`, unit `minutes` |
| Edited component | `Amplitude`, unit `m` | `waterlevelbnd amplitude`, unit `m` |

For this nonzero component, `360 / 28.8 * 60 = 750` minutes. The API's zero
frequency/BC zero-component row is retained without attempting that division.
The condition's API data type is `Harmonics`; its serialized function is `harmonic`.

The script addresses the condition by feature and type, verifies the populated
point indices and units, selects the nonzero frequency row, and changes the
amplitude component only. It asserts the complete before/after boundary data
structure differs at exactly that value.

### Preservation verified for the boundary edit

- General BC metadata, forcing-block order and names, repeated ordered
  `Quantity`/`Unit` pairs, function, periods and units are unchanged.
- Every numeric BC cell except the selected amplitude is unchanged, including
  the zero row, the selected point's phase, and both other support-point signals.
- The `L1_0007` and `L1_0013` blocks are byte-identical, including their phases
  `-17.13` and `-34.26` degrees. The General block is also byte-identical.
- EXT, PLI, network, wind, observations, cross sections, thin dams and dry points
  are byte-identical. The MDU's parsed values are unchanged.
- In the primary run the MDU bytes also matched the control because the exports
  occurred within the same timestamp second. In the sequential replay the MDU
  differs only in its generation timestamp. Thus raw changed-file lists differ
  without a difference in the modeling edit.

The verifier checks ordered BC blocks and every numeric row/column. A generic
INI key comparison would miss a changed data cell or lose repeated quantities.

## Exact preservation contract for the future CLI

| Requirement | Consequence for implementation |
| --- | --- |
| A scalar edit targets one section/key/value token | Preserve other values, comments, ordering, precision, encoding and line endings; do not regenerate the whole MDU by default |
| `HisInterval` can also encode an output window | Preserve optional start/stop values and distinguish seconds from `TUnit`; non-default windows require additional cases |
| A BC edit targets a named block, quantity/component and row | Validate block identity, function, period/frequency and units before modifying the value |
| Repeated `Quantity` and `Unit` entries describe columns | Preserve their order and all non-target columns and rows |
| PLI labels and support numbering are identities | Keep sparse support points and the zero-based/one-based mapping; do not infer identities from the filename alone |
| Neighboring signals and geometry are unrelated to this edit | Preserve other forcing blocks and EXT/PLI/network bytes; do not densify support points or resample signals |
| Application export can change presentation without changing model values | Report timestamps and reflow separately from semantic changes; a targeted file editor should retain unrelated spacing, including the zero row |
| Setter/read-back and exit status are not sufficient | Verify the written artifact against the intended value and scope of change before reporting success |
| Editing in memory is different from saving a project | Make project persistence explicit; these cases verify exports, not save/reopen persistence of the edited state |

All three accepted copied projects and the original baseline were unchanged by
hash and captured metadata. Each repeated export preserved its nine non-MDU
files exactly and its MDU values semantically. Nine known MDU/EXT input references
resolved inside each export folder.

## Retained failures and operational finding

The exploratory scalar case's initial concurrent startup failed before script
execution with access denied to `C:\Temp\DeltaShell_Working_Directory`. The native
console still returned 0; the wrapper rejected the missing completion marker.
Sequential retry succeeded. The clean replay runs all cases sequentially.

Shared temporary-directory contention is a plausible explanation, not a proven
root cause. Do not assume separate model folders make concurrent shell startup
safe; characterize scratch-directory isolation before enabling concurrency.

## Reproduce

Use the existing fresh E001/E002 baseline and a new, nonexistent output folder:

```powershell
python research/scripts/run_edit_experiment.py --baseline research/experiments/E001-E002-replay-20261103/gui-project --install 'C:\Program Files\Deltares\Delft3D FM Suite 2026.02 OpenHMWQ' --out research/experiments/E003-E005-new-replay
```

The command creates three independent project copies, records fingerprints,
executes the cases sequentially, exports each twice, writes text/semantic
comparisons, and verifies preservation. It requires the locally collected suite
and baseline; it does not run the solver.

Tracked implementation:

- `assets/edit-experiment/export_case.py`: guarded IronPython model API edits.
- `scripts/run_edit_experiment.py`: copying, process execution and snapshots.
- `scripts/verify_edit_experiment.py`: MDU values, BC cells/metadata, references,
  repeatability and project-preservation checks.

Local evidence:

- `experiments/E003-E005-edits-20261104/`: inspection logs, raw-setter negative
  probe, startup failure, accepted scalar in `scalar-owned/`, accepted boundary
  and control, comparisons and `verification.json`.
- `experiments/E003-E005-replay-20261104/`: clean sequential replay, per-case
  invocations/results, snapshots, `analysis/` diffs and `verification.json`.

## Sources and limits

The retained runtime inspection establishes `HisOutputDeltaT`'s `TimeSpan` type,
the raw interval's list type, and the harmonic data's names, indices, frequency,
units and values. Invocation records fingerprint the executable and scripts.
Private targeted `MduFile` inspection fingerprints its assembly; its
`GetPropertiesByGroup` writes the generated timestamp/version header.

Manual references: D-Flow FM User Manual, output parameters §7.4.14, printed
pp.118-121 / PDF pp.144-147; boundary conditions §7.4.8 and Appendix C.5,
printed pp.89-107 and pp.422-427 / PDF pp.115-133 and pp.448-453.

This establishes application API editing/export behavior for one normalized
fixture. Interactive GUI dialogs, modified-project save/reopen persistence,
unknown/custom-key preservation, other boundary functions, non-default output
windows, boundary snapping, solver initialization and physical behavior remain
untested. Existing legacy network and optional numerical-library warnings are
retained in the logs. Follow-up [E004/E008](serial-experiment.md) verified a
separate bounded serial engine case using the unchanged baseline, not these edits.
