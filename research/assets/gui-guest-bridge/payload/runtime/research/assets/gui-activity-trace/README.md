# E007/R01 harness v1 — Phase A

This is a research harness for **GUI-hosted script Run**, not an interactive Run
button test. Phase A cannot launch a GUI, console host, engine, or launcher. MPI
product files and shared documentation are untouched.

## Public Phase A commands

From the repository root, with the application venv:

```powershell
.venv/Scripts/python.exe -B -m research.workflows.replay.trace_gui_activity prepare --install '<suite-root>' --out 'research/experiments/<fresh-E007-folder>'
.venv/Scripts/python.exe -B -m research.workflows.replay.trace_gui_activity preflight 'research/experiments/<fresh-E007-folder>'
.venv/Scripts/python.exe -B research/assets/gui-activity-trace/offline_checks.py --fixture 'research/experiments/<fresh-E007-folder>' --out 'research/experiments/<fresh-offline-check-folder>'
```

`prepare` only materializes the ten official f34 files from locked Git blobs and copies harness assets,
shortens its stop to 600 s, and sets history/map cadence to 60 s and restart to
600 s. It never accepts an arbitrary model. Original bytes, source pin and hashes
are retained. CRS/datum and all non-target model values are inherited explicitly,
not newly validated. A fresh destination below `research/experiments` is required;
reparse points, symlinks and nested source/destination paths are refused.

`preflight` re-reads hashes, fixture references, clock, asset syntax and selected
installation/configuration. JSON records `phase_a_checks_passed` separately from
`native_ready: false`. Exit 0 means offline preparation passed; 2 means invalid
preparation; 3 is a refused native operation. `run` always exits 3 in v1. There is
no bypass flag, coordinator token, service installation or firewall prompt.

## Current isolation blocker

Installed `DeltaShell.Gui.exe.config` uses
`DeltaShellUserDataFolderConverter` for its log path. Static inspection of that
converter and `DelftTools.Utils.SettingsHelper` shows startup obtains
`Environment.SpecialFolder.LocalApplicationData`, creates a settings directory,
and removes old `*.log` files there. GUI startup also accesses `Settings.Default`
before `--run-file` dispatch. Setting TEMP/TMP/APPDATA/LOCALAPPDATA alone is **not
proof of relocation** of Windows known folders or .NET user configuration.
The existing installation therefore fails the pre-launch isolation gate. No GUI
was launched to test this. A supported, independently reviewed private startup
settings/logging route must be established before enabling the native controller.
No installed file, registry value, user setting or existing GUI is modified.

### Alternate isolation review

The live GUI gate is **unavailable**, rather than hypothetically accepted:

| Candidate | Confirmed basis | Remaining blocker |
| --- | --- | --- |
| Identical EXE in private appbase with copied `.exe.config` | Standard adjacent config can describe a different log4net FileAppender; installed XML shows that interface | EXE/config copy alone does not redirect SettingsHelper's LocalApplicationData root. Loading original `DelftTools.Utils.dll` retains its original location hash. Private dependency/plugin closure and every settings consumer remain unverified. No relocated GUI was launched. |
| Pre-start log redirection | log4net supports a literal `<file value="private-path"/>`; replacing the copied config's entire PatternString removes that converter invocation | This only addresses that log appender/prune path; it does not redirect GUI/core user settings or prove all startup side effects contained. No installed config was edited. |
| GUI per-user Settings path | Actual GUI class has `[SettingsProvider(typeof(PortableSettingsProvider))]`; its constructor assigns `SettingsHelper.GetApplicationLocalUserSettingsDirectory()/user.config` and may Save immediately | It is not merely .NET's default user.config path. PortableSettingsProvider has a public static filename setter, but the constructor overwrites it before script injection. No pre-start path/profile option found in the installed parser or collected manuals. Core Settings independently uses ApplicationSettingsBase's default provider. |
| Change appSettings identity fields | SettingsHelper reads applicationName/publicReleaseVersion/distributionName and builds a name plus assembly-location hash | Unique identity is not a supported folder redirect and still selects LocalApplicationData. Treating applicationName as an absolute path would exploit Path.Combine behavior, not establish a documented profile contract. Not attempted. |
| Existing Windows Sandbox/VM | Read-only local availability queries only | WindowsSandbox.exe, VirtualBox and VMware command locations were absent. Hyper-V cmdlets and running vmms were present, but Get-VM was denied by authorization policy. VM absence is **not** inferred; no accessible, pre-existing disposable guest was established. No VM was started or changed. |

