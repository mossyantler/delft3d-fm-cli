# E007 RESOLVER-I: real file evidence, unresolved CLR paths

This additive resolver reads the actual pinned installed GUI, its helper
assemblies, the selected .NET Framework files and configuration. It never starts
the GUI or Console, loads a target assembly into the CLR, invokes a target
constructor/getter, changes a policy, creates Windows user state, or issues a
controller token. The frozen controller and production admission remain unchanged.

`scan` is genuinely file-only and side-effect-free with respect to the inspected
application/system. Its only writes are a new requested evidence directory.
`measure_guest` adds read-only Windows token/known-folder/DACL observations only
on the independently named disposable guest. It does not fill runtime-dependent
CLR paths with guesses. No real guest was provided or queried for this research.

## Actual evidence

The separately retained Phase A anchor is
`research/experiments/E007-I-phase-A-20261104-01/prepared-final/fixture.json`,
SHA256 `153ceae23316007a90ec9e75f680662d900967f2a49723a4eae69e98f1ca2a4b`.
All seven selected suite/config file hashes must match it **before parsing or
publishing evidence**. This is an explicit out-of-band byte/provenance anchor,
not a newly invented signing authority or an Authenticode verification.

The installed GUI has SHA256
`37ff0890bd729a534881782db00ced653ddc1049988f4c1b0e0afbe36b00b097`,
assembly version `3.0.0.4936`, MVID `7955b0fd-ea6c-47a3-a972-12326e2577fd`,
entry token `0x06000012`, and entry `DeltaShell.Gui.App::Main`. The separately
read Console has another file hash, MVID and entry token `0x0600000a`; using it
as a surrogate does not establish the GUI's entry context.

The GUI's actual TargetFrameworkAttribute is `.NETFramework,Version=v4.8`.
The unchanged EXE.config separately advertises supported runtime `v4.0` with
`sku=.NETFramework,Version=v4.6.1`. These are distinct observed fields, not
proof that the CLR will activate one particular installed Framework directory.

The local scan retains nine real managed images and 58 selected methods:
GUI, Utils, Core, log4net, Console and selected Framework mscorlib, System,
System.Configuration and Windows.Forms. Each includes SHA256, exact assembly
identity, MVID, CLI flags, entrypoint and relevant custom attributes/references.
Each method includes its metadata token/signature, RVA, PE-mapped file offsets,
IL length/hash and decoded instruction bytes/call tokens/string literals. No
operand-byte pattern search is used to invent calls. All selected CIL bytes can
be checked directly against the installed file without using this parser.

The selected System.Configuration.dll has MVID
`0bdd7b69-bfbb-4d92-b3c3-55dc2aa7669b` and SHA256
`e346f5d994fecaf847d7e675a96f6de82288ce471b008f4c7b579935a39ccb7a`.
Its actual ClientConfigPaths constructor, GetPaths, GetTypeAndHashSuffix,
GetEvidenceInfo and naming methods are decoded from those bytes, not replaced
by an online reference implementation. The selected native clr.dll and actual
machine.config are fingerprinted. App/machine binding redirects, codeBase,
publisherPolicy, runtime options and external configSource declarations are
retained as file evidence. Actual binding/GAC/publisher-policy activation remains
unproven; the report explicitly calls the Framework directory a selected candidate.

dnfile 0.18.0 and pefile 2024.8.26 are the existing research environment parsers.
Their actual source/package fingerprints are retained with the freeze. The
scan retains 42 parser diagnostics across these real images, including partial
string-heap warnings; it does not promote them into a proof of all metadata or
control-flow semantics. Raw installed-byte/IL reports stay in ignored local
`evidence-*` directories. `resolver-freeze.json` pins the reviewable summary and
actual report digest. No installed binaries or raw decompilation are vendored.

## What was resolved and what was not

The code resolves exact file and metadata identities and rejects malformed
Windows components. It derives a **conditional containment envelope** from the
actual Utils company attribute (`Deltares`) and configured application identity
(`Delft3D FM Suite`, `2026.02`, `OpenHMWQ`). If these components are valid, the log
converter's relative leaf is below `KNOWN(LocalApplicationData)/Deltares`.
The OS root, actual suffix and protection are not asserted by a static scan.
`NUL`, trailing dot/space, raw dot/dotdot, ADS, UNC/device and DOS device aliases
cannot be labelled safe relative components or absolute roots.

Exact absolute portable, local/roaming .NET and log paths remain **null**:

