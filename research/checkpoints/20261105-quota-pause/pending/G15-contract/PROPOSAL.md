# G15 standalone structure interchange — source/file/CLI proposal

Status: **revision02 proposal for independent V and G decision, not implemented or approved**.
This revision replaces01 only at the two admission clarifications in
ADDENDUM.md. Frozen01 and all its source/fixture evidence remain unchanged.
No GUI, engine, package build or product edit was performed. The source pin is
`5a4649830b1e5072caf019fb4850bbdefd9ad431`; the installed engine's matching
source revision is unknown. All line references below refer to that pin, not an
assumed suite-to-source identity. The source blobs and numbered excerpts are
hashed in source-evidence.json and source-evidence-additions.json.

## 1. What G15 actually includes

M0 G15 describes project-tree operations, not full-model export. UM 2026.02,
revision81168 DRAFT, §7.4.2.8–11, printed81–84/PDF107–110 documents:

| GUI family | Documented incoming formats | Documented outgoing formats | What is NOT established |
|---|---|---|---|
| Pumps | PLI(Z), Shapefile | PLI(Z), Shapefile | Actual Z/DBF field meanings, property/forcing retention, collision/save behavior |
| Adjustable weirs | Polygon PLI or structure file | Polygon, structure-data file, Shapefile | Which native format/version and attributes the standalone exporter writes |
| Gates/sluices | Structure file or PLI | Structure file or PLI | Mapping of GUI gate classes to modern gate/orifice/generalStructure; no documented SHP route inferred |
| Bridge pillars | PLIZ or Shapefile | PLIZ or Shapefile | GUI schema and sidecars; not the same object as a hydraulic bridge structure |

The text is documentation evidence, not a live menu/export observation. It does
not prove which fields survive a polygon-only exchange. Existing `.dsproj` and
companion directories are never inputs to the proposed native-file editor.
CSV crest editing is G16, not a substitute for G15. G13 pump sign measurements
and G18 observation sections likewise cannot approve this interchange.

## 2. Source mechanisms and counterexamples

Short names used here: `Readstructures` = flow1d_io/src/Readstructures.f90;
`Model` = dflowfm_data/unstruc_model.f90; `Control` = prepost/
flow_init_structurecontrol_implementation.f90; `Forcing` = timespace/
fm_external_forcings.f90. Full repository paths and line-numbered excerpts are
provided by the evidence JSON files.

