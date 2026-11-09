# INI comment lines starting with `*` (`model.parse`)

This note records how the shared INI/MDU reader `model.parse` treats comment lines, and why.

## Behaviour

- A line is a comment when, after the optional UTF-8 BOM on line 1 and any run of ASCII spaces, its first byte is
  `*`. It is skipped like an empty line, a `;` line or a `#` comment. Entries, values and byte offsets of every other
  line keep their meaning; entries after a `*` line shift by exactly its byte length.
- A tab before the `*` does not make a comment. Such a line keeps its earlier reading: `syntax_error`, or a key such as
  `*key` when it contains `=`.
- Writers never touch comment lines, so preview/apply edits keep `*` lines byte for byte.
- `;` comment lines remain accepted although the engine reader does not list them. Other product parsers
  (`boundary.py`, `boundary_locations_graph.py`, `layers_inputs.py`, `project_files.py`) are unchanged and tracked in
  `INI-STAR-OTHER-PARSERS`.

## Source

- Static analysis of the engine source tag `DIMRset_2026.02` (`5a4649830b1e5072caf019fb4850bbdefd9ad431`):
  `properties.f90:325` left-trims spaces (`adjustl`), `:331` treats a first `#` or `*` as a comment, and tabs become
  spaces only later (`:382-395`). The installed binary's source commit is not established.
- [Contract](../delivery/ini-star-comment.md) R1-R2 with clarification R5. Origin: G15 V-Run round 1 (V01).

## Verification (2026-11-09)

| Check | Result |
| --- | --- |
| Author tests | 20 new tests; new `*` behaviour fails on the base, tab-refusal controls pass on both |
| Independent cases (V) | 265 cases on a clean wheel install: 112 new acceptance (all fail on base), 20 tab-refusal controls, 133 unchanged; MDU, new EXT and structure INI files through public inspect and preview/apply |
| Public surface | schema byte-equal; usage results equal for all 107 commands; no-star fixture commands unchanged |
| Regression | 1,878 tests vs 1,858 on the base; only the 20 added tests differ |

- **Evidence:** [V review](../../experiments/INI-STAR-V-Run-20261109-01/REVIEW.md),
  [V plan](../../experiments/INI-STAR-V-Plan-20261109-01/PLAN.md),
  [G acceptance](../../experiments/INI-STAR-G-20261109-01/acceptance.json).

## Not established

- engine or GUI runs with `*` comment lines;
- comment rules of `.bc`, PLI, XYN, TIM and the four other product parsers.
