"""Scoped live FM BMI candidate. Native validation is PENDING a separate lease.

Coordinator registration only: add bmi to COMMAND_MODULES. register/execute follow
that module interface. No shared CLI/runner changes are made here.

 bmi session MDU --out NEW --install SUITE --timeout 45 [--controls JSON]
 bmi inspect MDU [--controls JSON]                 (no native loading)

Controls default to MDU.parent/bmi-controls.json. JSON v1 exact keys:
 {schema_version:1,crs:{epsg:32631,unit:'m'},vertical_datum:STRING,
  weirs:[{id:ASCII_ID,unit:'m',minimum:NUMBER,maximum:NUMBER,initial:NUMBER,
          transfer:'dimr_address_scalar'}]}.
The explicit CRS/datum must match the 2D UGRID metadata. Only the previously
tested projected EPSG:32631 mesh encoding is accepted. No datum conversion.
Only cold, uncoupled 2D UTC seconds, positive aligned output intervals, <=600s;
<=20000 faces, <=32 XYN observations and <=16 simple 2D weirs. Model references
are copied unchanged; a weir StructureFile requires locationFile (not the legacy
polylineFile alias), numeric crestLevel equal to declared initial and corrCoeff.
Optional crestWidth>0m, useVelocityHeight=true/false, allowedFlowDir=both are
validated. Its PLI is additionally checked. REALTIME/timeseries initial crests
are rejected: initialize verifies numeric native input without writing controls.
Other structure types, 1D, layers, MPI, Waves, processes, restart are unsupported.
No native inputs/outputs are changed outside the fresh session directory.

Public stdin/stdout UTF-8 JSONL, protocol bmi_protocol=1, <=8192 bytes/request,
<=10000 requests, unique positive integer id. Initial event 'ready' identifies
staged hashes, allowed scalars and native_validation='pending'. Requests:
 {id,op:'initialize'|'clock'|'finalize'|'abort'}
 {id,op:'step',seconds:NUMBER}                  (positive, <=60, DtUser aligned)
 {id,op:'get',name:NAME,unit:'m'}
 {id,op:'set',name:NAME,unit:'m',value:NUMBER}   (weirs only, declared bounds)
Reply {bmi_protocol:1,id,ok,result|error}. Names are observations/ID/water_level
and weirs/ID/crest_level. No pointers, arbitrary variable names, arrays, DLLs or
native functions are exposed. initialize checks clocks and reads every scalar,
then verifies explicit initial crest values without any initialization write.
Native return code0 with ERROR/structure-read rejection still fails. Worker lifecycle:
created -> initialized -> stepping -> finalized|aborted|failed. finalize is legal
before the requested stop but reports 'finalized_partial', never completed.
At stop, finalized output must pass the existing inclusive CF output verifier.
EOF, malformed requests, native error, timeout, Ctrl+C abort the session. Native
calls only occur in a Python -I isolated worker with a kill-on-close Windows Job Object;
the controller uses the existing OwnedJob API, retained handles and membership
checks. Native stdout/stderr go only to native.stdout.log/native.stderr.log;
Readiness proves the kernel-reported named-pipe client PID against the reported
PID, live retained handles in the exact private job, creation times and selected
interpreter image path/hash. A venv redirector child must be the root's direct
child and match sys._base_executable; a direct root interpreter is also accepted.
Root and actual worker identities are recorded separately; no same-name lookup.
authenticated local pipe messages use JSON bytes, never pickle. Public JSONL
ends with the shared CLI's ordinary protocol2 result/error envelope; standalone
python -m dfm_cli.bmi has the same behavior. Do not parse that as a scalar reply.

Files: manifest.json (kind=dfm_bmi_session, schema_version=1), model/* copied
inputs, control-contract.json, commands.jsonl, replies.jsonl, native.*.log.
Manifest records controller/worker identity, job cleanup, input/DLL/worker hashes,
clock samples, scalar reads/writes, partial outputs, inclusive output verification.
The shared run status/cancel manifest protocol is not claimed for these sessions.
Cancellation is public abort or EOF/Ctrl+C; no adoption/resume or PID signaling.

Pinned ABI/source: Delft3D 5a4649830b1e5072caf019fb4850bbdefd9ad431,
dflowfm_lib/src/unstruc_bmi.F90:233 initialize(char*),484 update(double by value),
507 finalize() return int;526-561 clock(double*);1167 get_var(char*,void**),
1428 set_var(char*,void*). Observation getter2321-2333 returns scalar valobs(S1).
2D weir getter2072-2085 uses 'crestlevel'; setter2610-2630 uses 'crest_level'.
The public name remains crest_level; the actual write uses the crestlevel getter
address, only with explicit transfer='dimr_address_scalar'. Pinned dimr.cpp:1509
maps dflowfm to COMP_TYPE_FM; receive:1108-1160 copies one double into get_var's
model-owned address. That is the selected transfer, not a fallback after set_var.
Pinned set_compound_field's network branch2620-2621 reassigns a local c_ptr;
it does not copy a double. No claim that this set_var path works is made.
Every write refreshes the address and is read back exactly. Transfer mechanism
and native target name are logged; pointers never leave the isolated worker.
getStructureIndex's network branch alone is NOT proof of active2D links. Native
link selection, applied crest/history, and RAW hydraulic response need independent
verification. The old#32 failed files/readback remain unchanged evidence.
get_var_units at884-889 is a stub, so units are source-backed declarations checked
against model/UGRID, not a fabricated native units query. Installed DLL hash and
source commit remain distinct. No model behavior or physical response is proven
until an independent native get/set/step/control comparison and cancellation gate.
"""