| Concern | Pinned source lines | Contract implication |
|---|---|---|
| MDU entry and format | Model:480–505,823–868,2411–2434; Readstructures:90–103 | StructureFile is a declared input. The modern semicolon tokenizer explicitly allows filenames containing spaces, but the ENTIRE list is first copied into character(IdLen) inputFiles/file. Independently, the no-semicolon kernel path calls whitespace-splitting strsplit before prop_file (Model:2414–2425; string_module.f90:787–848); modern tokenization alone does not qualify a single MDU filename containing spaces. Total list length, not just token count, needs a native-buffer bound. The older single-file tree skips lists. Do not use a generic unknown-leaf inventory. |
| Versions | Readstructures:69–83,164–187,286–292 | Modern reader supports major2 and3 within its checks; missing/v1 returns to older kernel handling. Bridge requires major3 with shift semantics. No header-only universal migration or invented bed-level shift. |
| polylineFile vs locationFile | Readstructures:260–274; Control:436–448 | The pinned modern reader tries locationFile then a warned polylineFile fallback. It is false to claim the pin universally rejects polylineFile. First CLI increment may require locationFile as an explicit policy; it is not an engine fact or automatic conversion. |
| Structure identity | Readstructures:209–226; MessageHandling.F90:139 | id/name/type are separate fields; source IDLEN is256 with a255-character C-interface recommendation. Do not inherit G18's64-byte name limit as an engine limit. |
| Location precedence | Readstructures:233–274 | branchId+chainage, inline numCoordinates/X/Y, then locationFile are different location mechanisms. Reject competing declarations in a writable profile even if native chooses one by precedence. |
| Geometry file consumption | polygon_module.f90:284–340 | Reader skips initial first-column* records, ignores the location label as structure identity, reads N XY points from the FIRST block, then closes. Concatenating one PLI per selected structure into one file would silently lose later geometries. Source reading XY also does not qualify arbitrary extra PLIZ columns. |
| Weir crest and width | Readstructures:1111–1142 | crestLevel may be a scalar/file/realtime through the forcing list; crestWidth is a scalar here, defaulting internally to1e10. Generic `width` is not a substitute key. Preserve explicit values/default absence; do not materialize defaults. |
| Gate width/opening | Readstructures:1267–1309 | crestLevel, crestWidth, gateLowerEdgeLevel, gateOpeningWidth have forcing registration; gateHeight/opening direction are distinct. Do not treat every width-bearing field as the same hydraulic dimension. |
| Pump drive | Readstructures:934–1067,1439–1454; UM C.12.5 PDF480 | orientation and signed capacity are different. numStages=0 supports scalar/file/realtime. Staged capacity is a nonnegative table with trigger/controlSide and optional reduction table. Geometry order alone does not establish geographic transport direction. |
| Forcing identity | Readstructures:1070–1107; structures.f90:500–535 | File-valued parameters register object_id=id, object_type and quantity_id=type_parameter. PLI label is NOT the BC Name and there is no boundary-style automatic `_0001` suffix. |
| TIM/BC/realtime | Control:90–103; Forcing:1349–1460 | `.tim` takes the uniform relation; `.bc` uses objid and forcingFile. REALTIME is an external controller dependency, not an asset filename. Old EXT's inferred `_0001.tim`/`.tim` fallback differs from a declared StructureFile parameter. |
| Actual quantity hookup | meteo1.f90:6873–6910; fm_external_forcings_update.f90:754–795 | Pump capacity, weir crest and gate quantities are separate runtime items. Copying input bytes/seeing a symbol does not establish a measured response. |
| Time semantics | ec_filereader_read.F90:116–185 | TIM time column is minutes; block time uses reference MJD minus timezone/24 plus minutes/1440. MDU TUnit is not the TIM unit. BC has its own headers/units. Preserve authored t=0 distinctly from actual initialized engine state. |
| BC content | ec_provider.F90:82–124,242–312; ec_bccollect.f90:56–167,303–374 | Lookup/creation uses quantity+location and ordered headers, not just extension. Repeated Quantity/Unit columns require their grammar; duplicate/mismatched physical blocks cannot be blessed by generic INI parsing. |
| Nested paths | Readstructures:145–155,270; Model:2419; Control:94–96; unstruc_files.f90:492–504 | Geometry path base is chosen per structure file; forcing control uses md_structurefile_dir, including TWO consecutive resolvePath calls in the pin. Relative nested paths with mode1 may be prefixed twice; multiple-file base-dir TODO exists. Do not promise a universal portable parent-relative graph from the manual rule alone. |
| Pillar role | Model:608–637,865,2738; setpillars.f90:89–99,122–132,157–182 | PillarFile uses x,y,diameter,Cd; columns3/4 are NOT elevations. -999 in diameter or Cd skips an auxiliary. Manual excludes pillar3D. Modern type=bridge instead uses a hydraulic cross-section definition and shift. |
| Fixed-weir distinction | Model:122,594–604; reapol.f90:33–44; reapol_nampli.f90:133–216 | Base X/Y/Z differs from adjustable StructureFile. The generic reader contains3/4/5 and Baseline9/10 column branches and missing-X handling; not a universal5-column format and not the modern location reader. |
| Other native classes | Readstructures:278–314; structures.f90:468–535 | Universalweir, bridge, culvert, dambreak, compound, longCulvert and generalstructure introduce extra tables/IDs/definitions or kernel paths. Recognize them as deferred, never silently drop them. |

The nested-path finding is static evidence of the exact statements/call order,
not a new runtime failure claim. A future portable or native path probe must
establish behavior before widening eligibility. Current pump/weir examples use
3.01/locationFile; weir_series/model has a root crest.tim; pump has a constant
scalar capacity. Their exact inputs and current limited graph/editor modules
are hashed, not modified. Existing editors/runners are references, not a new
complete structure-transfer graph.

## 3. Proposed file and command contract

These are **proposed** names, absent from the current CLI. No registration patch
or executable implementation is supplied.

