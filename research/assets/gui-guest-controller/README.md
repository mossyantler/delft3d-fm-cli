# E007-GUEST-CONTROLLER-I

This is a separate guest controller, not an edit to Phase A or the transfer.
It contains an executable prelaunch proof API, split suspended Windows launch,
one-use challenge protocol, bounded ownership state machine and raw collection.
Development uses injected fake process/kernel boundaries only. No GUI, VM,
native helper, account, installed file or Windows setting is changed or launched.
Raman's verifier and raw-runtime acceptance adapter remain independent.

**Production is fail-closed in this freeze.** `ADMITTED_RESOLVERS` is empty.
No currently reviewed, side-effect-free mechanism resolves the actual GUI's
portable config, real .NET local/roaming config and log directory before its
entrypoint runs. A JSON assertion, environment variables, signed statements from
an arbitrary caller key, a GUI script after startup, or a surrogate executable
cannot enable the controller. There is no admission/test/bypass CLI flag.
The runner is implemented and tested behind that gate; this is not native E007
acceptance and it does not establish that all possible guest configurations are
physically impossible.

## Files and proof boundary

- `gui_guest_controller.py`: plan/pack/challenge/run commands, allocation,
  state machine, snapshots, append-only journal and raw evidence manifest.
- `gui_guest_controller_proof.py`: frozen dependency loader, exact binding,
  expiring challenge, RSA-PKCS1-v1_5 SHA256 signature validation and startup paths.
- `gui_guest_controller_windows.py`: retained process/Job boundary. No automatic
  process creation on import; only a validated run can instantiate it.
- `source-evidence.json`: source/decompilation artifact hashes and scope. Existing
  raw decompilation stays in ignored evidence and is not copied here.
- `test-rsa-key.json`: PUBLIC synthetic fixture, including its intentionally
  public private exponent. It is not an operational credential or admitted key.
- `offline_checks.py`: portable fake-boundary tests; optional NetCDF packages
  already in the application venv are used only by the unchanged frozen parser.

Bindings include the named guest token/registered/known-folder/firmware descriptor,
frozen transfer manifest hash and nonce, exact suite file signature, actual
Framework assembly file hashes, allocation/evidence/install paths and the hashes
of all three controller modules. `signature` means the resolver's cryptographic
signature on those facts, not an assertion of Authenticode trust or scientific
validation. Suite identity remains the exact seven-file transfer pin, not a full
plugin dependency closure or a claimed source revision of installed binaries.

A challenge has a fresh 256-bit nonce and at most 300 seconds validity (default
180). A proof signs its complete SHA256 and exact real-entry-context statement.
The production authority/installation/resolver/Framework policy must be admitted
in source after independent review and a new freeze. The CLI accepts neither a
key path nor a policy file. A test authority is passed only to the pure Python
proof API in offline tests, never through `run`.

The admitted resolver statement must contain:

```json
{
  "statement": {
    "schema": 1,
    "kind": "E007_exact_prestartup_paths",
    "challenge_sha256": "<fresh complete challenge SHA256>",
    "context": {
      "entry_executable": "<selected installed GUI EXE>",
      "application_config": "<that unchanged EXE.config>",
      "resolution": "real_entry_assembly_and_appdomain_before_target_entrypoint",
      "resolver_sha256": "<independently reviewed resolver>",
      "framework_sha256": "<fingerprint of the actually selected Framework files>",
      "suite_signature": "<challenge's suite signature>",
      "settings_written": false,
      "target_entrypoint_executed": false,
      "clickonce": false
    },
    "paths": {
      "temp": "<allocated profile>/temp",
      "settings": "<actual Application.GetUserSettingsDirectoryPath>",
      "portable_user_config": "<actual PortableSettingsProvider.SettingsFileName>",
      "core_user_config_local": "<actual OpenExeConfiguration(PerUserRoamingAndLocal).FilePath>",
      "core_user_config_roaming": "<actual OpenExeConfiguration(PerUserRoaming).FilePath>",
      "log_directory": "<actual converter output and prune directory>"
    }
  },
  "authority": "<source-admitted authority>",
  "signature": "<fixed-width RSA signature hex over canonical statement JSON>"
}
```

