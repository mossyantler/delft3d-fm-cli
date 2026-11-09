# Contract: engine comment rules in the other line parsers (EXT, inifield, PLI, BC header)

Beads: `INI-STAR-OTHER-PARSERS` (`dfm-3ks.4`, mapping, done by this Contract), `INI-ALIGN-I`, `INI-ALIGN-V-Plan`,
`INI-ALIGN-V-Run`, `INI-ALIGN-G` (new). Status: proposal by the coordinator, 2026-11-09. Product verification rules
apply in full. No native engine or GUI run belongs to this Contract.

## Background

After `INI-STAR-G` (`9c2a735`), `model.parse` follows the engine INI reader for `*` lines. Four other product line
parsers still skip only empty, `;` and `#` content. The engine has no single comment rule; it depends on the file kind
(static analysis of tag `DIMRset_2026.02`, `5a4649830b1e5072caf019fb4850bbdefd9ad431`, paths under
`research/upstream/Delft3D/src`):

| File kind | Engine reader | Comment rule |
| --- | --- | --- |
| new EXT, inifield (INI) | `prop_file('ini')` (`fm_external_forcings_init.f90:90`, `unstruc_inifields.f90:248`) | after leading spaces, first char `#` or `*` (`properties.f90:325-334`); tabs only later (`:382-395`) |
| PLI (boundary `locationFile`) | `read1polylin` (`meteo1.f90:453`, via `selectelset` `:5362`) | column-1 `*` lines before the label only (`:473-475`); count and coordinate rows have no comment skip |
| PLI via `reapol` (inifield vertical profile `dataFile`) | `reapol_nampli.f90` | column-1 `*` or blank lines before each label only (`:85`); data rows no skip (`:131`) |
| `.bc` header/block scan | `ec_bcreader.f90` | blank, or column 1 in `!#%*` (`:194-195`), then cut at `#` |
| `.bc` data rows | `ec_bcreader.f90` | empty or column-1 `#` only (`:803-804`) |
| observation `.xyn` | `m_observations.f90:1009-1010` | blank lines only |

Product sites (mapping by the coordinator's read-only survey, 2026-11-09): `boundary.py` `_text` (`:55-67`) feeding
`_blocks` (EXT), `_bc` (`.bc`) and `_pli` (PLI); `boundary_locations_graph.py` `lines` (`:223-235`) feeding `blocks`
(EXT) and `pli`; `layers_inputs.py` `blocks` (inifield, EXT, `.bc`), `polyline` (PLI), `profile_table` (`reapol`
data file) and the obsfile loop (`.xyn`); `project_files.py` `_bc_references` and `_bc_semantics` (`.bc`). Today a
`*` line in these files is an error, a misread label, or a misparsed field such as `* k`.

## R1. Product change

Make each site follow the engine rule of the file kind it reads, and nothing else:

1. **EXT and inifield (INI rule):** a line whose first byte after the optional line-1 BOM and any run of ASCII spaces
   is `*` is a comment, exactly as `model.parse` (`ini-star-comment.md` R5.1: a tab before the `*` keeps the current
   behaviour).
2. **PLI (`read1polylin` and `reapol` rule):** a line whose first byte is `*` and that comes before a polyline label
   (before the first label, and between the end of one polyline's rows and the next label) is a comment. `*` lines
   anywhere else, and the current handling of blank lines, stay as they are.
3. **`.bc` header (block-scan rule):** a line whose first byte is one of `!`, `#`, `%`, `*` outside a block's numeric
   data rows is a comment. Data-row handling stays as it is.
4. **`.xyn` and every other rule stay unchanged**, including the product's acceptance of `;` and inline `#`, which is
   a separate question.
- Shared helpers may be introduced only inside the four named modules; no other product module changes. If a site
  cannot follow its rule without changing another module, stop and report.
- Result: 212 product files, 107 commands, schema byte-equal.

## R2. Tests

- New tests, one module per product file or a single `tests/test_comment_rules.py`: for each rule, a file with the
  comment line in each allowed position reads exactly like the same file without it (entries, labels, points,
  rows), edits keep the comment line byte for byte, and `*` in a non-comment position (PLI coordinate rows, `.bc`
  data rows, `.xyn`, tab-led INI) keeps its current outcome.
- New-behaviour tests fail on the base; controls pass on both.
- Full `unittest discover -s tests`: no new failures against the base (1,878 tests, 33 geo skips).

## R3. Independent verification

- **V-Plan (Contract and engine source only):** cases per rule and position, including adverse ones, and public
  commands that read each file kind (boundary inspect/edit, boundary locations, layers, project audit) with and
  without comment lines.
- **V-Run:** the plan against the frozen candidate on a clean wheel install; regression on candidate and base.

## R5. Clarifications (coordinator, after V-Plan; binding for I and V)

1. **PLI scope (A1).** R1.2 changes comment handling only within what each reader already supports. Readers that
   accept exactly one polyline keep refusing a second one; for them the rule covers `*` lines before the first label.
   Readers that already accept several polylines also skip `*` lines between one polyline's last row and the next
   label. No reader gains multi-polyline support.
2. **BC lines after numeric rows (A2).** A `.bc` line is a header comment under R1.3 only when it comes before the
   first numeric data row of its block (or before the first block). From a block's first numeric row until the next
   block header, the engine's data reader applies (`ec_bcreader.f90:803-806`: empty or column-1 `#` only), so `!`,
   `%` and `*` lines there keep their current product behaviour.
3. **Project audit (A3).** There is no public `project audit` command, and console-backed `project import/export` is
   outside this Contract. Labeled internal coverage through `project_files.audit_project` and `_bc_semantics` meets
   R3 for `project_files.py`; no console run and no new command.

## R4. Out of scope

- `;` and inline `#` differences; `.bc` data-row and PLI data-row comments; `.xyn`; `model.parse`;
- engine or GUI runs.

## Done when

- **I:** R1-R2; each site's change listed with its rule; `compileall` clean; schema byte-equal; full regression.
- **V-Plan / V-Run:** R3, PASS or REJECT.
- **G:** merge; wheel identity; full regression; `research/notes/verification/ini-comments.md` extended.