```text
dfm structure inspect MDU [--id FULL_ID]
dfm structure export MDU (--all | --id FULL_ID repeat)
    --representation geometry|hydraulic-bundle --out NEW_DIRECTORY
    [--apply --expect-sha256 HASH]
dfm structure import MDU --source GEOMETRY_DIRECTORY --representation geometry
    --id TARGET_ID --mode replace-matching --coordinates model-xy-as-is --xy-unit m
    [--apply --expect-sha256 HASH]
dfm structure import MDU --source HYDRAULIC_BUNDLE_DIRECTORY
    --representation hydraulic-bundle (--all | --id FULL_ID repeat)
    --mode append|replace-matching --coordinates model-xy-as-is --xy-unit m
    --target-structure-file EXISTING_RELATIVE_INI --asset-map MAP.json
    [--height-unit m --vertical-datum LABEL] [--apply --expect-sha256 HASH]
```

`inspect` reports every declared structure/PillarFile class and its exact
location/parameter representation, source spans, readers/version, dependency
roles and explicit blocked/deferred reasons. A parser inventory is never
`editable:true` for an unsupported concrete graph. An unknown class is reported
or refused for transfer, not omitted from `--all`.
Report units per parameter: capacity m3/s; crestLevel, crestWidth and gate
height/opening levels/widths m; orientation has no physical unit; pillar diameter
m and Cd dimensionless. Distinguish a literal file header's declared unit from
the native parameter convention: a scalar/TIM does not acquire a fictional Unit
header. In particular, never reuse pump capacity's m3/s label for a crest value.

Export and hydraulic-bundle selectors use exact canonical full source
Structure.id values re-derived from native INI. Geometry import instead
requires ONE explicit `--id TARGET_ID` and derives that target ID/type/roles
from the actual destination INI; its geometry route is operator-declared.
`name`, operator route IDs, native source IDs and PLI labels are separate.
Selection is mandatory for export/import; duplicate selectors usage2; no implicit
all, rename, suffixes, case matching or guessing. Global exact/casefold ID
ambiguity across declared INIs is refused as CLI policy, not an assertion of
native case sensitivity. Export/hydraulic source order is StructureFile-list
order then physical block order; replace uses destination slots. Geometry
import consumes one explicitly selected operator route, not an invented
native source order or auto-selected target. Proposed first profile IDs are
printable ASCII1..255 bytes, not trimmed or normalized; controls/quotes and
ambiguous property duplicates refuse. Every bound text has explicit byte limits.

### Geometry representation

Export a directory with one byte-identical active location PLI per unique source
file and a CLI-owned geometry.json operator-routing index. Never concatenate
different structure geometries into one native PLI. Sharing is inventoried;
export does not rename the PLI label to the structure ID. All hydraulic fields,
forcing, trigger tables and runtime controls are explicitly listed as NOT
included. No new hydraulic structure may be created from geometry-only data.

Geometry import first supports only replace-matching for ONE existing eligible
planar-XY weir/pump location file. It requires `--id TARGET_ID`; `--all` and
append refuse rather than selecting a target from metadata or inventing
hydraulic defaults. A unique canonical geometry.json route_id must equal
the explicitly requested target ID. That is an operator-declared route,
not evidence of a native source Structure.id. Source ID/type/authenticity
are unavailable in geometry-only payloads and are reported unverified.
Source PLI provides actual geometry/label only; never match or relabel its
header to prove a source identity. A route change is a changed request/map
requiring fresh consent, not a verified source-ID rename.
Replace the existing PLI bytes in one publication; leave StructureFile, all
forcing and MDU bytes unchanged. Refuse any other physical consumer of that
writable location file. Order and declared point count are preserved as authored;
no reversal/snap/reprojection or geographic flow prediction is implicit.

First location PLI policy: whole ASCII file, one nonempty canonical label,
contiguous N>=2 two-column finite normal XY rows (or exact zero), noncollapsed
segments, bounded record bodies<=256 bytes and vertices<=100000. Initial
first-column* comments and explicit trailing file trivia may be preserved;
second geometry blocks, extra numeric columns, nonnumeric separator records and
interior unknown records refuse. Modern location reading assigns numeric XY
directly: finite X=-999 or999.999 is NOT a native block separator here. Do not
inherit G18 missing-X splitting/refusal or MATR64 bounds. Any future rejection
of a finite sentinel-looking coordinate must be an explicit conservative CLI
policy, not misreported as this native reader's behavior. This is a conservative policy, not all behavior the native
first-block reader might tolerate. Pump PLIZ and pillar four-column data have
separate deferred grammars; do not truncate them to XY.

