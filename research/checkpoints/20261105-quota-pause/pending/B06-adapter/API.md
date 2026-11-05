# Prospective B06 public-manifest adapter

This is a read-only research adapter. It contains no launcher, product imports,
native API, Job implementation, environment installation or package builder.
It does not grant a native lease, runtime acceptance or scientific calibration.

Only four observed cases are admitted: `point_set15_direct`, `pair_set15_direct`,
`point_set15_dimr`, `pair_set15_dimr`. The original B06 plan and #225 tolerances
are unchanged. Every case needs its own actual public execution. The retained
#225 C5/noop/add references do not become new route controls.

## Callables

`provenance.admit(admission_pin, expected_sha, *, kind='observed_native')` returns
a frozen `Admission`. A file pin is `{path, bytes, sha256, identity?}`; identities
are `[device,inode,size,mtime_ns,nlink]`. Actual collection pins require identity.
Paths must be absolute, local, ordinary, singly linked and free of reparse or
symlink components. `Refusal` reports missing, malformed or conflicting evidence.

`provenance.bind(admission, collection_row)` returns a frozen `BoundRun` retaining
the original raw manifest, CLI stdout, status and invocation byte strings plus
their complete parsed objects. It never reshapes these into a research receipt.
`BoundRun.model`, `.returncode`, `.stdout_text()`, `.verify_output(path)`,
`.recheck()` and `.proof_summary()` supply provenance to the unchanged math.
Changing its dictionary projections is detected. All native ownership fields,
including unknown fields, false flags and nulls, remain in the original bytes
and full object. The adapter cross-binds root image/birth/token/route, but delegates
native HANDLE/Job/collector/cleanup adjudication to separately pinned shared V/G.

`science.reference_context(source_case)` returns **ReferenceContext**, never
PublicContext. It reads the original private #225 receipt, inputs, native log and
datasets with their hashes. It cannot claim a new public execution or route.
`science.check_science(context, source_case)` runs the frozen field predicates and
all170 exact comparisons. It refuses synthetic PublicContext science. Direct and
DIMR public contexts must first be independently admitted/bound.

`science.verify_collection(admission_pin, expected_admission_sha, collection_pin,
expected_collection_sha, out)` verifies the exact four public cases. It writes
only to a fresh B06 research directory. Raw JSON bytes are copied intact under
`out/raw/`; original files are never rewritten. Missing cases or any provenance,
physics, unknown-variable, mask, metadata or final-content failure prevent pass.

CLI, after corrected-runtime approval, final adapter independent/G review,
actual capture and separately allocated native completions only:

```powershell
.venv/Scripts/python.exe -B research/experiments/B06-V-public-provenance-20261105-01/science.py --admission ABSOLUTE_ADMISSION_JSON --expect-admission-sha256 ACTUAL_EXPECTED_SHA256 --collection ABSOLUTE_COLLECTION_JSON --expect-collection-sha256 ACTUAL_EXPECTED_SHA256 --out research/experiments/B06-V-public-provenance-results-FRESH
```

These expected hashes are research evidence binding, not public product tokens.
The product continues to use ordinary explicit `dfm run start` arguments.

## Admission and capture sequence

1. Shared common V/G and the coordinator must accept a corrected common runtime,
   its source-profile composition, clean source→wheel→installed payload set,
   dependencies/origins and actual entrypoint. No such admission is supplied here.
2. A separately reviewed collector freezes `b06-public-capture-plan-v1` **before**
   native dispatch: exact four case IDs, original public argument arrays, source
   and run paths, collector code pin and reviewed collector freeze pin.
3. The coordinator publishes a new `b06-public-run-admission-v1` with the keys
   listed below and its independently expected hash. It binds six explicit V/G
   approval artifacts and this adapter's exact freeze. Producer success flags,
   root state, binary presence and arbitrary caller hashes are not approval.
4. Only a separately allocated collector may invoke the public commands. It
   retains actual public stdout/stderr/return code/controller birth/interpreter,
   raw terminal manifest/status, native logs and terminal generated-file identity
   inventory. This adapter never performs those actions.
5. Shared native ownership V/G reviews the actual raw manifest/ownership and
   publishes its case/route/runID/manifest/object-fingerprint-bound receipt.
6. The coordinator independently pins the complete collection after all four
   terminal captures. The adapter then joins it to admission and the #225 oracle.

