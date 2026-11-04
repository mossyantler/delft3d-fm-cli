# Pinned f152 RR/FM preparation

These three specifications require the complete local 62-blob acquisition at
`research/experiments/RR-G-f152-source-01/source`. Every original blob is checked
against SHA256, Git blob SHA1 and size from HYDROLIB-core revision
`48993b1c85d6237ba55de08a4b4fbf8cb7965b80`. No acquisition or native execution
occurs in `rr-f152 prepare` or `inspect`.

From the repository root, use a new existing parent directory and a new output
directory for each role. For example:

```powershell
$out = 'C:/Temp/RR-review-NEW/wet'
$preview = .venv/Scripts/dfm.exe rr-f152 prepare examples/rr_f152/wet.json --out $out | ConvertFrom-Json
if (-not $preview.ok) { throw 'Preview failed' }
.venv/Scripts/dfm.exe rr-f152 prepare examples/rr_f152/wet.json --out $out --apply --expect-sha256 $preview.result.input_sha256
.venv/Scripts/dfm.exe rr-f152 inspect $out
```

Repeat with `dry.json` and `hydraulic.json`, using distinct new destinations.
Apply requires the fingerprint of the same source/spec/destination preview;
source bytes are checked again before publication. Existing outputs are refused.
Relocating a prepared case does not require the acquisition folder: the receipt
contains the complete inventory and compressed originals of changed/unstaged
blobs, permitting reconstruction and validation against all 62 pins.

## Fixed experiment and clock

The source is f152, not c11: 95 RR nodes, 61 links, and all original 34 pairs in
each coupling direction. Three disconnected boundary IDs (`lat_902`, `lat_994`,
`lat_1022`) remain in the graph and cannot establish runoff discrimination.

All three roles explicitly run 2000-01-01 00:00:00 through 00:10:00 with UTC
declared by this case. RR INI EndTime is actually shortened to 600 seconds;
RR step is 300 seconds and FM output cadence is 60 seconds. Before-master
controller calls at 0 and 300 exchange FM levels into RR, advance RR to 300 and
600, and return actual RR discharge to FM. The native initial RR row at 0 is
initialization, never an already-received FM sample.

| Role | Only physical difference from wet |
| --- | --- |
| wet | Two 300-second rain records, 10 mm per record at each original 35 stations |
| dry | Same event/header/stations; numeric rain matrix is zero |
| hydraulic | Wet rain; existing waterlevel forcing `141134_395446` increased by 0.2 m |

All other engine input bytes match between roles. Added instrumentation and
clock corrections are identical. Original material/initial conditions, all other
forcing blocks and the original four observation points are retained. No
parameter fitting or effective-influence claim follows from preparation.

All 67 original FM BC forcing blocks contain 482 rows spanning 0..28860 minutes
since 2000-01-01 00:00:00, covering this 0..10-minute trial. The retained RR EVP
contains daily values for January1..10 (mm/day). Rain is authored explicitly for
the two requested 300-second intervals; the source's day-long RR clock and extra
post-event rain row are not silently reused.

## FNM disposition and readiness

`inspect` exposes every one of the 123 positional FNM entries under
`profile.fnm_disposition.slots` and `references`. These rules are permitted only
after the complete source has been reconstructed and every derivative input byte
has been reproduced from the fixed recipe. Unknown slots still block readiness;
unknown files are never waived by filename. The generic `source_audit` remains
conservative and retains its original issues separately.

The adapter's current static disposition is complete, with zero unresolved
source-reference blockers. `native_readiness=prepared_only` and `launchable=true`
mean eligible for a separately leased native trial. `native_gate=pending`,
`native_initialization=not_performed` and scientific validation remain separate.
The installed engine's source commit is unknown.

Particularly relevant missing/empty entries:

| Slots | Fixed-recipe disposition and pinned source evidence |
| --- | --- |
| 4, 9, 117 | Required empty scan containers; retained, never replaced by invented records |
| 8, 34 | Retained empty table containers; actual constant/inline options do not select their tables |
| 39, 58 | Retained legacy slots with no input reader in pinned source; closed private-storage/getter-consumer proof below |
| 80 | External-runoff reader gated by internal type18 count; this graph has none |
| 95 | Native CapSim message output, `UnpavedModule.F90:4606-4614`; source placeholder retained in provenance only |
| 114 | `RRModule.F90:320-325` explicitly warns/continues if DIO config is absent; an added untracked config is refused |
| 115 | `NWRWContinuous=0`; conditional alternative rain path is inactive |
| 118 | No Cell nodes; the pinned Cell reader is disabled |
| 121 | Salt/WQ computation defaults remain disabled; old salt HIS path also excludes DLL/DIMR |
| 123 | `UseOpenDAFile` defaults false, no override; `RestartIn=0`; optional read/write paths inactive |

