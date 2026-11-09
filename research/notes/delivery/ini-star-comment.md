# Contract: INI comment lines that start with `*`

Beads: `INI-STAR-COMMENT` (`dfm-qu3`, I), `INI-STAR-V-Plan`, `INI-STAR-V-Run`, `INI-STAR-G` (new). Status: proposal by
the coordinator, 2026-11-09. Product verification rules apply in full. No native engine or GUI run belongs to this
Contract.

## Background

- **Engine (source, `DIMRset_2026.02`, `5a4649830b1e5072caf019fb4850bbdefd9ad431`):** the INI reader
  `prop_inifile_pointer` (`src/utils_lgpl/deltares_common/packages/deltares_common/src/properties.f90:268-453`) left-trims
  each line (`adjustl`, line 325) and treats it as a comment when its first character is `#` or `*` (lines 331-334).
  MDU files and new-format INI inputs (EXT, structure, and other files read through `prop_file`) use this reader.
  This is static analysis of the tagged source; the installed binary's exact source commit is not established.
- **Product:** the shared reader `model.parse` (`src/dfm_cli/model.py:77-99`) skips empty lines, lines whose code
  before `#` starts with `;`, and inline `#` comments. A line whose first non-blank character is `*` raises
  `syntax_error` ("Expected section or key=value"). So the product refuses files the engine reads. Origin: G15 V-Run
  round 1 (finding V01; Contract `g15-finish.md` R5.1).
- `;` comment lines are accepted by the product but not listed by the engine reader. That difference is out of scope.

## R1. Product change

- In `model.parse` only: a line whose content, after stripping leading whitespace (and the UTF-8 BOM on line 1), starts
  with `*` is a comment line and is skipped like a `;` line. Nothing else changes: entry addresses, values, byte
  offsets of every other line, section handling, errors for other malformed lines, and every writer's byte
  preservation (comment lines stay untouched in edited files).
- No other product module changes. The other line parsers that also do not treat `*` as a comment (`boundary.py`,
  `boundary_locations_graph.py`, `layers_inputs.py`, `project_files.py`) are listed in the follow-up node
  `INI-STAR-OTHER-PARSERS`; each needs its own engine-reader mapping first.
- Result: 212 product files, 107 commands, schema unchanged byte for byte.

## R2. Tests

- New tests in `tests/test_model_comments.py`: a `*` line at file start (with and
  without BOM), after a section header, between keys and indented by spaces or a tab is skipped; entries, values
  and byte offsets equal those of the same file without that line, and an in-place edit of a later key preserves the
  `*` line byte for byte. A line like `x*=1` or `key = *value` keeps its current meaning.
- Each new test fails on the base and passes after the fix (show both).
- Full `unittest discover -s tests`: no new failures against the base (1,858 tests, 33 geo skips).

## R3. Independent verification

- **V-Plan (Contract only):** cases for R1-R2 derived independently, including adverse ones (a `*` inside a value, a
  `*` after `=`, `*` after leading whitespace, CRLF and LF files, `*` in MDU, EXT and structure INI files read by real
  commands), and a check that every existing public command result on the repository's fixtures is unchanged.
- **V-Run:** the plan against the frozen candidate on a clean wheel install, plus regression on candidate and base
  listing every differing test.

## R5. Clarifications (coordinator, after V-Plan; binding for I and V; they replace conflicting R1-R3 wording)

1. **Leading whitespace means spaces only.** The engine tests for `#`/`*` after `adjustl`, which removes leading
   spaces only, and converts tabs to spaces later (`properties.f90:325-334` versus `:382-395`). A tab before the `*`
   therefore does not make an engine comment. In `model.parse`, a `*` comment line is one whose first byte after the
   optional line-1 BOM and any run of ASCII spaces is `*`. A line with a tab anywhere before its first non-blank `*`
   keeps its current behaviour (`syntax_error`). R2's "or a tab" case becomes this refusal case.
2. **Offsets.** "Byte offsets unchanged" means: every entry's recorded span slices exactly its value from the actual
   file; compared with the same file without the `*` line, entries before the line keep their offsets and entries
   after it shift by exactly the inserted byte length, with equal addresses, values and line-number shift.
3. **Failing-before rule.** R2's "each new test fails on the base" applies to tests of the new `*` behaviour. Control
   tests of unchanged meaning (`x*=1`, `key = *value`, other malformed lines, the tab refusal) pass on both.
4. **Public fixture results (R3).** Discharged by the full `unittest discover` regression on candidate and base (the
   repository's fixtures run through public commands there), V's no-star fixture command comparisons and its usage
   parity check over every advertised command. No complete invocation matrix is required.

## R4. Out of scope

- `;` comments, `.bc` (`ec_bcreader`), PLI/XYN/TIM and other non-INI readers; the four other parsers above;
- engine or GUI runs.

## Done when

- **I:** R1-R2; one fix commit preceded by the failing tests; `compileall` clean; schema byte-equal; full regression.
- **V-Plan / V-Run:** R3, PASS or REJECT with reproducing commands.
- **G:** merge; wheel identity with 212 files; full regression; a short section in
  `research/notes/verification/` (where `model.parse` behaviour is recorded, or a new `ini-comments.md`).
