# E014 bounded property export replay

Preparation and verification launch nothing. A prepared bundle is NOT evidence
of GUI behavior. Ordinary-host launch is disabled. The shared guest lifecycle
requires an independently identified disposable Windows guest/profile, its
target-bound disposal declaration and a coordinator-assigned exclusive lease.
No engine Run/Calculate is called. Startup itself accesses per-user settings;
TEMP redirection alone does not isolate them.

This is a standalone FM-only field experiment. It does NOT run P08's FM/DIMR
export experiment, require its success or use dummy P08 receipts. Only the
reviewed isolated guest/lease/Job/lifecycle hook is shared. Until the coordinator
integrates the closed, experiment-specific lifecycle API, live launch is blocked;
there is no fallback runner. The former generic runner-hook.patch is SUPERSEDED,
must not be applied, and is not a launch authorization.

The original saved f34 is Chezy: law 0, coefficient 65, initial level 1.9 m,
DtMax 30 s. Its datum is undeclared. Do not call 65 a Manning coefficient.
Its original DB and companion remain immutable. Separate fresh project copies
cover unchanged control, WaterLevIni 1.9 -> 2.4 m and DtMax 30 -> 15 s.
DtMax is a Double in seconds, independent of TUnit; it is NOT model.TimeStep
(which maps to DtUser).

Manning is a DISTINCT explicitly authored input baseline, not an equivalent
calibration. Coordinator source: E014-G-source-controls-01/
f34-manning-authored-control. Only prerequisite changes are law 0 -> 1 and
coefficient 65 -> 0.023. The guest imports this MDU into a NEW project and
SaveAs to a NEW DB. Both unchanged export and closed/reopened export MUST show
law 1 and coefficient 0.023 before ANY coefficient edit. Then fresh independent
copies provide an unchanged Manning control and coefficient-only 0.023 -> 0.041
s m-1/3 edit, preserving law 1. Never replace the original f34 DB or use a law
change as part of the single-field edit. No datum/CRS assumptions or scientific
equivalence are introduced by this export-only fixture.

The STATIC CANDIDATE owner is model.ModelDefinition.GetModelProperty(KEY).Value,
a WaterFlowFMProperty inheriting Common.ModelSchema.ModelProperty.Value. This
is read-only installed schema/type evidence, NOT a measured live owning object
or successful mutation. The guest must measure and qualify it. Installed
CSV plus live property definition/Double type/unit/assembly hashes are recorded.
Conditional roughness metadata is retained verbatim, with law 1 explicitly
selecting s m-1/3. Wrong unit/owner/law are protocol refusals before assignment;
invalid numeric text exercises actual SetValueFromString and must produce
System.FormatException without mutation. Unsupported item and missing path
exercise actual FMModelFileExporter; same-value typed assignment is a no-op
control. Exported bytes, not typed readback alone, decide acceptance.

Each cases/{control,waterlevini,dtmax,manning-control,manning} has before/after/
reopened exports. All ten names, all nine non-MDU byte hashes and ordered MDU
occurrences must match. Only the unique requested numeric token may change;
the first exact '# Generated on YYYY-MM-DD HH:MM:SS' timestamp is separately
allowed. No generic timestamp/comment/path/precision/NetCDF UUID stripping.
Collateral export or SaveAs migrations FAIL and are retained for diagnosis.

E014 has its own manifest kind, request kind, nonce, fields-result.json,
completion marker and fields-verification.json. No P08 host-result, DIMR outputs
or P08 verification gate exists in this experiment. The shared lifecycle checks
owned exit/empty-job evidence. 'verify' alone reports files only, never a live
GUI operation. This implementation route is console-hosted supported model API;
interactive GUI clicks and solver/physics remain unverified.

From repository root, portable preparation (substitute a NEW output path):

```powershell
.venv/Scripts/python.exe -m research.workflows.replay.fields_project_export prepare --project research/experiments/E001-E002-replay-20261103/gui-project/gui-baseline.dsproj --manning-source research/experiments/E014-G-source-controls-01/f34-manning-authored-control --install 'C:/Program Files/Deltares/Delft3D FM Suite 2026.02 OpenHMWQ' --out NEW_BUNDLE
.venv/Scripts/python.exe -m research.workflows.replay.fields_project_export inspect --bundle NEW_BUNDLE --expect-sha256 MANIFEST_HASH
```

The original ten-file Chezy export is also staged, and the exact two-token
Manning prerequisite is checked. By default the explicit coordinator receipt
beside the supplied Manning source identifies that export; alternatively supply
--manning-original ORIGINAL_CHEZY_EXPORT. The receipt/hash is input provenance,
not runtime identity or custom cryptographic trust.

With no guest identity or shared hook, output MUST say NOT_READY_FOR_LIVE_RUN. To prepare a
launchable transfer, additionally supply --host-identity HOST.json
--target-identity GUEST.json --declaration DISPOSABLE.json. Reuse the read-only
identity format, but E014 requires its OWN exact declaration; P08 purpose is
rejected before copying/launch:

```json
{"schema":1,"purpose":"E014_f34_typed_property_export","disposable":true,"independent_profile":true,"shared_profiles_disabled":true,"target_identity_sha256":"DIGEST_OF_GUEST_DESCRIPTOR"}
```

The digest uses the existing sorted compact JSON identity fingerprint, not a
custom trust mechanism. E014's manifest kind and isolation purpose are both
E014_f34_typed_property_export; its marker is E014_FIELDS_EXPORT_OK:<nonce> and
its only final verifier is the fixed E014 FM field verifier. No arbitrary
script/callback override is admitted. Nash owns the shared lifecycle and complete
prospective Job trace packaging. Source-only replays never upgrade or modify an
old bundle in place: prepare a NEW directory with the reviewed current runtime,
then independently inspect its NEW external manifest hash. Old bundles and
their historical hashes remain unchanged and cannot inherit new trace evidence.

The agreed shared API is closed: prepare_export_guest(project, install, out,
kind=KIND, ...), inspect_export_guest(bundle, expected_sha, kind=KIND), and
run_export_guest(bundle, expected_sha, install, out, kind=KIND, slot=LEASE,
timeout=SECONDS). E014 passes no script, callback, marker, report-name or record
override. The registry fixes those values and authenticates the frozen owner.
The request and E014 result also bind the exact bundle and shared lifecycle
fingerprints. Separate field output checks cannot substitute for the future
owned lifecycle/trace or measured runtime-property evidence.

Transfer the immutable bundle. ONLY in the actual
declared guest, after an assigned lease (these commands are instructions, not
authorization to launch):

```powershell
python BUNDLE/runtime/fields_replay.py run-guest --bundle BUNDLE --expect-sha256 MANIFEST_HASH --install SUITE --out NEW_PRIVATE_GUEST_RUN --slot ASSIGNED_LEASE --timeout 180
python BUNDLE/runtime/fields_replay.py verify --bundle BUNDLE --expect-sha256 MANIFEST_HASH --out NEW_PRIVATE_GUEST_RUN
```

No custom signature, crypto identity or duplicate native runner is introduced.
P08's selected suite files plus Common DLL and FlowFM CSV are fingerprinted.
Read-only local decompilation is ignored under local-inspection/; no installed
program code is included in the portable assets. Actual guest execution remains
pending and may expose migration or API behavior that static checks cannot prove.