### Hydraulic-bundle representation

`bundle.json` is a new CLI interchange index, **not an observed GUI format or
an FM input file**. It contains schema/policy version, selection and order,
original role/relative paths, source byte-span lineage, exact raw payload hashes,
spatial/clock declarations, dependency/consumer graph, omissions and eligibility.
No runtime implementation-source rehashing; release pins belong in packaging/V.

Bundle payload consists of selected raw `[Structure]` blocks, the required raw
`[General]` version/type context per original INI, exact active geometry and
supported referenced TIM/BC/table assets, plus source-MDU context bytes for
explicit path mode/clock provenance. That context is NOT a runnable MDU export:
unrelated original model dependencies are not a complete model in this bundle.
Preserve each native relative layout and
header; no generic INI roundtrip, synthesized hydraulic defaults or renaming.
Nonselected blocks are excluded/disclosed. Native core and file-trivia spans
are defined below; they are never guessed from a generic INI serializer.
Nonselected destination bytes remain exact.
Delimiter bridges at splice points are explicit original-EOL bytes with hashes.

INI framing is explicit, not borrowed from G18. Require one explicit General
before the Structure blocks, one3.01 fileVersion and structure fileType; reject
duplicate General/critical keys and unsupported global semantics. A General or
Structure core runs from its physical section header through its LAST key/value
record, including its EOL. Comments/blank records before that last key belong
to the core; trailing comments/blanks before the next header/EOF are file-owned
gaps/footer. Prologue is file-owned. Bundle projection copies raw General core
and selected Structure cores in physical order, records omitted file-owned
trivia, and never discards an unknown key to shorten a core. Destination gaps,
footer, General and non-target blocks stay exact. Prefixes/bridges are disclosed.
Unknown General fields/blocks must be catalogued before an eligible transfer;
copying a fragment cannot silently drop default-sensitive global context.
Require source/target General semantic context to match; import never replaces
the target General or silently upgrades its format. First General admission is
the explicit version/type pair only, plus comments/trivia, until any additional
global field's meaning has been source-reviewed.

bundle.json, geometry.json and the asset-map are ALL untrusted input on every
import. Strictly parse their schema/duplicate keys/paths/declared roles before
any extraction or target access. Re-open actual assets, recompute
the native reference/quantity/ID graph and compare all claimed spans/hashes;
reject duplicate JSON keys, extra undeclared assets, missing edges, unsafe paths
and forged completeness/approval. Stored eligibility, passed/research receipts
and origin labels never authorize an operation. Re-derive native IDs/types
only where raw INI actually provides them: hydraulic-bundle source IDs/types
and BOTH representations' destination IDs/types/roles. Geometry-only source
routing is an unverified operator declaration, never a re-derived native ID.
Re-read actual PLI geometry and any applicable TIM/BC native graph and
quantity/clock compatibility from payload and target bytes. Do not require
or invent missing source INI/hydraulics for geometry-only data.
No directory extraction, unlisted nested dependency or lexical alias bypass is
permitted. Source context/metadata is input provenance,
not authenticated proof of a source project's history. Users can author a new
bundle intentionally; that requires a fresh preview of its ACTUAL contents.

`append`: all selected IDs must be new, casefold-disjoint from every existing
Structure.id across admitted INIs; insert source
blocks before the destination INI footer in source order. No skip-on-collision.
PillarFile header labels/array indices are not proven to share that namespace.
Pillars are separately inventoried/deferred, and unsupported Pillar interactions
refuse; never equate a Pillar label with a hydraulic Structure.id.
`replace-matching`: EVERY selected ID exact-matches an existing structure of
the same supported type; replace in destination slots without appending new IDs.
Refuse a compound/control/other-model ID consumer whose semantics cannot be
preserved; no type change or implicit ID-reference updates.

