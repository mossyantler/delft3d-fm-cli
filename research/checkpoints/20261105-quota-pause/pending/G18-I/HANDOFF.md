# G18 private implementation handoff

The complete approved standalone-section contract is implemented privately in
five additive modules. The held revision is `G18-TRANSFER-I-20261105-rev02`.
Root files were never edited. The package is composed from the exact accepted
root191/eedd payload, not an old CLI snapshot or the private B14 composition.

## Deliverable

- `src/dfm_cli/section_transfer.py`: public operation, preview consent, bounded
  result/receipt, parser registration and dispatch.
- `section_transfer_contract.py`: stable edit/publication policy identifiers,
  source/evidence scope, schema contract and contextual shared-service errors.
- `section_transfer_text.py`: strict entire-file ASCII physical-record parser,
  source-order selection, raw core/trivia spans and one-pass byte assembly.
- `section_transfer_graph.py`: role/path/external-source/output/ancestor/security
  binding around unchanged SectionInputs. No station or NetCDF decoder used.
- `section_transfer_write.py`: unchanged reviewed ACL import publisher adapter;
  exclusive new export with pinned parent, owned stage, late checks and honest
  commit/readback/cleanup receipts. Final exported names are never deleted on
  a postpublication error. Foreign target/stage identities are preserved.
- `integration.patch`: proposed registration/dispatch hooks in
  section_orientation.py and import/schema hook in cli.py. Apply semantic
  additions to the coordinator's eventual composition; never copy snapshot CLI.

The 196-file wheel has 189 root files unchanged. Only CLI/orientation glue and
five additive modules differ. All 98 existing commands, parameters and other
schema fields are exact; section export/import add two commands. G12 parser,
graph, contract and behavior remain unchanged.

Wheel SHA256:
`63e4b869d5afd9305f9239236dacaa5604aee883cbb0e873971bc319837b0a7e`.
The exact five-module, glue, test and wheel hashes are in hold.json and the final
freeze.json. candidate196.json pins every private package payload file.

## Operations

```text
dfm section export MODEL.mdu (--id FULL_ID repeat | --all) --out NEW.pli
dfm section import MODEL.mdu --source EXTERNAL.pli (--id FULL_ID repeat | --all)
    --mode append|replace-matching --coordinates model-xy-as-is
```

Preview is the default. Apply requires `--apply --expect-sha256 HASH` from the
same request, graph/source bytes and identities, security and intended plan.
Both selected and all modes admit the entire source/destination/result. Export
never overwrites. Import append inserts before file-owned footer; replace
preserves destination slots. Source cores retain exact header/count/XY/EOL
bytes; destination-owned trivia is exact. Bridges use the first destination EOL
and are disclosed with offsets/bytes/hash. Identical complete import bytes are
a full-recheck no-op with no staging or inode/mtime/metadata churn.

The coordinate declaration is a caller assertion. There is no CRS/unit/datum
conversion, mesh snapping, spatial validity or engine initialization. Policy
identifiers are consent-bound; operations never hash implementation .py files.
Raw descriptor bytes remain live publisher input only; the Windows consent
uses security.capture()['public'], not non-JSON ACL buffers.

## Reproduce portable checks

Use the clean installed interpreter, with the working directory in this private
folder (tests create fresh inherited-permission fixture directories there):

```powershell
Set-Location C:/Users/minyeop/project/delft3d-fm-cli/research/experiments/G18-TRANSFER-I-20261105-rev02
./venv/Scripts/python.exe -I -B ./test_section_transfer.py
```

The test module uses the installed public CLI registry, literal expected bytes,
ordinary inherited ACL fixtures, and actual writer functions for deterministic
publication faults. No in-memory registration or candidate import bootstrap is
used. The clean environment contains neither netCDF4 nor pyproj.

I checks: 25 portable tests (including 30 admission subcases), 24 unchanged G12
public regressions, all 33 frozen V admission fixtures replayed by I, seven
predeclared literal byte plans via subprocess CLI, full wheel/installed RECORD
identity and old-schema equality. release-check-01 retains argv/stdout/stderr.
The original 01 wheel and failed I fixture run remain unmodified.

Independent V acceptance is separately pinned in verification.json: 39 distinct
G18 tests, two external-parent identity controls, 24 copied G12 regressions,
33 admission subcases, actual ACL witnesses, no skips. V preserves its initial
harness failures and corrected fresh reruns without relabelling them. The G
installed f34 12-call receipt is supplemental file-only evidence.

## Integration and next native gate

There is no native/GUI approval in this handoff. The 63e4 wheel retains the
baseline runner. It is NOT a native-admissible substitute for the coordinator's
accepted common-short lifecycle composition, frozen owner/engine/inputs/oracle
and explicit lease. No run command was executed by this worker.

The separate `G18-TRANSFER-I-native-plan-20261105-01` folder contains six fresh
manual/public file pairs and a prospective plan: no-op roundtrip; append an
Entrance geometry copy under a new unique ID; replace Entrance with Boundary's
14 ordered vertices. All ten files match exactly within each pair. Its plan SHA
is `3a1b9aa59a9b6dfb7796376f6c92a57fb9cba51c051c1fdf29a5bccd78e895ec`.

That is a retained supplemental proposal, NOT a supersession of the separately
assigned G18-NATIVE-PLAN-V design. That worker reports the coordinator asked for
an eight-vertex Entrance reversal and a distinctive four-vertex append. Those
expect different native arrays and must never be merged. The independent plan
worker/coordinator owns final case selection and comparator freeze before any
lease; no G12 sign/numerical approval is inherited by either plan.

Future evidence must compare fresh public/manual complete NetCDF datasets and
raw masks/attributes, actual CF clocks through 600s, real geometry containers by
ID, unchanged map/restart state, and retained original-handle successful exits
plus empty owned Jobs. No production comparator is the numerical oracle. The
full limitations and proposed strict predicates are recorded in plan.json.

POSIX publication/ACL behavior is implemented with explicit fail-closed guards
but was not exercised on this Windows host. No global writer lock or filesystem
CAS is claimed; security scope is bounded as recorded in the schema/receipts.
