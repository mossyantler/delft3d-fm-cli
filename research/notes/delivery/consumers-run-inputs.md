# Contract: `.bc` comment mode in the source-sink run inputs

Beads: `CONSUMERS-RUN-INPUTS` (`dfm-3ks.15`, this Contract), `RUNIN-I`, `RUNIN-V-Plan`, `RUNIN-V-Run`, `RUNIN-G`
(new). Status: proposal by the coordinator, 2026-11-09. Product verification rules apply in full. No native engine
or GUI run belongs to this Contract.

## Background

`CONSUMERS-G` (`cd67e7a`) made every listed caller of `boundary._blocks` pass the comment mode of its file kind
(`research/notes/delivery/ini-align-consumers.md`; rules in `research/notes/verification/ini-comments.md`). One caller
was left on the earlier rule by R5.1: `source_sink_run_inputs.py:110`, where `bc_state` parses the source-sink `.bc`
file with `bounded_blocks(raw, path)` and then pairs those blocks with `graph.read_bc(path)`, which since
`CONSUMERS-G` reads the same file with `comments="bc"` (`source_sink_graph.py`). The two parses can therefore disagree
on a `.bc` file with header comment lines. `bc_state` feeds the admission of `dfm run start --profile source-sink`
(`source_sink_run_profile.py`).

## R1. Product change

- `source_sink_run_inputs.py:110`: `bounded_blocks(raw, path, comments="bc")` (or the positional form the helper
  uses). No other change to any product module.
- Result: 212 product files, 107 commands, schema byte-equal.

## R2. Tests

- A source-sink `.bc` with column-1 `!`, `%` or `*` lines before a block's first numeric row (and before the first
  block) gives the same `bc_state` result and the same `run start --profile source-sink` admission outcome as the
  same file without them; `*` in data rows and a tab-led `*` keep their current outcome. No engine is launched: test
  the admission and input fingerprint path only (the existing tests show how the profile is prepared without a run).
- New-behaviour tests fail on the base; controls pass on both. Full `unittest discover -s tests`: no new failures
  against the base (1,927 tests, 33 geo skips).

## R3. Independent verification

- **V-Plan (Contract and engine source only):** cases as R2 through public commands where possible (`run start
  --profile source-sink` preparation without launch, `source` inspection commands), or by calling the admission
  helpers with explicit arguments; plus unchanged results on files without comment lines.
- **V-Run:** the plan against the frozen candidate on a clean wheel install; regression on candidate and base. No
  engine, GUI or real-run Job.

## R4. Out of scope

- Engine runs; any other parser or caller; `;` and inline `#`.

## Done when

- **I:** R1-R2; `compileall` clean; schema byte-equal; full regression.
- **V-Plan / V-Run:** R3, PASS or REJECT.
- **G:** merge; wheel identity; full regression; the remaining-gap line in `research/notes/verification/ini-comments.md`
  removed.
