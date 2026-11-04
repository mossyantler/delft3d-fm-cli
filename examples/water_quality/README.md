# E015-WQ: fixed f34 internal processes, native gate pending

`fm_processes.json` builds genuine example03 positive/control **input** cases.
It does not execute the model or establish a chemical effect. The process
database data pair is copied into each private case; installed DLLs/executables
remain selected by the existing owned coupling runner. No new dependencies.

The independent contract is in
`src/dfm_cli/water_quality_contract.py`. Pinned source commit:
`5a4649830b1e5072caf019fb4850bbdefd9ad431`, 70 exact example03 `dflowfm` files,
input-set SHA256 `a74cefdc861fbcd5423998e62fe9e9a9fbdce790ba4cc885225af64239c9e329`.
The retained source is
`research/experiments/E015-WQ-I-20261104-01/example03/dflowfm`;
`source-manifest.json` independently lists each original Git-blob SHA256.
To use another materialization, change only `source_root` to its explicit path.
Arbitrary or changed user models are refused, even if named f34.

The common clock is 1990-08-05 00:00:00 UTC through 01:00:00, process interval
60 s and map/history cadence300 s. Both retain all original active processes,
boundary/initial fields, grid and native parameter definitions. They explicitly
select `SWVnNit=0` and `ZNit=0`; their sole physical difference is `RcNit=1/day`
versus `0/day`. NH4 starts at the source polygon's0.4g/m3, OXY8gO2/m3; all
spatial provenance is inherited and geodetically unverified. Source boundary
tracer units are literally `-`, a retained limitation. No silent unit repair.

Pinned `nitrif.f90` old branch computes `ZNit + RcNit * max(NH4,0) *
TcNit**(Temp-20) * O2FUNC` above its critical temperature. Inputs CSV maps
`RcNit` to slot14 and `SWVnNit` to slot13. `stochi.csv` maps dNitrif to NH4=-1,
NO3=+1, OXY=-4.571. These are **source** facts; installed process database hashes
and actual native branch/updates still need independent checking. Other active
processes prevent treating whole-model NH4 as an isolated exponential oracle.

Current standalone authoring syntax (shared CLI registration is coordinator-owned):

```powershell
.venv/Scripts/python.exe -B -m dfm_cli.water_quality water-quality prepare examples/water_quality/fm_processes.json --process-library '<kernels>/share/delft3d/proc_def.dat' --out '<new-bundle>'
# Preview writes nothing. Reuse result.input_sha256 explicitly:
.venv/Scripts/python.exe -B -m dfm_cli.water_quality water-quality prepare examples/water_quality/fm_processes.json --process-library '<kernels>/share/delft3d/proc_def.dat' --out '<new-bundle>' --apply --expect-sha256 '<preview-hash>'
.venv/Scripts/python.exe -B -m dfm_cli.water_quality water-quality inspect '<new-bundle>'
dfm coupling prepare '<new-bundle>/spec-positive.json' --out '<new-positive-case>'
dfm coupling prepare '<new-bundle>/spec-positive.json' --out '<new-positive-case>' --apply --expect-sha256 '<coupling-preview-hash>'
# Repeat coupling prepare for spec-control.json with its own preview and new case.
```

Bundle artifacts: two copied sources, `spec-positive.json`, `spec-control.json`,
`effect-plan.json`, `water-quality-provenance.json`. Coupling adds its own source,
spec and preparation receipts. Neither an authored receipt nor validated XML
establishes native support. Native runs need an allocated exclusive lease and
fresh run folders; existing owned coupling run/cancel/control handles execution.
No native command is exposed by this module. Coordinator integration is additive:
register `water_quality.register(groups)` and dispatch to `water_quality.execute`.
Faraday can consume the emitted ordinary coupling specs without modifying the
coupling contract. Separate Einstein tests/verifier own independent acceptance.

Declared fields (map/time): `mesh2d_NH4` g/m3, `mesh2d_NO3` gN/m3,
`mesh2d_OXY` gO2/m3 and `mesh2d_s1` m. Einstein must independently read native
schema and raw CF clocks, spatial connectivity/coordinates and equal wet/dry masks,
run-manifest/input/library provenance and actual process update schedule. Plan
thresholds require equal initial fields, matched hydro, final NH4 lower and NO3
higher than control. A single final file, nonzero field or process exit is not an
effect oracle. If either schema/units or chemistry differs, preserve raw evidence
and revise the next experiment; never rewrite solver outputs to pass.

Offline WAQ is separate. This read-only command inventories an explicit chain:

```powershell
.venv/Scripts/python.exe -B -m dfm_cli.water_quality water-quality review-offline '<private-copy>/com-tut_fti_waq.hyd' '<private-copy>/com-tut_fti_waq.inp' --install '<suite-root>'
```

Pinned `examples/delft3d4/06_delwaq` (28 files retained under the fresh receipt's
`offline-reference06`) has Salinity, IM1 and EColi; `coli_03.sub` declares EColi
`(MPN/m3)` and mortality0.8/day. Its `.inp` directly consumes binary volume,
flow, pointer, length and parameter/diffusion data plus includes. `.hyd` describes
the hydro origin, grid and clock; it is not quality input by itself. Its original
`.dat` origin metadata is absent, distinct from required consumed files.
Hydro ends1990-08-06 01:00, while WAQ input ends1990-08-15 12:30: periodic/reuse
rules are unverified. Retain this mismatch, do not stretch or synthesize hydro.
The source's new `delwaq.exe` preprocesses then solves; its documented source CLI
is not evidence the installed executable accepts those flags. Binary discovery
only records paths/hashes. `-validation_mode` itself writes preprocessing files;
it is not a read-only preflight. Offline native format/consumer/physics gate stays
unavailable until separately exercised with controlled copied inputs.
