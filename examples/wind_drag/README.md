# Existing Smith&Banke drag table: inspect and edit

This small 48-cell, two-boundary 2D input graph demonstrates inspecting and
editing an existing two-breakpoint table. The authored `[wind]` table has
`ICdtyp=2`, dimensionless `Cdbreakpoints=0.0025 0.0025`, and
`Windspeedbreakpoints=0 100` in m/s. No wind forcing is attached. These files do
not establish wind response, a successful run, or scientific validity.

The seven files under `model/` are all bound native inputs. The mesh is copied
from the tracked weir-series example; the remaining inputs are authored with
the existing channel JSON and file-only model authoring helper. No weir or
structure input is used. See the private `example-proof.json` for provenance.

Commands, as written for Windows PowerShell 5.1:

```powershell
Copy-Item -LiteralPath examples/wind_drag/model -Destination wind-case -Recurse
$mdu = 'wind-case/model.mdu'
dfm wind drag-inspect $mdu
$changes = '[{\"index\":1,\"coefficient\":\"0.0030\"}]'
$request = @('wind','drag-set',$mdu,'--changes',$changes,'--coefficient-unit','dimensionless','--speed-unit','m/s')
$p = dfm @request | ConvertFrom-Json
if ($p.ok) { dfm @request --apply --expect-sha256 $p.result.input_sha256 }
```

Indices are one-based. Coefficients/speeds are explicit numeric strings. A row
may contain a coefficient, a speed, or both. Exactly two entries must already
exist in each array; the command never inserts defaults or changes the law.
Only selected numeric tokens change. The second coefficient stays `0.0025`
in this example, and the other six files remain byte-identical.

To publish a fresh complete input graph instead, include `--out NEW_DIRECTORY`
in **both** preview and apply. The destination must be absent and disjoint from
the source folder; the source remains untouched. A hash for an in-place request
cannot authorize a copy request. The copy uses new file permissions and does
not clone original ACLs or timestamps.

Other drag laws, legacy EXT, initial fields, spatial coefficients, stress-input
conversion and gridded meteo providers are refused. Coefficients are admitted
within [0,1] and speeds within [0,1000000] m/s; these are conservative editor
bounds, not physical validation ranges. Speed gaps must be at least 0.1 m/s,
including a binary64 check against the source reader's automatic clamp.
In-place publication uses the existing ACL-preserving publisher and refuses
unsupported access controls. This example requires no optional packages for
inspect/preview/edit; authoring/mesh checks used the existing optional NetCDF
environment. No dependency changes are proposed.