Apache's [FileAppender documentation](https://logging.apache.org/log4net/manual/configuration/appenders/fileappender.html)
supports log-path configuration only; it does not establish Delta Shell profile
isolation. The installed parser exposes project/run/script/culture/app-setting
options, with no profile/config-path switch. Its app-setting application happens
after script dispatch, too late for startup. The historical 2007 Deltares user
settings note is not evidence for this installed provider/version.

Priority while blocked: (1) independently review the startup/settings findings and
offline handshake/snapshot checks; (2) keep R01 live and dependent R04 GUI display /
R05 Stop unavailable; (3) workers can continue independent offline verification,
E014 static property/export mapping and already isolated engine work assigned by
the coordinator. Reconsider E007 native allocation only when a supported private
profile route or an accessible, explicitly disposable existing guest is established.

## Native controller contract for the next allocated phase

`trace_gui_activity.py` provides reviewable building blocks, not an enabled native
controller. A later version must compose them only after the startup blocker is
resolved and an exclusive native GUI slot is allocated. Never launch this script
manually or through an existing GUI. Freeze/fingerprint that version before replay.

1. Fresh `OwnedJob`, kill-on-close, no breakaway; launch installed GUI suspended,
   assign before resume, closed stdin, closed unrelated handles, private cwd/env.
   Exact argv: `[<GUI>, '--skip-default-libs', '--run-file', <copied host.py>]`.
   A new nonce/root is in this child's environment only. No process/window search,
   COM attach, automation of existing windows, global WMI inventory or ETW driver.
2. `arm_owned_host(job, process, root, nonce)` binds the *retained launched process
   handle* to creation FILETIME and exact Job and records a one-use challenge.
   No Job handle is transferred or inherited; kill-on-owner-close must retain its
   meaning even while the GUI is still starting. The host checks PID/creation time
   before importing model APIs; its managed guard confirms self identity and that
   it is in a Job. Owner independently re-queries its retained launch handle's
   membership in the **exact** private Job and its limits at each protocol gate;
   the host's any-Job boolean alone is insufficient. A PID mismatch never closes any handle
   or project/window belonging to another process. An unconfirmed host times out;
   only the owner may stop its private Job.
3. Host sends `handshake.json`, including actual temp/settings/config paths. Owner
   independently checks identity, nonce and every path under the allocated root,
   including the actual PortableSettingsProvider filename and separate core .NET
   local/roaming configuration paths.
   No project operation is permitted before `project-go.json`. After private import
   and save, host sends `project-ready.json` with actual project/data/input/work
   paths and model times. Owner takes retained **pre-Run** file snapshots and
   confirms ownership again before `run-go.json`. A separate post-import baseline
   avoids attributing import/save/export files to Run.
4. Call exactly `Application.RunActivity(model)` once, record return, activity
   status and model CurrentTime/StopTime. Do not substitute a batch or direct
   native run, change the remote/local API factory, or call Stop during this case.
   A returned call alone is not completion proof. Unexpected asynchronous return,
   failed status or time mismatch fails closed. R04 display is only model API time;
   a rendered GUI clock and R05 interactive Stop remain separate experiments.
5. Target-only `sample_owned_processes` queries command line and modules through
   handles validated against this exact Job. Each sample has wall observation
   time, PID+creation FILETIME, raw command-line text and actual module paths/hashes.
   Windows raw command line is retained separately from `CommandLineToArgvW`
   parsing; parsed argv is not an inferred launch event. Keep cumulative samples,
   root and helper records, failed queries and timestamps. Root/child absence is
   never evidence that no helper existed. Sampling can miss short-lived helpers;
   missing argv/module/exit observations make the trace incomplete, not accepted.
   Use an owned Job completion-port event collector in the next version if needed
   to prove full helper coverage; it is not implemented in Phase A.