Config paths must be three distinct `user.config` files in their actual OS known
folders; logs/settings must be beneath actual LocalAppData. All writes must be
strict descendants of the allocated root. AppData/profile-wide retention,
UNC/device/ADS paths, aliases, overlap with input/protocol/evidence and existing
GUI config/log files are refused. No host profile is traversed before an actual
probe proves the named guest differs from the origin in machine GUID, firmware
UUID and ordinary user SID. A self-labelled VM/profile JSON is not live proof.

## Exact isolated configuration contract

This is a reproducible allocation/preflight procedure for an already provisioned,
user-owned disposable guest. Provisioning or identity creation is external and
is not performed by these scripts.

1. Use the independently provisioned named disposable guest and user whose live
   descriptor is already bound in a newly exported frozen transfer. Keep its
   default token profile, registry ProfileList, LocalAppData and Roaming AppData
   mutually consistent, local/fixed and free of redirection/reparse points. Use
   no shared host folders or reused GUI profile. Do not change known-folder or
   installed EXE/config settings to make this test pass.
2. Allocate **the entire disposable profile** as `DFM_E007_ROOT`. A nested scratch
   directory cannot contain the normal known-folder settings used before script
   injection. This allocation does not weaken `host.py`: the exact same root
   containment check is used. It does mean the profile is dedicated to this one
   owned attempt, and it must never be an existing host/user profile.
3. Put the unchanged transfer below that profile; install the matching suite
   outside it. Keep `protocol`, `project`, `working`, `temp`, `settings`, `logs`,
   `snapshots`, `blobs`, `input`, `harness` and `fixture.json` absent at profile
   top level. Windows' normal profile scaffold can exist; the exact GUI settings
   and log targets must be absent or empty. There is no cleanup/adoption of old
   data. Evidence is a new `e007-controller-<fresh nonce>` profile subdirectory.
4. Select the actual Framework folder containing `mscorlib.dll`, `System.dll`
   and `System.Configuration.dll`. Preflight hashes them without executing them.
   An admitted resolver must independently prove that this is the real GUI's CLR
   and AppDomain context; simply pointing to a folder is insufficient.
5. Run the offline `plan`, then explicit guest-only `challenge`. Obtain an exact
   startup statement using a separately reviewed side-effect-free resolver in
   the real entry context. **That resolver is the remaining external requirement;
   no valid implementation/key is admitted in this version.** A new reviewed
   controller policy/freeze is required before the explicit `run` command can
   proceed. No invented path, copied prior GUI trace, transplanted settings,
   temporary profile override or surrogate .NET probe substitutes for this step.

The whole-profile contract solves the broad containment geometry without Windows
settings edits. It does not manufacture exact prelaunch provider paths. The
installed SettingsHelper uses LocalAppData plus identity/assembly-location hash;
GUI Settings assigns its portable filename in its constructor and can save
immediately (`GuiSettings.cs` 334–358). The log converter creates/selects that
directory and prunes old logs (`DeltaShellUserDataFolderConverter.cs` 11–31).
Core Settings independently derives from ApplicationSettingsBase. These are
static findings pinned in `source-evidence.json`, not observed startup results.

Microsoft's [ClientConfigPaths reference source](https://github.com/microsoft/referencesource/blob/main/System.Configuration/System/Configuration/ClientConfigPaths.cs)
uses the real entry assembly/AppDomain and evidence-dependent suffix. Its explicit
EXE-path branch exits before constructing per-user paths (lines 131–137); a helper
EXE's own configuration paths are not the GUI's. That reference source alone does
not identify the installed .NET binary. No supported pre-start profile/config
switch was found in the inspected installed parser. Consequently this freeze
reports the exact-path gate unavailable before any production process creation.

## Commands

From the repo root, using a fresh check output name:

```powershell
.venv/Scripts/python.exe -B research/assets/gui-guest-controller/offline_checks.py --out research/assets/gui-guest-controller/scratch/check-01
```

Create a deployable controller sidecar. The original transfer is copied byte for
byte and its manifest digest is unchanged:

```powershell
.venv/Scripts/python.exe -B -m research.workflows.replay.gui_guest_controller pack --bundle '<frozen-transfer>' --sha256 '<retained-transfer-digest>' --out 'research/assets/gui-guest-controller/scratch/package-01'
```