Slots39/58 are not declared universally obsolete. `Conf_fil.f90` keeps `NAMFIL`
private and exposes names only through its scalar getter. Complete consumer
enumeration found 285 literal getter callsites (none selecting39/58). The seven
dynamic executable sites are only local filename transformations followed by
setters: `FILESMODULE.F90:617,670` and `INITDT.F90:181,183,190,198,210`.
Later output-name tables explicitly select actual output slots. This closes the
reader dataflow in native source revision
`5a4649830b1e5072caf019fb4850bbdefd9ad431`; it does not identify the installed
engine's commit. `rr_f152_slots.LEGACY_READER_PROOF` records file hashes, scope,
and locations. SaltComputation's disabled default is separate from OutputRRSalt.

All62 originals remain fingerprinted, including runtime return-code and CapSim
message placeholders. Those two outputs are not immutable staged inputs:
60 native files + two metadata files + the receipt = 63 immutable staged files.
Deleting a required empty input, introducing an untracked FNM input, changing a
recipe byte/clock/graph, or aliasing an FNM output to an input is refused.
Old preparation receipts with the earlier incorrect CapSim provenance basis
remain historical and fail the new guard; create fresh cases rather than
rewriting them.

## Actual native observation declarations

| Path | Selected native data |
| --- | --- |
| `logs/flow2rr.nc`, `logs/rr2flow.nc` | 34 scalar `itemN_values` in each direction, controller offsets0,300; no fabricated terminal sample |
| `rr/bndflodt.nc` | `locations`, integer CF `time`; `Flow` [m3 s-1], `Boundary_Level` [m AD], current aggregation, completed RR offsets300,600 |
| `fm/output/f152_his.nc` | `lateral_name` and actual prescribed/realized instantaneous plus realized interval-average discharge [m3 s-1]; exact 34 IDs |
| `fm/output/f152_his.nc` | `station_id`, `waterlevel` [m]; added `rr_ID` stations at the exact REALTIME 1D lateral branch/chainage |

RR output spelling may be uppercase; the source DLL explicitly uppercases its
lookup. Masked trailing zero/space name padding is permitted; masked identity
payload, duplicate identities, missing/nonfinite values, incompatible units,
calendars, wrong times and receiver initialization sentinels are refused.
`m AD` is the native label, not proof of a surveyed vertical datum. The exact FM
station interpolation versus the lateral BMI getter remains an independent
native check. FM initial output at0 precedes coupling; solved60..300 and360..600
belong to returned RR Q at300 and600 respectively. Interval-average Q must not
be treated as an instantaneous snapshot.

## Independent review and remaining gates

Public preparation and inspection, immutable common staging, binary hashing and
the observer can be checked without executing native code. Common runner owns
the actual launch and unchanged Windows Job lifecycle. No native process has
been started by the author node.

The integrated public dry plan stages the exact command and selected installed
binary hashes without creating a native Job/process or an active run manifest:

```powershell
.venv/Scripts/dfm.exe coupling validate "$out/dimr_config.xml"
.venv/Scripts/dfm.exe coupling plan $out --out 'C:/Temp/RR-plan-NEW/wet' --install 'C:/Program Files/Deltares/Delft3D FM Suite 2026.02 OpenHMWQ' --timeout 60
```

Use the actual selected suite path. `plan.json` is preparation evidence only;
the eventual leased run needs another new output directory. Independent common
review reconciles the28 generic unresolved slot issues only for the byte-guarded
fixed recipe and checks each native FM reference, including individual semicolon
roughness-list members. Generic RR audits remain conservative.

Portable review should cover the three exact physical differences, all62
original pins, no-overwrite/hash conflict, relocation, missing empty containers,
untracked DIO and output/input aliases, complete123 dispositions, malformed
NetCDF IDs/units/calendars/times/masks/sentinels, and common staging without an
execute call. Existing independent RR and coupling portable tests also apply.

Native acceptance still requires an assigned lease, actual initialization and
finalization of the installed RR/FM, real output paths/dimensions/clock coverage,
both receiver chains, explicit single-precision RR level rounding, signed volume
budgets and independent wet/dry/hydraulic discrimination. Sender logs or
successfully decoded files alone do not pass physical exchange. Preserve native
diagnostic warnings, timeout/cancellation ownership checks and retained failures.
