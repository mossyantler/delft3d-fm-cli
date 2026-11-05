# G15 revision02: two admission clarifications

This is a **proposal revision, not implementation or V/G approval**. It replaces
the two ambiguities below in revision01. The complete revised PROPOSAL.md,
contract.json and coverage.json agree on these choices. All67 files in frozen01
remain unchanged; all other evidence, coverage and publication limits carry over.

## Geometry routing does not verify a native source identity

The geometry payload contains PLI, not native hydraulic INI. Its PLI header is
not a Structure.id. geometry.json therefore declares operator routing only:

```json
{
  "format": "dfm-structure-geometry-v1",
  "routes": [{"route_id": "W_Main", "asset_path": "assets/location.pli"}]
}
```

Strict schema, bounded strings/assets, unique exact/casefold-safe route IDs,
ordinary contained paths, no duplicate keys and actual asset bytes are checked.
No source_type/verified_id/passed field is accepted as authority. No stored
eligibility, receipt or lineage claim qualifies the target or its consumers.

I1 geometry import requires one explicit `--id TARGET_ID`, mode
`replace-matching`, and a unique route_id exactly matching that request. `--all`
and append are refused. The operator selects a route; metadata never silently
selects another target. Actual TARGET ID/type/location role/shared consumers
come from the destination INI; actual source label/count/ordered XY come from
PLI. The label is neither matched nor rewritten to manufacture a native ID.
Source native ID/type/authenticity remain unavailable/unverified. Changing the
route is a new routing request requiring new consent, not a source-ID rename.

This differs from hydraulic-bundle import, whose raw native INI permits actual
source ID/type/refs to be re-derived. Both modes bind full request, routing/map,
paths, source bytes/identities and actual target graph/security to preview/apply.
Geometry import still changes only one existing exclusive PLI; it creates no
hydraulic defaults or new structures. The source-ID report must be representation
specific rather than claiming that every metadata ID has been re-derived.

## I1 restricts the MDU StructureFile value, not every path

At pin5a464, Readstructures.f90:90–103 explicitly tokenizes semicolon lists and
documents filenames containing spaces. However Model:2414–2425 also enters a
no-semicolon kernel path, calls strsplit, and calls prop_file for each token.
The pinned string_module.f90:787–848 defaults to whitespace separators and
handles quotes while splitting. Thus a single unquoted `with spaces.ini` MDU
value is not qualified by the modern reader's tokenizer alone.

I1 requires the MDU `geometry/StructureFile` value to be one nonempty unquoted
root-relative `.ini` filename with **no whitespace, quote characters or
semicolon**. Existing length/alias/path/mode bounds still apply. Do not add a
semicolon or quotes to bypass a reader path; no safe quoted multi-reader route
has been established. This is a bounded admission policy based on a counterpath,
not a newly observed engine failure or a proof of mesh/native validity.

Ordinary child location/forcing filenames and external bundle/output paths may
contain spaces under their own readers, bounds and lexical/security checks.
Modern filename-space list capability remains explicit in deferred coverage;
it is not erased or advertised as end-to-end native eligibility. Nested/multiple
INI/mode1 support still needs both reader paths and forcing base-dir handling
resolved independently.

## Evidence and checks

counterpath-source.json pins three exact source blobs and numbered excerpts;
the other16 source blobs and33 manual fixtures remain in frozen01. The new
literal routing/path cases are prospective controls only. Verification checks
the proposal's internal choices, hashes, JSON and Python artifact syntax; it
does not execute a product parser, Fortran, CLI transfer, solver or GUI. Root,
G18 documents and previous freezes are not edited. Final approval remains V/G.