Offline plan, requiring no guest/profile/installed-suite traversal:

```powershell
python -B '<package>/scripts/gui_guest_controller.py' plan --bundle '<package>/transfer' --sha256 '<retained-transfer-digest>' --install '<guest-suite>' --allocation-root '<bound-guest-profile>' --evidence-root '<guest-profile>/e007-controller-proposed' --out '<fresh-plan.json>'
```

`plan` returns a useful blocked report and exact binding candidate, never a
launch permit. The bundle must be at its intended guest location for the path
contract; an arbitrary host-side package path cannot be claimed as a guest path.

Explicit commands on the named disposable guest only (no commands run here):

```powershell
python -B '<package>/scripts/gui_guest_controller.py' challenge --bundle '<package>/transfer' --sha256 '<retained-transfer-digest>' --install '<guest-suite>' --framework-root '<real-Framework-folder>' --allocation-root '<bound-guest-profile>' --out-parent '<bound-guest-profile>'
python -B '<package>/scripts/gui_guest_controller.py' run '<printed-evidence-root>' --bundle '<package>/transfer' --sha256 '<retained-transfer-digest>' --install '<guest-suite>' --framework-root '<real-Framework-folder>' --startup-proof '<signed-proof.json>' --proof-sha256 '<separate-proof-digest>'
```

In this freeze the latter refuses `startup_resolver_not_admitted`, even with a
valid test signature, before a Job or process exists. Keep all transferred
script/package hashes through a separate trusted channel before executing them.
No UI/VM management or existing-window automation is implemented.

## Owned execution and raw evidence

After an admitted proof, a second live identity/suite/Framework/proof-lifetime
check occurs immediately before Job creation. Launch uses the exact installed
GUI argv `--skip-default-libs --run-file <copied frozen host.py>`, closed stdin,
closed unrelated handles, private working directory and child-only environment.
Known-folder environment values mirror the actual guest values; they are not a
Windows folder relocation. The fresh transfer nonce and per-attempt nonce remain
separate. The latter is bound to a newly retained PID/birth/exact Job challenge.

The root is created suspended, assigned to an unnamed non-inheritable
kill-on-close Job with no breakaway, rechecked through its retained handle, armed
using unchanged `arm_owned_host`, and only then resumed. Assignment failure kills
only that unassigned retained suspended root. Thread identity is checked before
resume. The exact frozen `validate_handshake` and `sample_owned_processes` are
reused. Actual startup paths must additionally equal the signed prelaunch paths.
Project/save/clock paths must be proven before the pre-Run snapshot and run-go.

Waits are bounded at 15 s handshake, 15 s project, 90 s Run and 120 s total;
after a valid Done result, natural shell exit gets at most five seconds within
the remaining total budget. This wait uses the retained launch handle, a
signalled `WaitForSingleObject`, `GetExitCodeProcess` and the same creation
identity; it never opens a recorded PID. Nonzero natural exit remains a failure
even after a valid Done callback. A running handle, failed wait, unconfirmed
zero, wrong creation identity or PID-only exit source cannot prove success.
cleanup has a separate at-most-10-second retained-handle/empty-Job check. Timeout,
interruption and errors terminate only this Job. Missing PID, root exit, empty
sampling or a returned activity are never cleanup/completion proof. Failed member
confirmations, leftover Job members or errors remain `cleanup_failed`, even if
closing the Job later kills them. No Stop API or arbitrary PID kill is used.

Raw output includes signed prelaunch proof and challenge, invocation,
append-only observations with all unknown queries, frozen host protocol, snapshots
`prelaunch/pre-run/post-run/terminal`, content-addressed retained bytes, private
input/project/work/temp/log copies, cleanup, controller result and a sealed file
inventory. Missing startup directories are explicit in snapshots. Partial files
survive failures. Journal is bounded at 64 MiB/2048 samples and copies inherit the
frozen 256 MiB per-file/1 GiB/10,000-file bounds. One attempt reserves a permanent
`launch.lock` and fresh operation paths; there is no resume/adoption/reuse.