First hydraulic import changes ONE existing target StructureFile only. The user
must explicitly name that existing declared target; no MDU insertion/new target.
An explicit asset-map binds bundle logical assets to ordinary existing model
assets with exact matching bytes. Path tokens may be rewritten only according
to that map, with every token before/after/span disclosed; all other source block
bytes remain raw. Rebuild the prospective consumer graph before consent. Reuse
of read-only byte-identical shared assets is allowed only with all consumers
bound and no semantic/clock mismatch; never alter a shared asset implicitly.
Missing/different mapped assets refuse. New asset copying, multi-INI mutation,
forced overwrite or deleting old unused assets is NOT hidden in this first
operation: those require the separate transaction increment below.

### Closure, assertions and unknowns

Bound the actual MDU, all supported declared inputs and output destinations,
StructureFile list/order, IDs/types, location modes and resolved geometry,
scalar/file/realtime parameter discriminants, clock data, tables, compound and
cross-section references, file identities/aliases, parents/security and external
bundle/map bytes. Source includes unselected data. Unknown or ambiguous graph
edges prevent a complete/writable result; filename-looking heuristics alone are
not proof of closure. NetCDF bytes can be fingerprinted without decoding for
the initial 2D file transfer; no spatial assignment is claimed.

Keep comments, unknown fields, casing/order/precision, repeated unrelated MDU
scalars and every non-target byte. Unknown selected hydraulic keys or unknown
reference-bearing keys block import until catalogued; do not strip or invent
their semantics. Unknown non-target data stays raw and blocks complete closure
where its dependencies cannot be established. Duplicate addressed native keys
and duplicate IDs are not equivalent to unrelated custom MDU repetitions.

`model-xy-as-is`/m is an explicit caller assertion of already compatible source
and target XY, not a CRS test or conversion. The first profile performs no unit,
axis, datum, Z or chainage transformation. When transferred fields contain height,
require `--height-unit m --vertical-datum LABEL`; the label is a user assertion,
not guessed from CRS, numeric values or a mutable bundle receipt. Record actual
spatial metadata as known/unknown separately. Pillar diameter must never receive
a vertical datum transformation. Refuse unsupported units rather than convert.

For TIM-bearing transfer bind explicit source and destination RefDate/TZone and
the native minute convention; require compatible absolute origins/timezone and
intended time coverage. BC requires its actual Name==structure-ID binding,
typed quantity/units/function/column grammar and CF origin, with no boundary
support suffix or silent time/value conversion. REALTIME/RTC requires an external
controller/DIMR dependency closure and cannot be exported as a self-sufficient
static signal. Do not substitute native initialized t=0 values for authored knots.

First path scope is one modern3.01 root StructureFile with a nonempty,
UNQUOTED and WHITESPACE-FREE MDU `geometry/StructureFile` value, with NO
QUOTE CHARACTERS OR SEMICOLON, explicit path mode0, ordinary model-root-contained assets and exact lowercase suffix
dispatch. A single `with spaces.ini` MDU value is explicitly outside I1.
This admission restriction addresses the additional kernel single-file
path; it is not a runtime-failure finding or global filename-space ban.
File transfer qualifies an explicit planar locationFile mechanism, not the
underlying mesh dimensionality or an engine run. Require explicit Kmx=0 for
this initial profile, but report mesh/1D-vs2D topology validation as not performed;
Kmx=0 alone does not prove a2D mesh. Branch locations, mixed/3D transfer semantics
and native-run eligibility need their own actual mesh/topology gate.
Ordinary child location/forcing filenames and external bundle/destination
paths may still contain spaces if their own role-specific readers, bounds
and path safety checks admit them. Shell quoting is separate. Modern
semicolon-list filename-space capability stays in the deferred path/list
coverage, not an end-to-end native-eligibility claim. Reconcile both reader
paths before expansion; do not add a semicolon to bypass one path or infer
that quoting repairs all readers. Require ASCII native parameter/ID strings<=255 bytes,
and the ENTIRE semicolon-delimited StructureFile string<=255 bytes even when
future list scope is enabled. Any path built into a fixed256-byte filename
variable must also remain<=255 bytes after applicable prefix operations. Refuse
overlong strings before tokenization/native-eligibility claims, never truncate.
The count64 budget is an additional ceiling, not permission to exceed that
aggregate string bound. First root/mode0 avoids the unresolved prefix doubling.
Scalar/file discrimination must match the source branch before resolving a
dependency. Fortran list-directed scalar read can accept a numeric prefix in a
string such as `1 crest.tim`; refuse that ambiguity rather than guessing it is
a file from its suffix or silently importing it as a pure scalar. First profile
requires an entire finite normal scalar token (or exact zero), a supported
unambiguous filename, or explicitly deferred REALTIME; no underflow/overflow.
Modes1/nested/multiple INIs remain in the matrix but are refused pending the
source-derived resolver/last-basedir issue and independent path cases. No absolute,
UNC/device/ADS/parent-traversal/symlink/reparse/hardlink or input/output aliases.
External bundles/exports are outside model root; output absent, parent existing.