File-only consistency cannot certify an arbitrary caller-fabricated execution.
The expected hashes must come from the independent/coordinator freeze chain,
with actual reviewed public capture and native ownership evidence. A collection
made by the synthetic fixture generator is never eligible as observed evidence.

### Admission object

Exact top-level keys:

- `schema: 'b06-public-run-admission-v1'`, `evidence_kind: 'observed_native'`.
- `scope: 'prospectively_accepted_corrected_common_and_B06_source_profile'`.
- `adapter_freeze_sha256` and `approval_artifacts` with exactly
  `common_independent`, `common_G`, `package_independent`, `package_G`,
  `adapter_independent`, `adapter_G`, each an actual retained file pin.
- `common_freeze`: actual approved corrected common source freeze pin.
- `package`: exact keys `wheel`, `composition_freeze`, `source_payloads`,
  `site_packages`, `runtime`, `dfm`, `python`, `origin_audit`, `dependency_lock`,
  `software`, `runtime_files`. File members are pins; runtime/site are absolute directories.
  `source_payloads` JSON has `payloads:[{path,relative_path,bytes,sha256,...}]`.
  Complete source/wheel/site sets and hashes must agree; payload count is derived.
  The clean venv must have no `.pth`/egg linkage or system site packages. The
  packaging V/G artifacts, rather than this reader, adjudicate full dependency
  and actual import-origin audit evidence. `software` matches the complete actual
  public manifest `software` object.
  `runtime_files` pins a `b06-admitted-runtime-files-v1` JSON object containing
  `runtime`, `base_prefix`, `files:[{relative_path,path,bytes,sha256,identity}]`
  and `external_interpreter_files:{base_python:PIN,python_dll:PIN}`. Every runtime
  file except `__pycache__` entries must be listed and rehashed, including
  `pyvenv.cfg`, installed dependencies and entrypoints. The two base-interpreter
  pins must reside under `base_prefix`, matching the venv's explicit `home`.
  Limits are 10,000 runtime files / 2 GiB total; each file is at most 512 MiB.
  Product payload limits are 512 files / 32 MiB total / 4 MiB per file and a
  64 MiB wheel. These are reader limits, not wider product capability claims.
- `installation`: exact keys `root`, `kernels`, `binaries`, `proj_db`. Binary keys
  are `bin/dflowfm-cli.exe`, `bin/dimr.exe`, `lib/dflowfm.dll`, `lib/dimr.dll`,
  `lib/gdal.dll`; each is an actual pin. `proj_db` is a pin or null. Direct FM
  must match the retained #225 executable hash. FM DLL, DIMR executable/DLL,
  GDAL and PROJ are separate pins; an executable/version string is insufficient.
- `entrypoint_prefix`: `[actual_dfm_exe]` or
  `[actual_runtime_python,'-I','-B','-m','dfm_cli']`.
- `cases`: exact four IDs, each `{source_case,route,source_mdu,run_directory,
  timeout_seconds}`. Source inputs may be privately relocated but must match the
  frozen active six plus preserved inactive old BC exactly. No renamed data or
  new case/physics is admitted. Future run paths are fixed before dispatch.
- `reference_contracts`: pinned `input_closure` and `reference225` files from
  B06-V-public-run-01. `capture_plan`: reviewed prospective capture-plan pin.

The failed wheel `23f9daa7...`, common source `ced356ad...`, and obsolete held
compositions `b06261eb...`/`d37a661c...` are explicitly refused. Current rev03/rev04
author freezes are not automatically approved or bound by this packet.

### Collection object

`{schema:'b06-public-collection-v1',evidence_kind:'observed_native',
admission_sha256,capture_plan_sha256,cases:[...]}`. The reader requires its
separately expected SHA. Each case row has exactly `case_id` and file pins
`manifest`, `public_stdout`, `public_stderr`, `status`, `invocation`,
`native_stdout`, `native_stderr`, `ownership_review`, `terminal_inventory`.
All these pins include the captured five-field identity. Native log files are
`run/stdout.log` and `run/stderr.log`; public JSON stdout is a distinct file.

