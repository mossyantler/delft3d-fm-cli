# Comment lines in model input files (`*` and engine rules per file kind)

This note records how the product's line readers treat comment lines, and why. The engine has no single comment
rule: it depends on the file kind.

## Rules (engine source tag `DIMRset_2026.02`, `5a4649830b1e5072caf019fb4850bbdefd9ad431`, static analysis)

| File kind | Engine rule | Product reader |
| --- | --- | --- |
| MDU and other INI read by `prop_file` | after leading **spaces**, first char `#` or `*` (`properties.f90:325-334`); tabs become spaces only later (`:382-395`) | `model.parse` |
| new EXT, inifield | same INI rule | `boundary.py` (EXT), `boundary_locations_graph.py`, `layers_inputs.py` |
| PLI (`read1polylin`, `reapol`) | column-1 `*` lines before a polyline label only (`meteo1.f90:473-475`, `reapol_nampli.f90:85`) | `boundary.py`, `boundary_locations_graph.py`, `layers_inputs.py` |
| `.bc` header | column 1 in `!#%*` (`ec_bcreader.f90:194-195`) | `boundary.py`, `layers_inputs.py`, `project_files.py` |
| `.bc` data rows (from a block's first numeric row to the next header) | empty or column-1 `#` only (`:803-806`) | unchanged |
| observation `.xyn` | blank lines only (`m_observations.f90:1009-1010`) | unchanged |

The installed binary's source commit is not established.

## Behaviour

- **INI rule:** a line is a comment when, after the optional UTF-8 BOM on line 1 and any run of ASCII spaces, its first
  byte is `*` (or `#`). A tab before the `*` does not make a comment; such a line keeps its earlier reading
  (`syntax_error`, or a key such as `*key` when it contains `=`). Entries after a comment line shift by exactly its
  byte length.
- **PLI:** readers that accept one polyline skip column-1 `*` lines before its label; readers that accept several also
  skip them between one polyline's last row and the next label. No reader gained multi-polyline support.
- **`.bc`:** column-1 `!`, `%` or `*` lines before a block's first numeric row (or before the first block) are
  comments; in the data rows they keep their earlier handling.
- Writers never touch comment lines, so preview/apply edits keep them byte for byte.
- The product still also accepts `;` lines and inline `#`, which the engine readers do not all list.
- **Other `boundary._blocks` callers:** since `CONSUMERS-G` the twelve callers in `boundary_export*`,
  `boundary_vertical*`, `boundary_preview_graph`, `boundary_import_parse`, `boundary_series*`,
  `boundary_constituents*` and `source_sink_graph` pass the mode of the file they read (`ini` for new EXT and inifield,
  `bc` for `.bc`). **Remaining gap:** `source_sink_run_inputs.py:110` still reads its `.bc` with the earlier rule
  (`CONSUMERS-RUN-INPUTS`).

## Verification (2026-11-09)

| Step | Result |
| --- | --- |
| `model.parse` ([Contract](../delivery/ini-star-comment.md) + R5) | 20 author tests; V 265 cases (112 new acceptance fail on base); schema and usage of 107 commands unchanged; regression 1,878 |
| Other readers ([Contract](../delivery/ini-star-align.md) + R5) | 23 author tests; V 410 decisive cases pass (164 new-behaviour cases fail on base); round 1 REJECTED only a frozen private probe that omitted the new mode argument, round 2 passed with the reviewed one-call adapter; regression 1,901 |
| `_blocks` callers ([Contract](../delivery/ini-align-consumers.md) + R5) | 18-line product change in 10 modules; V 7,717 checks over 2,033 public CLI calls in eight command families; regression 1,927 |

- **Evidence:** [model.parse V review](../../experiments/INI-STAR-V-Run-20261109-01/REVIEW.md),
  [G](../../experiments/INI-STAR-G-20261109-01/acceptance.json);
  [alignment V round 2](../../experiments/INI-ALIGN-V-Run-20261109-01/REVIEW-r2.md),
  [round 1](../../experiments/INI-ALIGN-V-Run-20261109-01/REVIEW.md),
  [G](../../experiments/INI-ALIGN-G-20261109-01/acceptance.json).
- Origin: G15 V-Run round 1 (finding V01).

## Not established

- engine or GUI runs with these comment lines;
- `source_sink_run_inputs.py:110` (above);
- TIM and other readers not listed.