| Path | Actual calls/unknowns retained |
| --- | --- |
| Portable `user.config` | GUI Settings constructor assigns PortableSettingsProvider.SettingsFileName via SettingsHelper; initialization order determines the active identity. Default initialization's AssemblyUtils.GetExecutingAssemblyInfo calls **GetEntryAssembly**, with a separate UnitTestDetector branch. |
| Settings/log hash suffix | Utils token `0x060000e2` calls Path.GetFullPath, then the **System.Object.GetHashCode virtual slot** at IL offset 103 on that String receiver, then Math.Abs. The metadata token is preserved exactly; the report does not rewrite it to a String method token or evaluate Python/surrogate hashes. Actual CLR hash mode/value and actual Utils.Location remain unknown. |
| Log directory/files | Core converter initializes identity from configuration, calls the directory getter, enumerates `*.log` and deletes old files. Calling this converter or the directory getter would have side effects and is prohibited. Exact date-expanded log filename is runtime-dependent. |
| Core .NET local/roaming config | Actual ClientConfigPaths reads the real entry assembly, AppDomain SetupInformation/ConfigurationFile, FriendlyName, CodeBase and StrongName/Url/Path evidence; its suffix involves BinaryFormatter serialization. ClickOnce/data-directory state and actual binding must also be established. |
| Protected roots | Exact Windows known folders and ACLs must be measured under the named guest token. Declared strings supplied to the pure function are explicitly unobserved; they never establish protection or a real entry context. |

The static report never claims that the app's full writable startup surface is
closed. The precise remaining requirement is a separately verified resolution of
those real-entry/AppDomain/evidence/hash/binding values before any target startup
side effect, followed by guest OS known-folder/ACL evidence. Existing controller
requirements cannot be satisfied by this partial report, a self-signed statement,
a caller `real_entry_context=true`, copied context from Console, or a mock list.

## API and commands

`I_V_CONTRACT.json` and `I_V_STATUS.json` provide exact additive I/V interfaces
and the current file receipt. Independent tests live outside this owner's files.

```powershell
# File-only actual installed scan. Use a fresh output directory.
research/.venv/Scripts/python.exe -B -m research.workflows.replay.gui_entry_resolver --install '<suite-root>' --framework-root '<selected-Framework-root>' --anchor research/experiments/E007-I-phase-A-20261104-01/prepared-final/fixture.json --anchor-sha256 153ceae23316007a90ec9e75f680662d900967f2a49723a4eae69e98f1ca2a4b --out research/assets/gui-entry-resolver/evidence-fresh

# Recheck actual files, method bytes and genuine negative cases; blocks process,
# CLR and Windows API entry points in the test process.
research/.venv/Scripts/python.exe -B research/assets/gui-entry-resolver/offline_checks.py --report '<evidence>/file-evidence.json' --out research/assets/gui-entry-resolver/scratch/check-fresh

# Export the new code plus a byte-identical frozen full transfer validator.
research/.venv/Scripts/python.exe -B -m research.workflows.replay.gui_entry_resolver_pack --out research/assets/gui-entry-resolver/deploy-fresh
```

The read-only package contains no suite/Framework/profile files. A disposable
guest needs Python and the pinned parsing libraries already provisioned by its
owner; this tool installs nothing. Preserve its package digest through a trusted
channel before running it. The transfer-validation dependency is the **unchanged**
controller proof module SHA256
`44dbc308c387c652e24f7f51044478f5781b9acbeb31c501406b2b942585e3b4`.
It is used only for the full frozen `inspect_transfer` chain, not for admission.

Guest-only OS measurement (not run on this shared host):

```powershell
python -B '<package>/scripts/gui_entry_resolver_windows.py' --transfer '<frozen-transfer>' --transfer-sha256 '<separate-digest>' --report '<guest-local-file-evidence.json>' --report-sha256 '<separate-digest>' --allocation-root '<actual-independent-profile>' --out '<fresh-observation.json>'
```

Before **any** identity/profile/ACL query, the full frozen transfer chain checks
code hashes, schema, source pin, nonce, declaration, inventories, payload, clock
and harness. Minimal or corrupt transfer JSON cannot reach probe(). Then the
actual token SID, firmware/machine GUID and known folders must match the target
and differ from the origin. Known folders must be local and free of reparse
points. The actual file report is rechecked against all real image metadata/IL,
configuration and CLR hashes. No supplied context flag replaces any check.

DACL reads use GetNamedSecurityInfoW/GetAce without changes. Writable grants to
other principals, null DACLs and unsupported object/callback ACEs fail closed.
The explicit trust scope is the actual user, SYSTEM and Administrators; this is
not isolation from those trusted principals or a kernel sandbox. Parent-folder
ACL evidence does not assert exact unknown child filenames or prevent later
administrator/path-swap changes. No settings directory is created, no existing
profile contents or logs are enumerated, and destructive getters are never called.

## Primary semantics references

- [Microsoft ClientConfigPaths](https://github.com/microsoft/referencesource/blob/main/System.Configuration/System/Configuration/ClientConfigPaths.cs): context and suffix mechanism; actual installed IL remains the byte authority here.
- [Microsoft string hashing policy](https://learn.microsoft.com/en-us/dotnet/framework/configure-apps/file-schema/runtime/userandomizedstringhashalgorithm-element): per-AppDomain hashing can be configured; no surrogate hash is accepted.
- [Microsoft assembly binding](https://learn.microsoft.com/en-us/dotnet/framework/deployment/how-the-runtime-locates-assemblies): app, publisher and machine policy are separate from merely selecting files.
- [Microsoft known-folder API](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath): token-specific OS roots; the helper uses the read-only legacy wrapper without create flags.

These documentation/reference claims are kept separate from observed file bytes,
inferences, unobserved guest OS metadata and actual runtime behavior. No new
signing key, fabricated token, authority admission or production policy is created.