Proposed budgets:512 graph files/2GiB total,256MiB opaque leaf,8MiB per text,
64MiB aggregate text,64 INIs/1024 structures for future list scope,128 forcing
assets per selected batch and100000 geometry vertices. Count all actual source,
destination and mapped/new assets in aggregate budgets; no unbounded raw JSON.

### Consent and publication

Default preview writes nothing. Apply requires exact request-bound
`input_sha256`: versioned edit/publication policy, raw selectors/resolved order,
representation/mode, assertions/map, all graph and bundle bytes/identities/roles,
output absence/parent/security, intended complete bytes and operation digests.
No-op means complete intended target bytes identical: recheck full source/graph/
security, do not stage or churn identity/mtime. Existing export destinations are
never no-ops. Fresh apply must reject same-content replaced identities, changed
unselected data or metadata, aliases and late file/parent/security changes.

Reuse the reviewed inherited-ACL one-existing-file publisher through its actual
graph snapshot/access/recheck interface, keeping honest raw commit/readback/
owned rollback/cleanup facts. No guessed-path rollback and no global CAS claim.
Current pump-specific graph cannot simply be called a full G15 graph. B04's
OwnedStage is a candidate ownership primitive for new directory export, but its
boundary prefix, error context, parent/security and directory-publication protocol
need an explicit adapter/review, not direct unqualified reuse. Export must use
exclusive fresh-directory publication with retained ownership/late checks; final
published output is not deleted after a postcommit readback error.

Installing NEW assets or changing multiple target files is a separate phase:
either publish a fresh standalone model-root collection with a reviewed commit
boundary, or design a durable journal and independently verify every failure
prefix/recovery/foreign-owner case. A loop of per-file atomic replaces is NOT
an atomic multi-file import. Until that phase is approved, refuse it in preview.

Errors proposed: usage2; unsupported/data/path/alias3; collisions/missing exact
match/stale/publication4. Results separate syntax/reference/semantic-profile,
file publication, native initialization/completion and numerical/GUI evidence.

## 4. Full coverage matrix and staged delivery

Every row is a retained part of G15, not a claim of implemented support.
`coverage.json` supplies the same machine-readable map.

