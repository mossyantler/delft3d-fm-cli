# E007 portability I: offline guest transfer

This implementation prepares/exports a self-contained folder, checks a specifically
named disposable Windows guest/user, and collects/replays returned bytes read-only.
It does **not** start a VM, GUI, console, helper or engine. No native slot is used.
`run` exits 3 unconditionally; the unchanged Phase A guard is also active. There is
no allow flag, host-account exception, profile redirect or shared user settings.
No installed files, accounts, credentials, registry settings, services or network
configuration are changed. No VM inventory is required or attempted.

The shipped ten f34 files are actual Git blob bytes from
`DIMRset_2026.02`, commit `5a4649830b1e5072caf019fb4850bbdefd9ad431`, directory
`examples/dflowfm/01_dflowfm_sequential/dflowfm`. `payload/payload-lock.json`
retains each Git blob ID, SHA256, length and the unchanged runtime source paths.
No Git checkout, previous experiment, original host path or installation is needed
to inspect/replay a transferred bundle. Preparation changes only four MDU byte
spans: stop 600 s after start, history/map 60 s, restart 600 s. The independent
existing `preparation_bytes` scanner checks those edits; the existing fixture clock
and reference checks remain in use. Spatial metadata is inherited, not validated.

## Offline verification here

From the repository root (Python 3.12+, existing application venv with `run` extra):

```powershell
.venv/Scripts/python.exe -B research/assets/gui-guest-bridge/offline_checks.py --out research/assets/gui-guest-bridge/scratch/check-01
```

Use a fresh output name. Only this bridge's directories are written. The tests
block subprocess launch and real identity probes. Synthetic machine/SID/suite and
process evidence is explicitly test data. They exercise preparation, relocation,
guest refusal on host/wrong account, byte/suite/nonce/path tampering, unchanged
handshake and guard behavior, read-only collection/replay and real NetCDF parsing
of synthetic datasets with both unchanged verifiers. Missing netCDF4/numpy fails
this check rather than skipping the clock tests. `result.json` and `unittest.txt`
record the outcome. All scratch artifacts are ignored by the local `.gitignore`.

## Transfer procedure (explicit user commands, no launch)

The user must already have a **disposable Windows guest and independent disposable
user profile**, a separately installed suite matching the expected seven file
hashes, Python 3.12+ and, for output checks, netCDF4/numpy. Provisioning/installing
these is outside this tool. Do not use an existing host GUI, host account, shared
profile, mapped host directory or an existing calibrated project.

1. Manually transfer just `gui_guest_bridge.py` and `gui_guest_identity.py` from
   `research/workflows/replay/` together to the intended guest. There are no
   passwords or hardcoded account names. Explicitly run, in that guest/user:

   ```powershell
   python -B .\gui_guest_bridge.py identity --out .\guest-identity.json
   ```

   This reads the current process token SID, token profile, registered ProfileList
   path, OS known folders, local drive type, MachineGuid and raw SMBIOS system
   UUID/manufacturer/product. It launches no process and writes only the requested
   new JSON. Keep the printed canonical `identity_sha256`. Return the descriptor
   manually to the host through a trusted channel.

2. Write a JSON declaration, substituting that identity digest:

   ```json
   {
     "schema": 1,
     "purpose": "E007 disposable guest only",
     "disposable": true,
     "independent_profile": true,
     "shared_profiles_disabled": true,
     "target_identity_sha256": "<printed canonical identity_sha256>"
   }
   ```

   This is an operator declaration, **not** independent proof of disposability.
   The actual guest gate also requires distinct host/guest machine GUID, SMBIOS
   UUID and user SID, an ordinary user SID, local fixed-volume profile, agreeing
   token/registered/known profile paths and contained OS AppData paths. Supported
   firmware descriptions are narrowly Hyper-V, VMware, VirtualBox or QEMU; unknown
   or unavailable identity fails closed. Cloned/spoofed firmware and a malicious
   operator are not authenticated remotely by this offline protocol.

3. On the host, using the existing installed suite only as a read-only hash source:

   ```powershell
   .venv/Scripts/python.exe -B -m research.workflows.replay.gui_guest_bridge prepare --install '<selected-suite-root>' --target-identity '<returned-guest-identity.json>' --declaration '<declaration.json>' --out 'research/assets/gui-guest-bridge/scratch/export-01'
   ```

   Retain the printed `sha256` and nonce separately. Preparation reads host OS
   identity metadata; it never traverses the host's settings/profile files. The
   suite pin includes GUI EXE/config, Core/Utils, Dimr plugin and dimr/dflowfm DLLs.
   It is a static binary/config identity, not a full dependency closure, executed
   version probe or claim that installed binaries came from the source commit.

