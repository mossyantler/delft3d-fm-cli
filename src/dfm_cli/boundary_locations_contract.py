"""B04 PLI import authoring contract; no GUI or native execution evidence."""

CONTRACT = "boundary-location-import-v1"
INVENTORY = ".dfm-boundary-locations/inventory.json"
KIND = "unbound_boundary_geometry_authoring"
SOURCE = {
    "manual": "D-Flow FM User Manual 2026.02 revision 81168 section 7.4.8.3 printed104 / PDF130",
    "policy": "Same filename AND internal polyline name replaces geometry and deletes its forcing; new names add unforced geometry",
    "GUI_parity": "not established; file-level candidate implements an explicit bounded policy",
    "native_execution": "not performed",
}
LIMITS = [
    "One imported PLI line with two numeric columns and optional canonical label_NNNN support IDs; >=2 finite, normal-binary64-or-zero XY points; no vertical coordinate/datum conversion",
    "as-is imports no optional packages, declares no common CRS/height datum and refuses every CRS/unit flag",
    "transform requires all four explicit source/target EPSG and degree|m unit flags, optional geo dependencies and actual contained NetFile CRS/XY metadata validation",
    "Frozen read-only projection adapter changes numeric XY spans only; no MDU/mesh/datum modification or implied mesh containment/snapping/native validation",
    "Preview input_sha256 binds raw source, projected bytes, all target/model inputs, operation/runtime/implementation evidence, final changed bytes and provenance before stale comparison",
    "Original raw source is archived separately from projected-source and projection.json; no substitution of projected bytes for input provenance",
    "Transformed object CRS_evidence binds its final geometry/evidence bytes and historical model fingerprints; untouched chained records retain metadata; changed as-is geometry loses any prior CRS assertion",
    "Exact basename AND exact internal label replaces; a new internal label adds unbound geometry even with an existing basename; existing label/different basename or case aliases refused",
    "Existing engine-bound location files must each contain one line; multiple quantities may reference that line",
    "Every attached Forcing block across all quantities/functions is physically deleted by exact byte slice from active BC; native #130 rejected commented retirement as physically incorrect despite exit0",
    "Selected EXT Boundary blocks are deactivated; selected line becomes explicitly UNBOUND, never a fake active engine edge",
    "If EXT has no remaining non-General sections, blank the existing MDU ExtForceFileNew token; leave its audit file unreferenced",
    "Preserve every unselected BC block byte; archive complete original changed files including retired metadata/data/comments; only EXT retirement uses comment prefixes",
    "Shared BC consumers with ambiguous support/whole-line identities or non-boundary consumers are refused",
    "Copy the entire dedicated MDU-parent directory tree, including unknown ordinary files, without stripping existing outputs",
    "At most4096 ordinary files /2GiB source tree; no links, junctions, hardlinks, aliases or source/output overlap",
    "All supported active references must be contained; unsupported dependency containers and legacy EXT refused",
    "Fresh absent output required even for preview; preview writes nothing; apply requires exact input_sha256",
    "Publication uses exclusive file creation and owned directory handles; inventory is written last; failure leaves an explicit partial copy, never overwrites another writer",
    "Inventory is an authoring sidecar, not a DeltaShell .dsproj or engine binding; no GUI/project-database round trip or scientific validity claimed",
]
