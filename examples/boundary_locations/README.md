# Candidate PLI location import

This file-level authoring candidate implements the policy described in D-Flow
FM User Manual 2026.02 §7.4.8.3, printed104/PDF130. It does not exercise the GUI,
modify a DeltaShell project database, initialize an engine or establish science.
The included PLI is an abstract XY example, not a georeferenced native fixture.

Coordinator registration only (the producer does not change the shared CLI):

```python
from dfm_cli import boundary_locations
boundary_locations.register(boundary_subparsers)
# Dispatch when args.action == "location-import":
result = boundary_locations.execute(args)
# Discover exact limits without optional dependencies:
description = boundary_locations.contract()
```

Candidate public commands, once registered by the coordinator:

```text
dfm boundary location-import MODEL.mdu --source CHANGED.pli --out NEW_COPY --coordinates as-is
dfm boundary location-import MODEL.mdu --source CHANGED.pli --out NEW_COPY --coordinates as-is --apply --expect-sha256 PREVIEW_INPUT_SHA256
```

The Python entry point is `location_import(mdu, source, out, *, coordinates,
source_crs=None, target_crs=None, source_unit=None, target_unit=None,
apply=False, expect_sha256=None) -> dict`.
Preview writes nothing. Apply requires the exact request/source/model-bound
fingerprint and a directory that does not yet exist, including an empty one.
Use a dedicated model input directory: the complete MDU-parent tree is copied,
including unknown ordinary files, empty directories and any preexisting outputs.
No result files are silently stripped. Maximum4096 files/directories and2GiB;
boundary metadata16MiB/file and64MiB total. All ordinary file bytes are hashed.
Links/junctions/hardlinks, escapes and unsupported dependency containers fail.
Clock, mesh, physics and model CRS/datum bytes are retained without interpreting
or validating them. This is a preservation-oriented working copy, not a claim
that every original model was valid or runnable.

Identity and signal policy:

- Matching exact basename **and** exact internal label replaces the coordinates
  and clears every attached `[Forcing]` block, including different quantities,
  multiple functions and whole-line QH names. The remaining shared BC and other
  line blocks retain their original bytes. Retired block slices are physically
  deleted from the ACTIVE BC, including their metadata/data/comment text; a
  byte-exact before-image of the ENTIRE original BC remains in the event archive.
- A new unique internal label adds a new unforced authoring geometry, even when
  the imported basename equals an existing line's basename. It never overwrites
  that other line. Existing label with a different basename, case-only aliases,
  shared ambiguous support IDs and non-boundary consumers are refused.
- V1 accepts one XY-only line per file,2..100000 points. A third text token is
  accepted only when it is the canonical `<label>_<row index padded to4digits>`
  support ID; it is preserved and validated. Multiple lines, numeric third
  columns and vertical columns are refused. Replacement splices count/coordinate tokens;
  target comments/other bytes remain. New geometry retains the entire source.
- Removed active EXT block lines receive the explicit comment prefix
  `# boundary-location-import removed: `. BC blocks are physically deleted,
  never commented at a numeric table's tail. All selected EXT bindings are retired.
  If this leaves only EXT `[General]`, the existing MDU `ExtForceFileNew` value
  is blanked; the audit EXT is retained **unreferenced**. No blank forcingFile,
  guessed quantity or empty invalid active EXT is authored.

The new line is deliberately **UNBOUND** in
`.dfm-boundary-locations/inventory.json`. Its relative geometry path is
`.dfm-boundary-locations/objects/<label>/<basename>`. It has
`"status":"unbound"` and `"engine_bindings":[]`. This sidecar is an explicit
authoring inventory, not a Shell `.dsproj` or hidden engine link. A replaced
line also becomes unbound. Surviving engine bindings are inventoried as observed
references, with no native validity claim. Provenance stores the raw source PLI
and every changed file's original bytes under
`.dfm-boundary-locations/imports/<input_sha256>/`; previous inventories are
archived when importing into a subsequent fresh copy. The complete output file
inventory excludes its own JSON file to avoid a circular hash; the result gives
the exact `inventory_sha256` separately.

The completion inventory is written last, after full source-byte revalidation
and output-byte checks. Exclusive creation and pinned directory handles prevent
replacement of an existing/foreign destination. On failure, a partial copy is
retained and named in the error; no recursive deletion or foreign-file cleanup
occurs. A partial folder is not a completed working copy and is never reused.

`as-is` performs no conversion, asserts no common source/model CRS or height
datum, rejects every CRS/unit flag and imports no optional geo packages.

`transform` is a distinct lazy call to the frozen read-only projection adapter.
All four declarations are required, with no defaults:

```text
dfm boundary location-import MODEL.mdu --source GEOGRAPHIC.pli --out NEW_COPY --coordinates transform --source-crs EPSG:4326 --target-crs EPSG:32631 --source-unit degree --target-unit m
```

Apply uses the same arguments plus `--apply --expect-sha256 PREVIEW_INPUT_SHA256`.
Units are exactly `degree` or `m`, never `metre`. Missing declarations or any
transform flag with as-is is a usage refusal before dependency/mesh work.
Transform execution needs optional netCDF4/numpy/pyproj; it does not install them.
The adapter verifies the actual contained MDU NetFile, one2D UGRID, scalar CRS
mapping linked by both X/Y, target EPSG/units and consistent CRS declarations.
Absent, unlinked, conflicting or unsupported mappings fail before writes. No
arbitrary pipeline, ballpark/network fallback, MDU projection/datum change,
mesh containment/snapping or native/GUI/science claim is introduced.

Public `projection` and `planned_inventory.projection` carry the full adapter
receipt, including original/projected source hashes, original MDU/NetFile
path/hash/identity, operation/runtime evidence and consent. Original incoming
PLI bytes always remain in `imports/<hash>/source/<basename>`; transformed
incoming bytes are separately in `projected-source/<basename>` and the receipt
is `projection.json`. Preview consensus binds all those inputs/provenance,
selected implementation hashes and actual planned changed output digests BEFORE
the stale check, including the BC retirement bytes. An old commented-retirement
preview cannot authorize different physical-deletion output.

Object `CRS` stays a string for legacy inventory compatibility. A transformed
object additionally has typed `CRS_evidence` binding its final geometry hash,
archived receipt and historical target-model fingerprints. Matching was verified
AT THAT TRANSFORMATION, not automatically reasserted for every later model edit.
Chaining preserves untouched objects' CRS metadata without geo imports. Changing
an object as-is clears its previous CRS assertion; a new transform issues fresh
evidence. Prior sidecars require the exact contract/kind/MDU and typed unique
objects with canonical case-exact POSIX relative paths before any file lookup.
Legacy as-is string records continue to chain normally.

Native counterexample `B04-PLI-G-east-contrast-02` showed a0.1816934645m error
despite all jobs returning0 when retired BC records were appended as comments
after active numeric data; swapping only BC to physical deletion removed that
delta. Historical commented-retirement outputs/evidence remain unchanged and
are not silently repaired by this release. New authoring uses exact physical
BC slice deletion in BOTH coordinate modes and retains original archives.

Portable author checks (synthetic mesh bytes, no native validity claim):

```powershell
.venv/Scripts/python.exe examples/boundary_locations/offline_checks.py
research/.venv/Scripts/python.exe -B examples/boundary_locations/check_projection_chaining.py
```

Independent verifier files and native/GUI gates belong to other owners. No
B04-EXPORT code, staging/pins, shared parser, schema or documentation is changed.