4. Manually copy the **whole** exported folder beneath the disposable guest's
   profile, outside its installed suite. Treat the directory as immutable. On
   the guest, explicitly invoke its bundled script (no repository needed):

   ```powershell
   python -B '<bundle>\scripts\gui_guest_bridge.py' inspect '<bundle>' --sha256 '<retained-bundle-sha256>'
   python -B '<bundle>\scripts\gui_guest_bridge.py' guest-check '<bundle>' --sha256 '<retained-bundle-sha256>' --install '<guest-suite-root>' --out '<guest-profile>\e007-<nonce>'
   ```

   Before executing any transferred script, compare its SHA256 using a trusted
   local hash tool against the source/bundle file hash retained separately. A
   script cannot authenticate its own replacement. The exported
   `scripts/offline_checks.py` also runs without the original checkout:
   `python -B '<bundle>\scripts\offline_checks.py' --out '<fresh-offline-check-folder>'`.

   `inspect` is completely offline. `guest-check` independently re-queries the
   live guest/token/profile; no `--identity` override or native-enable switch is
   available. It refuses the host, a different guest/account, redirected/reparse
   profile folders, nonmatching suite bytes and a reused evidence directory before
   writing any receipt. All seven suite paths are checked for containment/reparse
   points before static inspection. `guest-check.json` means identity check only:
   **native_ready remains false**. No host handshake or runtime proof is fabricated.

5. With this version, the returned folder contains only that identity receipt.
   Future independently produced raw runtime artifacts may be placed alongside
   it by an authorized controller. Retain raw protocol, invocation, samples,
   snapshots, blobs, diagnostics, generated MDU/XML and actual datasets. If a
   `normalized.json` is supplied, it must truthfully be `observed_runtime` with
   `trigger=gui_hosted_script`; synthetic/console evidence is refused. Do not fill
   gaps with invented events, altered outputs or direct-FM/DIMR substitutions.

   For the existing application output verifier, optionally retain
   `model-check.json` with exactly `{"schema":1,"nonce":"<bundle-nonce>",
   "mdu":"<relative-path-to-actual-GUI-generated.mdu>"}`. Replay checks the
   actual generated MDU clock/cadence and invokes unchanged
   `outputs.verify_outputs` on its actual output files. Absence is reported as
   unknown, a wrong clock/path/nonce or failed output check as failure. This
   locator does not certify GUI export or DIMR XML generation.

   Return the nonce-named evidence directory manually, then on the host:

   ```powershell
   .venv/Scripts/python.exe -B -m research.workflows.replay.gui_guest_bridge collect '<original-bundle>' --sha256 '<retained-bundle-sha256>' --evidence '<returned-parent>\e007-<nonce>' --out 'research/assets/gui-guest-bridge/scratch/collected-01'
   .venv/Scripts/python.exe -B -m research.workflows.replay.gui_guest_bridge replay 'research/assets/gui-guest-bridge/scratch/collected-01' --sha256 '<printed-collection-sha256>'
   ```

   `collect` preserves exact bytes in a new directory; `replay` does not write
   anything. Both source directories remain unchanged. Repeat replay safely after
   relocation. The bundle is included in the collection so the original host,
   checkout, suite and Python source tree need not exist. Keep the collection
   manifest digest separately. Hashes protect integrity against accidental or
   untrusted-transfer changes relative to that trusted digest; they are not digital
   signatures. The collector cannot authenticate a fabricated guest receipt.

## Containment and evidence contract

Bundle/collection manifests seal all file names, SHA256 and lengths. Missing,
extra, changed, case-colliding, nonportable or Windows device/ADS/traversal paths,
symlinks/junctions/reparse points and hardlinked files fail. Files are bounded at
256 MiB each, 1 GiB total and 10,000 files. Concurrent mutation is an error, not a
repair request. Destinations must be new and disjoint from their sources; failed
partial exports are retained for diagnosis. JSON duplicate keys/nonfinite values
are refused. Offline replay never probes local identities, follows recorded guest
absolute paths or executes imported scripts' CLIs. The data folders must be
quiescent, not concurrently writable by an adversary; this is not a kernel sandbox
against path-swap races. Empty directory metadata/ACLs are not transferred.

The nonce binds bundle, explicit guest target, guest evidence leaf, receipt and
collection. The future host protocol still needs its separate PID+birth/exact-Job
challenge and one-use gates. This transfer nonce is not a replacement Job proof.
Normalized retained artifact paths are checked again before invoking the existing
independent verifier. Receipt-only replay reports `transport_integrity=passed`,
`runtime_acceptance=unknown`; a normalized failure is retained as failure and exit
4. Success exit 0 means offline/transfer checks only, never native acceptance.
Invalid input exits 2, refused `run` exits 3; no interactive prompts exist.

### Producer receipt repair freeze