6. Retain before/after file *bytes* and hashes below private input, project,
   working, temp and settings roots, excluding the evidence directory itself.
   Capture at prelaunch, immediately pre-Run, post-Run and after confirmed shutdown.
   Record missing/locked/unreadable paths, never silently skip them. This is file
   state comparison, not a complete file-write syscall trace or an assertion of no
   writes outside the private roots. Do not hash/copy arbitrary host-user folders.
7. Re-read the GUI-generated MDU and DIMR XML and require contained references and
   the declared clock/output schedule. Use existing `outputs.verify_outputs` plus
   the independent verifier against actual history/map/final restart CF times.
   Retain GUI status time, engine diagnostics and CF time separately. No output
   synthesis/repair, no serial output substitution and no scientific acceptance.
8. Bounded handshake (15 s), Run (90 s), total (120 s). Ctrl+C/timeout/error only
   terminates the retained private Job; retain member handles, exit confirmation
   and empty-Job proof using `OwnedJob.terminate`. `cleanup_failed` is distinct.
   Exit code, missing PID, root exit or `Gui.MainWindow.Close()` alone is not tree
   cleanup. Do not close a GUI window until the exact handshake and private
   project are proven. Preserve partial artifacts and original failed evidence.

## Evidence interface for independent verification

Preparation: `fixture.json`, immutable `source-input/`, copied `input/`, copied
`harness/`, `preflight.json`. These are **offline** evidence, never runtime traces.
Planned runtime: `invocation.json`, append-only `observations.jsonl`,
`protocol/{challenge,handshake,project-go,project-ready,run-go,result}.json`,
`snapshots/{prelaunch,pre-run,post-run,terminal}.json`, content-addressed retained
bytes under `blobs/`, `cleanup.json`, generated MDU/XML, native logs and datasets.

Normalized verifier bundle v1 must be produced from retained raw evidence (no
invented events): `evidence_kind=observed_runtime`, `trigger=gui_hosted_script`,
`started_at_utc`, `ended_at_utc`, `launched_identity`, `before_processes=[]`
(scope **this new empty private Job**, not a machine-wide inventory), chronological
`observations` with owned process identities, raw/parsed argv and loaded modules,
`expected_native_modules` (installation path/hash), `before_files`/`after_files`
mapping relative private paths to `{artifact,sha256}`, `model_clock`
`{start,stop,history_interval_seconds:60,map_interval_seconds:60}`,
`output_files` for history/map/restart, and `operation` state/returncode. Keep the
handshake, Job identity and cleanup proof alongside it; bundle conversion must
not hide unknown ownership or incomplete helper capture. Verifier owns its adapter
and acceptance decisions; this producer does not label itself independently passed.

Future offline syntax, after actual evidence exists:

```powershell
.venv/Scripts/python.exe -B -m research.workflows.verification.verify_gui_trace '<native-evidence>/normalized.json' --out 'research/experiments/<fresh-independent-verification>'
```

Do not run that verifier on Phase A preparation as if a GUI activity had occurred.

## Basis and limits

- Documented: Delta Shell User Manual §4.2 printed pp.33–34, PDF pp.44–45,
  `Application.RunActivity(flow)` case-management example. Technical Reference
  Manual Figure 2.1 printed p.4, PDF p.13, lists RunActivity,
  RunActivityInBackground and StopActivity independently.
- Observed E001: `run_gui_export.py` and `gui_save_export.py` use fresh GUI
  `--skip-default-libs --run-file`, private import/save/export. E001 established
  script injection, not RunActivity, helper launch or interactive Run semantics.
- Static installed managed interfaces: `DimrRunner.ValidateExportAndInitialize`
  exports inputs, generates DIMR XML and calls factory/CreateNew; RemoteDimrApi
  uses RemoteInstanceContainer. These are candidate paths, not observed commands.
- Source fixture: `DIMRset_2026.02`, locked commit
  `5a4649830b1e5072caf019fb4850bbdefd9ad431`. Installed binary identities remain
  separate; never infer their source commit from the suite release name.

Unverified: native host/bootstrap and settings isolation, helper coverage and
remote transport, imported/exported model preservation, generated engine clocks,
native modules and results, cancellation/controller loss for GUI hosts, GUI button
click and rendered progress display. No E007/R01 acceptance is claimed by Phase A.