`activity_state=host_returned_done` describes the API result only. The terminal
controller state is `shell_exited_zero` only after a confirmed natural zero exit;
`shell_still_running` is an unsuccessful bounded wait with a still-running
retained handle. Nonzero natural exit gives `failed/shell_exit_nonzero`, and an
unavailable exit observation gives `failed/shell_exit_unavailable`. `shell_exit`
is captured before cleanup and is never replaced by a forced termination code.
Native cleanup separately retains `root_before_cleanup`, `root_after_cleanup`,
`root_exit_was_natural` and `root_termination_requested`: forcing a leftover
helper Job does not turn an already natural root exit into a forced one.
No normalized runtime events
or output datasets are synthesized. Sampling can miss short-lived helpers; this
controller does not claim complete process/file syscall coverage. Raman's current
transfer verifier still rejects runtime files, and its raw-runtime adapter and
independent generated-MDU/XML/NetCDF verification remain external. Run button
click, rendered R04 clock, R05 Stop/cancel/controller loss, E014 and P08 are not
verified by this script-run controller. Scientific validation is not performed.

## G preflight correction

The first 35-test fake-kernel run exposed a raw `ValueError` escaping from the
frozen transfer's Windows-path parser. The owned proof API now translates that
exception to `Refusal(code="startup_paths")` and preserves its diagnostic text
and exception cause. The frozen transfer parser is unchanged. Proof-level
containment, aliased config files, broad known-folder scope and incorrect TEMP
retain their distinct codes: `startup_path_escape`, `startup_config_alias`,
`startup_known_folder` and `startup_temp`. The negative tests assert these exact
codes on correctly signed TEST statements; they do not accept a generic error
or signature failure as a substitute. Validated permit paths are immutable so
their signature-bound values cannot change after validation. See `controller-freeze.json` for the
corrected source hashes and fresh offline result. No real launch was used.

## Full Raman audit repair

The independent `E007-CONTROLLER-V-offline-20261104-01` audit captured accepted
exit code 7 after a Done result, a resume after the 120-second budget, and a
`run-go` published after that budget. All 527 original files, including the
producer source snapshots, raw failure markers and manifests, remain unchanged.
`audit-repair-baseline.json` pins their hashes. The prior controller freeze is
archived byte-for-byte as `controller-freeze-v1.json`; `controller-freeze.json`
and the versioned `controller-audit-repair-freeze.json` publish the new freeze.

The owner now checks the total monotonic deadline and signed challenge lifetime
before Job creation, suspended creation/assignment, arming, resume and every
irreversible go. The native boundary checks again after thread/handle queries
immediately before `ResumeThread`. Go JSON is prepared under a pending name,
checked again after owner queries and file preparation, then atomically renamed
into the permission filename. Expired pending bytes remain raw evidence, not
permission. Blocking OS/file operations cannot be made hard real-time by these
checks; checks occur at their documented call/commit boundaries.

The pure boundary API now requires `wait_exit(timeout)` returning
`state`, `wait_confirmed`, `returncode`, `identity` and
`source=retained_launched_process_handle`. The frozen host is unchanged. Tests
use a scripted retained-root object or fake Win32 calls; no actual Windows wait,
process or guest is exercised. A missing wait contract fails closed. Cleanup
is not a substitute for natural exit evidence, and `cleanup_failed` remains
separate from the operation state that preceded it.

The repaired portable suite passed **51 tests**. Three genuine regression tests
were first run against the old source and reproduced all three findings. The
producer-owned `audit_repair_replay.py` also passed Raman's current **19 fixture
scenarios**, including proof expiry during suspended creation and invalid exit
witnesses, using the independent fixture's own `wait_exit` implementation. This
is a producer replay of independent test inputs, not independent acceptance.

```powershell
.venv/Scripts/python.exe -B research/assets/gui-guest-controller/offline_checks.py --out research/assets/gui-guest-controller/scratch/audit-fixed-fresh
.venv/Scripts/python.exe -B research/assets/gui-guest-controller/audit_repair_replay.py --out research/assets/gui-guest-controller/scratch/audit-replay-fresh
```

Both use fresh output directories. The second command requires the separately
retained original audit and Raman's repository fixture; it never edits either.
Real startup resolution/admission, native OS behavior and the independent raw
runtime adapter remain external requirements. Production admission stays empty;
there is no bypass, GUI/VM launch or Windows user-state change in this repair.