The original producer accepted malformed retained claims at collection: receipt
timestamps before preparation, UNC/device suite roots, and overlapping recorded
suite/bundle/evidence roots. The repair is producer-only; the independent Raman
verifier and byte-frozen Phase A/payload are unchanged. Historical exports and
`offline-verification.json` remain historical evidence, not the repaired version.
Use a fresh export after this repair; its manifest pins the updated scripts.

Every receipt now requires an explicit timezone and
`bundle.created_at_utc <= receipt.at_utc <= collection.at_utc`. Collection checks
against the actual collector clock before creating output, then checks copied
bytes again. Replay uses sealed historical times and does not require the guest
or current host clock. If optional runtime evidence is present, its interval must
start after the receipt and end before collection. Clock disagreement is refused,
never corrected by relabelling retained timestamps; real guest/host clocks must
already agree on UTC.

All three recorded guest roots must be explicit local Windows drive paths.
UNC, extended/device paths, drive-relative paths, traversal, ADS, device names and
ambiguous trailing dots/spaces fail lexical checks without touching those paths.
Suite, bundle and evidence must be pairwise disjoint, including equality,
ancestor/descendant paths and case-only aliases. The explicit guest check enforces
the same layout before suite inspection; UNC suite arguments fail before any
filesystem call. Collection and replay validate recorded guest paths purely as
Windows paths, without resolving them against the host filesystem.

`offline_checks.py` contains the collection and correctly resealed replay
regressions. The pre-fix run reproduced 36 accepting subcases across the three
findings. New results and hashes are recorded separately in
`producer-fix-freeze.json`; the old freeze is retained. A passing producer check
does not change independent acceptance: malformed collections and all runtime
claims remain subject to Raman's separate verifier and raw-runtime gate.

The repaired portable suite passed **37 tests** with subprocess, identity and
live Windows API tripwires active. `producer_fix_independent_checks.py` provides a
separate optional local audit against Raman's unmodified modules. It requires a
receipt-only test collection, its separately retained digest, the separately
retained Phase A `fixture.json` and digest, and that Phase A's original suite
available for static hash/length reads:

```powershell
.venv/Scripts/python.exe -B research/assets/gui-guest-bridge/producer_fix_independent_checks.py --collection '<receipt-only-test-collection>' --collection-sha256 '<retained-digest>' --phase-a '<independent-Phase-A-fixture.json>' --phase-a-sha256 '<retained-Phase-A-digest>' --out 'research/assets/gui-guest-bridge/scratch/independent-fresh'
```

It makes explicitly offline TEST copies and binds their suite hashes to the real
external Phase A, so an unrelated synthetic-suite mismatch cannot mask the
target rejection. The unchanged independent verifier accepted the offline
structural control (`runtime_acceptance=unknown`) and rejected seven negatives
with their expected chronology/path/runtime refusal codes. No live guest claim
is created or accepted. This audit tool needs the repository's independent
modules and local evidence; it is separate from the self-contained export.

## What a real run still requires

There is **no guest GUI controller** in this delivery. A validated disposable
profile does not override the existing host's stricter path guard: its actual
PortableSettingsProvider path and separate .NET local/roaming configuration paths
must all be below the allocated root. A future reviewed controller must establish
that layout before startup (e.g. a deliberately allocated whole disposable guest
profile with private subfolders, independently reviewed), without editing installed
configurations or weakening the existing guard. Merely placing this bundle inside
the guest profile or setting environment variables does not satisfy that gate.

An actual GUI run additionally requires a fresh explicit user-run command, a
demonstrably distinct disposable guest/user, an allocated GUI slot, suspended
launch assigned before resume to a retained kill-on-close non-breakaway OwnedJob,
the **unchanged** `arm_owned_host` / `validate_handshake` / host.py protocol,
pre-Run snapshots, **unchanged** `sample_owned_processes`, confirmed member exits
and empty-Job cleanup, and bounded handshake/Run/total time. Never attach to an
existing GUI or terminate by recorded PID/name. Preserve the native evidence
requirements in the frozen `gui-activity-trace/README.md`.

The exact existing `outputs.verify_outputs` and independent `verify_gui_trace`
are shipped and exercised, not replaced by a weakened clock checker. A raw runtime
adapter for Job, handshake, sampling completeness and cleanup remains pending in
that independent verifier: even complete normalized runtime data remains unknown.
Sampling can miss short-lived helpers; missing observations never prove absence.

E007/R01 is still **GUI-hosted Application.RunActivity**, not an actual Run button
click. No helper identity, rendered R04 progress, R05 Stop/cancel/controller-loss,
E014 property/export mapping or P08 DIMR-configuration exporter is verified here.
No GUI execution parity, source-build identity, scientific validation or live
guest result is claimed. This delivery is the concrete portable transfer and
offline evidence path only, separate from native work.