Invocation JSON has exact keys `schema:'b06-public-invocation-v1'`,
`evidence_kind`, `case_id`, `admission_sha256`, `capture_plan_sha256`, `returncode`,
`controller_identity`, `entrypoint`, `interpreter`, `argv`, `stdout`, `stderr`,
`manifest`, `cwd`, `environment`, `started_at_utc`, `finished_at_utc`.
Its argv must equal the reviewed capture plan. The public suffix is
`run start ABSOLUTE_MDU --profile source-sink --route ROUTE --install SUITE --out
ABSOLUTE_RUN --timeout SECONDS`, with those five options in any nonduplicated
order; optional `--restart-policy require-final` is accepted. Unknown flags refuse.
Environment capture is `removed:['PYTHONPATH','PYTHONHOME']` and
`overrides:{PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1'}`. Controller timestamps
enclose the native manifest's timestamps. Raw argv is retained, not rewritten.

Ownership review JSON: `schema:'b06-public-shared-ownership-review-v1'`,
`evidence_kind`, `case_id`, `route`, `run_id`, actual `manifest` pin,
`ownership_sha256` (canonical full object fingerprint), `decision:'passed'`.
The manifest pin retains the exact unnormalized raw bytes containing that object.
The external V/G review is required; this adapter does not replace it.

Terminal inventory JSON: `schema:'b06-public-terminal-files-v1'`, `evidence_kind`,
`case_id`, actual `manifest` pin, and `generated_files` with every manifest-listed
generated file's captured path/size/hash/identity. These identities detect even
same-byte replacement after capture. No borrowed, extra or stale NC files pass.

## Route and science boundaries

Direct argv remains `[actual dflowfm-cli.exe,'--autostartstop','model.mdu']`, cwd
`run/model`. DIMR remains `[actual dimr.exe,'dimr_config.xml']`, cwd `run`. The
actual XML must have `DFlowFM` spelling for start/component, `library=dflowfm`,
`process=0`, communicator `DFM_COMM_DFMWORLD`, workingDir `model`, inputFile
`model.mdu`; its raw bytes/hash/identity are checked. No FM child is invented for
DIMR. Raw ownership root image must match the actual selected route executable.

The old independent scientific body, label decoder, all-array functions and exact
comparison are AST-identical. Only the old research post_inventory lookup was
replaced with `context.verify_output(path)`. `math-extraction.json` documents the
excluded original path-provenance statements and common normalized AST digest.
The old source and all124 freeze pins were checked before extraction.
The wrapper checks complete variable/dimension/type/shape headers against the
reference before the frozen observer reads arrays. This bounds rejected shapes
without changing the scientific body or permitting a time-only artifact.

Every actual case needs all170 variables (82 HIS,36 MAP,26+26 RST), 121 native CF
samples0..120 and singleton restart0/120, three stations and48 physical cells.
All arrays/masks/dtypes/dimensions/variable attrs are exact against corresponding
#225. Only global history/date_created/date_modified/uuid differences are recorded
as provenance. BC salinityDelta is `ppt`; raw NC salinity remains `1e-3`. Neither
is converted. Original stock/current/cumulative/time tolerances are unchanged.
Q.1 over120 seconds gives12m3; point net+12, pair net0; C15 stock+180ppt*m3. No
same-route new C5 contrast or general calibration claim is made.

## Offline controls

`synthetic.fixture(fresh_directory)` constructs plainly marked **nonexecuting**
stub binaries, a small synthetic ZIP, opaque NOT-NETCDF output placeholders and
synthetic JSON envelopes. This is not a product build or public/native run.
`admit(...,kind='synthetic')` is an API for provenance tests only; observed-native
CLI never uses it. Frozen context classes prevent domain reassignment and detect
dictionary mutation. Synthetic contexts cannot call public science.

```powershell
.venv/Scripts/python.exe -B research/experiments/B06-V-public-provenance-20261105-01/selfcheck.py --out research/experiments/B06-V-public-provenance-20261105-01/selfcheck-FRESH
```

Read-only archived #225 math controls have ReferenceContext provenance, not a
fabricated public manifest. Mutated copies exercise science refusal without any
public context or new execution claim. The first71-check receipt is retained:
one time-only-field `Missing` was misclassified by the author harness, then
explicitly classified as a scientific missing-data refusal. No math/tolerance was
changed. Independent Einstein review and coordinator final review remain pending.
The final source-bound run is named in `verification.json`; all earlier receipts
remain available. `freeze.json` pins the implementation and exact final evidence.
`admit` validates already captured terminal evidence; it is not a native
preflight or launcher. The admission JSON, reviewed capture plan and their hashes
must be frozen prospectively even though the reader requires terminal run paths
to exist when it later validates them.