| Row | Native/file mechanisms and documented GUI formats | Initial disposition | Required next gate |
|---|---|---|---|
| W2D | Modern simple weir, root XY PLI + scalar or TIM crest; hydraulic INI; GUI PLI/structure/SHP export | I1 target: geometry + hydraulic bundle export, guarded one-file import | Independent literal file/clock/consumer/publication cases; later native pair |
| P2D | Modern scalar unstaged pump, XY PLI + orientation/capacity; GUI PLI(Z)/SHP both ways | I1 target: as above, explicit no geographic-sign guarantee | Same preservation gates; independent fixed-coordinate native flow if run later |
| WTBC | Weir/pump declared BC or pump TIM | I2 typed full BC/TIM import, do not fake suffix/units | Quantity/object/column/CF origin and shared-block cases; later receiver proof |
| G2D | Gate/sluice, modern gate/orifice/generalstructure + vertical/horizontal motion fields | I3 deferred, never label as simple weir | Explicit native class map, every hydraulic/control field, PLI/INI matched cases |
| PTRIGGER | Staged/reduction-table/realtime pump, trigger levels and controlSide | I3 deferred | Tables/counts/negative-capacity restrictions/controller closure and bounded native response |
| PIL12 | PillarFile PLIZ4 x,y,diameter,Cd, auxiliary -999; manual1D/2D | I4 separate role-specific importer/exporter | Sentinel/4-column preservation, ID grouping, dragging/topology native controls |
| PIL3D | Manual says pillar3D unavailable | Explicit unsupported; retained row | New authoritative reader/manual and runtime evidence before any support claim |
| PPLIZ | Pump geometry PLIZ including extra Z/attributes | I4 deferred, not truncated to XY | Actual GUI/native Z schema and preservation, no assumed elevation semantics |
| SHP | Pump/pillar SHP both directions; weir SHP export; gate SHP not inferred | I5 distinct GIS interchange | Real GUI files, SHP/SHX/DBF/PRJ/CPG schema, geometry/Z/units/CRS/ID mapping and complete sidecars |
| D1 | BranchId+chainage and explicit inline XY alternatives, 1D/native networks | I6 deferred | Branch/chainage maps, actual topology/CRS/units and CrossDef/CrossLoc closure; not a2D PLI rename |
| MODEL3D | Layered/mixed models using hydraulic weir/pump/gate data | I6 deferred; Kmx is not topology proof | Actual dimensionality, elevation/layer/control interpretation and raw receiver evidence; no2D-file-to3D approval |
| LEG | Unversioned/v1 kernel polylineFile, v2/v3 fallback, legacy EXT/TIM/CMP, fixed-weir geometry | I6 explicit import refusal, inspection distinction | Version/type/forcing catalogue; no automatic format upgrade. FixedWeirFile base X/Y/Z,4/5 and Baseline9/10-column variants are not generic adjustable-weir INI geometry |
| OTHER | Universalweir/culvert/bridge/dambreak/longCulvert/generalstructure | I6 deferred, visible inventory | Per-type cross-section/table/native parameter grammar; bridge shift exactly preserved |
| GROUP | Compound members, cross-INIs, shared geometry/forcing and external controllers; modern list filename spaces vs kernel single-file whitespace split | I2/I6 staged expansion; unsafe mutation refused; I1 MDU value has no whitespace | Full consumer closure, explicit all-consumer handling, duplicate/dangling/cycle and BOTH path-reader cases |
| MULTI | New assets, new StructureFile/MDU ref or multiple existing target writes | I7 transaction dependency | Reviewed fresh collection or durable multi-file transaction and failure recovery evidence |
| GUI | Actual standalone project-tree operation and property/save/export results | Separate observed-workflow gate after file work | Fresh owned GUI projects/controls, format/name-collision/save/reopen/export tracing; no parity inferred |

**Recommended first increment:** I1 on the concrete current root3.01 XY weir
and constant-pump families, with root TIM weir asset closure. Deliver useful
geometry-vs-properties export and explicit one-existing-target import as above;
record omitted hydraulics in geometry mode, require existing identical mapped
assets for hydraulic import, and refuse all broader matrix rows explicitly.
That does not complete G15. In particular BC, gates, pillars, GIS,1D, version
migration, live controls and multi-file installation remain named dependencies.

## 5. Prospective acceptance and limits

The tiny fixtures are manual bytes, not runnable models or native/parser tests.
They include labels!=structureIDs, exact property replacement/non-target pump,
duplicate/casefold IDs, duplicate scalar keys, alternate location ambiguity,
unknown scalar/file fields, shared/compound consumers, ignored second PLI block,
legacy headers, branch/inline/staged variants, pillar four-column/sentinel and
BC structureName versus `_0001`. No Shapefile bytes were fabricated as proof.

Before implementation approval, independent V/G must review this full contract,
scope matrix and sources. Future portable tests need literal export/import/
mapping/trivia bytes; whole-graph closure/ID/quantity/units/origin/missing cases;
unknown/deferred branches; stale requests with same bytes/new identity; stage
and final-file/dir races; actual ACLs; no-op; pre/postcommit faults and recovery.
Only after installed public-command checks may a separately assigned native
lease compare exact public/manual files, raw output geometry/values/masks/units/
CF times/restarts, active links and owned termination. A different lease and
fresh controlled GUI project are needed to assess GUI standalone interchange.

No scientific thresholds, actual native results or GUI format/collision claims
are supplied by this proposal. Final contract approval belongs to V and G.

Independent V froze its own obligations/fixtures BEFORE receiving these
conclusions: G15-PROPOSAL-V-20261105-01/predeclared-03/freeze.json SHA256
`1795249b719c4ed63f4d617290262f7673ddceac7eeef675f36ee220989d0daa`.
That is an independent predeclaration, not approval of this proposed increment.
