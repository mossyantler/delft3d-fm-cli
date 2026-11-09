# Contract: the other callers of `boundary._blocks` use the engine comment rule of their file kind

Beads: `INI-ALIGN-CONSUMERS` (`dfm-3ks.10`, this Contract), `CONSUMERS-I`, `CONSUMERS-V-Plan`, `CONSUMERS-V-Run`,
`CONSUMERS-G` (new). Status: proposal by the coordinator, 2026-11-09. Product verification rules apply in full. No
native engine or GUI run belongs to this Contract.

## Background

`INI-ALIGN-G` (`e7c32a0`) gave `boundary._blocks` an opt-in `comments` mode: `"ini"` (new EXT, inifield: `*` after
leading spaces is a comment) and `"bc"` (`.bc`: column-1 `!`, `%`, `*` before a block's first numeric row). Without the
argument it keeps the earlier rule. The rules and engine sources are in `research/notes/verification/ini-comments.md`
and `research/notes/delivery/ini-star-align.md` R1 and R5. Other modules still call `_blocks` without the argument, so
`boundary inspect` and other commands can read the same file differently. Every such call is followed by a
`_header(..., <filetype>, ...)` check that names the file kind (coordinator survey, 2026-11-09, at `3c04f50`):

| Call site | File kind (`_header` filetype) |
| --- | --- |
| `boundary_constituents_graph.py:87` | new EXT (`extforcefilenew`) |
| `boundary_constituents_parse.py:71` | `.bc` (`boundconds`) |
| `boundary_export_graph.py:109` (`bc_blocks`) | `.bc` |
| `boundary_export_graph.py:183` | new EXT (`extforce`) |
| `boundary_import_parse.py:52` | `.bc` |
| `boundary_preview_graph.py:213` (`parse_blocks`, used for several kinds) | per caller of `parse_blocks` |
| `boundary_series_parse.py:71` | `.bc` |
| `boundary_series_rows_parse.py:72` | `.bc` |
| `boundary_vertical_graph.py:47` | new EXT (`extforce`) |
| `boundary_vertical_graph.py:106` | inifield |
| `boundary_vertical_parse.py:73` | `.bc` |
| `source_sink_graph.py:159` (`bounded_blocks`, used for several kinds) | per caller of `bounded_blocks` |

Modules with their own `_blocks` (`rr_f152_inputs*.py`, `serial_profile.py`) are not callers of `boundary._blocks` and
are out of scope.

## R1. Product change

- Each call of `boundary._blocks` in the modules above passes `comments="ini"` when it reads a new EXT or inifield file
  and `comments="bc"` when it reads a `.bc` file. Where one helper serves several file kinds (`parse_blocks`,
  `bounded_blocks`), the helper takes the mode from its caller; every caller passes the mode of the file it reads.
  If a call reads a kind that is neither (or the kind cannot be determined), leave it unchanged and list it.
- Any other change to those modules, or a change to `boundary.py` itself, is out of scope; stop and report if one
  is needed.
- Result: 212 product files, 107 commands, schema byte-equal.

## R2. Tests

- For each public command family reached through these modules (boundary export, import, preview, series and series
  rows, vertical, constituents, source-sink), a file with comment lines in allowed positions reads exactly like the
  same file without them, edits keep comment lines byte for byte, and `*` in non-comment positions (tab-led INI, `.bc`
  data rows) keeps its current outcome. New-behaviour tests fail on the base; controls pass on both.
- Full `unittest discover -s tests`: no new failures against the base (1,901 tests, 33 geo skips).

## R3. Independent verification

- **V-Plan (Contract and engine source only):** cases per call site and command family as R2, including adverse
  positions, plus unchanged-behaviour checks on files without comment lines.
- **V-Run:** the plan against the frozen candidate on a clean wheel install; regression on candidate and base. Private
  helpers may change signature (a mode parameter); V-Plan probes should call public commands or pass the mode
  explicitly, so a signature change is not a verification failure.

## R4. Out of scope

- `;` and inline `#`; `.bc` and PLI data rows; `.xyn`; `model.parse`; modules with their own `_blocks`;
- engine or GUI runs.

## Done when

- **I:** R1-R2; every call site listed with the mode it passes and the file kind it reads; `compileall` clean; schema
  byte-equal; full regression.
- **V-Plan / V-Run:** R3, PASS or REJECT.
- **G:** merge; wheel identity; full regression; the known-gap line in `research/notes/verification/ini-comments.md`
  updated.
