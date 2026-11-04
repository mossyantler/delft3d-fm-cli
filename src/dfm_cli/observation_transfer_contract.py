"""G10 proposal delivered before implementation. Root registration is parent-owned.

PUBLIC API / ACCEPTANCE
  observation export MDU --out NEW.xyn [--apply --expect-sha256 HASH]
  observation import MDU --source FILE.xyn --mode append|replace-all
      --crs EPSG:NNNN --unit m [--apply --expect-sha256 HASH]

register(observation_subparsers) returns that same SubParsersAction, to compose
with integrated observation.register. execute(namespace), contract(),
export_xyn(mdu,out,*,apply=False,expect_sha256=None), and
import_xyn(mdu,source,*,mode,crs,unit,apply=False,expect_sha256=None) -> dict.

Acceptance decisions (product policy, NOT inferred GUI behavior):
* Export exactly all bytes of the one existing named ObsFile, to an absent
  explicit .xyn outside the MDU folder. Parent must exist; never overwrite.
  Export binds MDU+selected XYN only, reports duplicates/record widths but does
  not refuse them or read the full graph/mesh/CRS; no geo extra required.
* append requires disjoint unique IDs, including NFC/casefold aliases; no skip,
  implicit overwrite or GUI collision policy. Existing bytes remain a prefix;
  explicit EOF separator only when needed. Remove only incoming leading BOM as
  disclosed transport framing so it is not injected in the middle of a file.
  Cross-dataset case/NFC aliases with different literal IDs refuse both modes.
* replace-all explicitly replaces ALL ObsFile bytes with exact incoming bytes,
  disclosing removed IDs, replaced IDs and added IDs before consent. Unknown
  target trivia is within this explicitly replaced target; other files untouched.
* Import requires at least one incoming station; zero/comment/BOM-only incoming
  files refused for either mode. Empty target is supported. Empty raw export is
  permitted as a byte artifact, without claiming native observations exist.
* For import, both datasets must have unique unambiguous IDs and whole-record
  required-token end <=256 bytes. Name character limits and the separate source
  history name width are not substitutes for this full-row bound. BOM/comments
  are raw preservation only, not asserted native-compatible.
* No transformation or snap. Explicit projected CRS/unit must match actual CF
  UGRID, as with G06. Validate all original and incoming positions, including
  original rows removed by replace-all; outside, edge/vertex or ambiguity refuse.
* One geometry preparation and quality/overlap validation per import batch, not
  one G06 locate call per station. Reuse integrated G06 Inputs/XYN/number/record
  guards and its shared CF/mesh quality checks in a prepared batch context.
  The existing CF validator makes one additional fixed CRS read, independent of
  station count. Spatial AABB index before exact predicates; bound work/memory.
* Fresh source must not alias target, another graph input, or declared output.
  Reject symlink/reparse/hardlink routes including dangling destinations before
  resolution. Actual full-byte graph/source hashes, request, face/CRS proof,
  old/new target bytes and destination bind preview; recheck at publication.
* Single-file import atomic replace; export uses atomic no-clobber publication.
  No preview writes, directory creation, model-ref rewrite, native/GUI launch or
  original-source mutation. No cross-file transaction/uncooperative-writer lock.

Evidence: FM UM2026.02 §7.4.2.2 printed72/PDF98 documents context-menu point
import/export and model XY; §24.1.7 printed369-370/PDF395-396 documents standalone
Observation points -> Export -> .xyn to another folder. Neither establishes GUI
name collisions, import replacement, BOM/comment handling or byte-preserving
GUI behavior. F.2.2.2 printed497/PDF523 describes named XYN and quoted spaces.
Pinned source5a4649830b1e5072caf019fb4850bbdefd9ad431 m_observations.f90:1003/1008
uses character(len=256) rec; parent native G06 slot154 independently confirmed
record256 completes/full history ID, record257 fails. History IDLEN256 is separate.
"""

CONTRACT = "observation-transfer-v1"
MAX_ROWS = 4096  # Combined original and incoming positions.
MAX_INDEX_REFS = 1000000
MAX_EXACT_FACE_TESTS = 200000
MAX_AABB_TESTS = 2000000
SOURCE = {"manual": "D-Flow FM User Manual 2026.02", "sections": ["7.4.2.2 PDF98", "24.1.7 PDF395-396", "F.2.2.2 PDF523"],
          "documents": "Standalone named observation XYN import/export exists; model coordinates; no documented GUI collision policy",
          "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
          "record_reader": "m_observations.f90:1003/1008 character(len=256) whole-record buffer",
          "native_record_reference": "G06-OBS-G-width154-01 (parent evidence, not a G10 run)"}
LIMITS = ["Standalone named ObsFile=.xyn only; not CrsFile cross-sections or project export",
          "Export binds only MDU+selected XYN and does not require/read other inputs, mesh or CRS; duplicate/width diagnostics do not block archival copying",
          "External paths reject ADS, Windows reserved basenames/segments, UNC/device namespaces, drive-relative/navigation routes and trailing dots/spaces before external file operations",
          "Import modes are explicit CLI policies; GUI collision/parity behavior is unknown",
          "Import rejects empty incoming datasets, duplicates/case aliases and overlong required-token records; an empty target is allowed",
          "Export can preserve an empty/comment-only dataset as a byte artifact; no station/native-output claim",
          "Import reuses G06 projected metre/strict unique interior scope, without projection, snapping or vertical assumptions",
          "BOM/comments preserved as raw bytes only; no general native encoding/comment compatibility claim",
          "Bounded batch, connected graph and exact-predicate budgets may refuse larger models before writing",
          "Single-file publication with final full-byte recheck; no lock against uncooperative concurrent writers",
          "No native/GUI execution or scientific/output-identity verification"]


def contract():
    return {"contract": CONTRACT, "commands": {
        "export": "observation export MDU --out NEW.xyn [--apply --expect-sha256 HASH]",
        "import": "observation import MDU --source FILE.xyn --mode {append,replace-all} --crs EPSG:NNNN --unit m [--apply --expect-sha256 HASH]"},
        "import_modes": {"append": "Unique disjoint identities only; retain all target bytes and incoming bytes except disclosed leading BOM framing",
                         "replace-all": "Replace whole ObsFile with exact source bytes; disclose removed/replaced/added IDs"},
        "empty_policy": {"incoming_import": "refuse zero named stations", "existing_target": "allowed", "export": "exact bytes allowed, including zero stations"},
        "preview_consent": {"export":"Explicit contract, MDU+selected XYN bytes, destination/parent identity and exact output bytes; other graph/mesh/CRS not read",
                            "import":"Explicit contract, full connected graph/source bytes, request/mode/CRS/face evidence, exact old/new XYN hashes; no Python-source inventories"},
        "batch_geometry": "One prepared mesh context and quality pass per import, one fixed additional CRS read; AABB index then exact rational predicates for decimal AND binary64 point",
        "bounds": {"combined_positions": MAX_ROWS, "text_bytes": 8388608, "nodes": 50000, "faces": 40000,
                   "whole_record_required_tokens_end_byte_column": 256, "spatial_index_references": MAX_INDEX_REFS,
                   "AABB_tests": MAX_AABB_TESTS, "exact_face_tests": MAX_EXACT_FACE_TESTS},
        "dependencies": {"export_and_contract": "standard library only; no installation", "import": "existing optional geo extra, lazily imported"},
        "gui_parity": "not_verified", "GUI_collision_policy":"unknown", "source_basis": SOURCE, "limits": LIMITS}
