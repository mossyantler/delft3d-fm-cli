# CLI product guide (`src/dfm_cli/`, `tests/`)

Read the root [AGENTS.md](../AGENTS.md) first. This file holds the public
contract and the per-command lessons that tests alone do not reveal. Before
broadening a command, read its linked verification note. The note gives the
tested scope and what is still unverified. Keep every scope as narrow as its
evidence.

This guide sits in `src/` rather than in `src/dfm_cli/`, so the product
tree that G reviews compare against each wheel stays unchanged.

## Contract every command keeps

- stdout carries only structured JSON results and errors, with documented exit
  codes and optional JSONL progress. Logs go elsewhere.
- Every command is discoverable with its parameters, schema and capability
  information and explicit limitations, so an agent never has to guess.
- Edits are preview, then explicit apply, with no prompts. Apply is bound to the
  exact preview hash, the full connected input graph, the request bytes and the
  destination. An inspection hash is never an apply token.
- An edit changes only the requested fields. It preserves unknown keys,
  comments, ordering, numeric precision and repeated blocks or columns. Generic
  INI rewriting destroys BC semantics.
- File-only inspection and preservation edits work on incomplete inputs.
- Preserve ordinary file permissions. Reject unsupported permissions and decoded
  unsafe text before staging.
- Resolve paths with the selected model's rules, including
  `PathsRelativeToParent`. Distinguish old from new EXT by content and settings.
  Read units, BC time origins, relative or absolute model dates, CRS and vertical
  datum explicitly. Never apply a default to an existing calibrated model.
- Inspection and editing never import research checkouts. The optional `run`
  extra provides the NetCDF reader. The optional `geo` extra provides horizontal
  CRS conversion.

## Runs and process lifecycle

- Every run gets a manifest: input fingerprints, the selected executable and its
  hash, the argument array, the working directory, relevant environment overrides
  and output/log paths. Pass subprocess arguments as arrays. Scope environment
  changes to the child.
- Each native launch joins a private Windows Job Object before its first thread
  resumes. Completion requires member-handle exit confirmation and an empty-job
  check. The root exiting or the PID list emptying is not enough. Cold short
  serial launches trace Job members before resume. An empty Job alone is not a
  retained-handle proof.
- `run status` reads recorded state and checks PID/creation-time identity for
  active records. `run cancel` asks the live owning controller to stop. Neither
  kills an arbitrary manifest PID, and there is no daemon, adoption or resume.
  Process-name or tree killing by an unverified recorded PID stays out of the
  code.
- Keep the terminal states `failed`, `timed_out`, `cancelled`, `cleanup_failed`
  and read-only effective `owner_lost` distinct. Collect diagnostic context and
  partial outputs on every native terminal path. A forced stop does not
  establish clean finalization, a usable restart or scientific validity, and a
  signal request does not prove cancellation.
- Completion is checked against the requested final simulation time and the
  output time axis. File existence or process exit alone is not completion.
- For a forced stop, unavailable or foreign member handles cannot prove exit.
  Observe the request's return and the retained original handles separately
  ([E011 follow-up](../research/notes/verification/job-force.md)).
- The common `short` lifetime/terminal gate comes from the separately verified
  `e32bf84f` wheel ([SHORT-CLOSE](../research/notes/verification/serial-close.md)).
  Before a terminal publication, retain the raw close receipts for the original
  members, the original Job and the collector. When lifetime alone is unproven
  but the actual close is confirmed, keep the legacy short-only
  `termination_unconfirmed` code. Pump and weir keep their own family error
  codes and lifecycle keys. This does not approve the pending B06/S07/B14
  products or broaden the default physical profile.
- A serial launch keeps the [FM Program identity gate](../research/notes/verification/fm-model-identity.md)
  on both the original and the staged MDU.
- The default final-checkpoint requirement and the opt-in configured schedule
  are separate gates ([O02](../research/notes/verification/checkpoint-schedule.md)).
  A clean run with restart output disabled has verified history/map clocks and
  no checkpoint to resume from.
- Batch execution uses owned subprocesses. The isolated BMI worker supports the
  checked 48-cell weir control and observation reads
  ([live worker](../research/notes/verification/live-worker.md)). Any other live
  interface goes in its own worker with an explicit lifecycle.
- Start with short serial cases. DIMR, MPI, restart and component coupling each
  get their own reproducible case. Initialization may itself write files.

## Boundaries (B-series)

- **B03** `boundary series-set` changes values at existing times.
  `boundary series-rows` inserts and deletes rows explicitly. A rows preview
  binds the point, the graph and the request to the exact new BC and operation.
  Preserve other lines and time coverage
  ([boundary series](../research/notes/verification/boundary-series.md)).
- **B04** `boundary export` collects active BC blocks and PLI locations into a
  fresh directory. Process groups require an explicit map; GUI process membership
  is never inferred. Preserve source block bytes, inventory and staging ownership
  ([export](../research/notes/verification/boundary-export.md)).
- **B09** keeps imports for the selected PLI distinct from other boundaries that
  share its BC. Any expanded merge policy must pass the independent checks and
  the manual-mode comparisons ([import](../research/notes/verification/boundary-import.md)).
- **B10 / location import:** remove retired forcing blocks from the active BC
  stream and keep the originals in the archive or loss receipt. A commented block
  after active numeric data can change results even when FM exits 0. Keep a
  target-last control with unequal surviving signals, verify CF clocks and compare
  the complete native arrays ([locations](../research/notes/verification/boundary-locations.md),
  [support](../research/notes/verification/boundary-support.md)).
  Horizontal PLI conversion needs the `geo` extra, explicit source/target EPSG,
  XY units and matching CRS metadata in the actual NetFile. The `as-is` path needs
  none of these and infers no datum.
- **B11** keeps a coefficient before the first Quantity and preserves raw rows.
  Linear-scalar behavior does not generalize to other BC functions
  ([coefficients](../research/notes/verification/boundary-coefficients.md)).
- **B12** `boundary preview` reads only the MDU/new EXT/PLI/BC input graph. A
  missing signal is reported separately from a zero. Source-based evaluation,
  installed-engine prescribed levels and receiving-station results are three
  separate things. Preserve the two-file correction regression and the raw input
  controls ([preview](../research/notes/verification/boundary-preview.md)).
- **B13** `boundary vertical-inspect/vertical-set` edits one existing T3D
  salinity cell. Preview and apply bind to `result.input_sha256`, the exact
  authored time and position tokens, units, the selected support, the input
  graph and file permissions. `VertPositionIndex` selects a BC value column; it
  is not a model layer index. Leave generation sidecars as they are after an
  edit. The three 20-second runs say nothing about GUI export behavior
  ([layers](../research/notes/verification/layers.md#b13)).

## Observations, sections and results (G/O-series)

- `observation inspect/add/move` work on existing XYNs. The raw history/map
  comparisons and the 256-byte record boundary define the tested geometry and
  serialization ([observation points](../research/notes/verification/observation-points.md)).
  `CrsFile` is an observation cross-section file.
- Standalone `observation export` binds the MDU and XYN only. Import validates
  the connected graph, the source and all positions against one prepared mesh.
  `section reverse` changes only the selected CrsFile record bodies, and an
  absent ObsFile is not an error ([G10/G12](../research/notes/verification/spatial-transfer.md)).
- `results stations` requires physical polygon identity and the actual all-times
  history/map join. It distinguishes masked, absent and unproven. Every CRS
  recheck stays, even when the mesh is streamed without retaining bytes
  ([release scope and receipt hashes](../research/catalog/coefficients-stations-gates.json)).
- **O03/O04** `model set` edits only the existing `output/Wrishp_obs` or
  `output/Wrihis_balance` scalar, and both the old and new token must be exactly
  `0` or `1`. The preview hash is the MDU SHA-256. Preserve unrelated
  repetitions. `model fields` points to this command separately from its
  `field-set` eligibility ([output toggles](../research/notes/verification/output-toggles.md)).

## Structures and sources (pump, weir, B06)

- **Pumps (G13):** a 2D pump's structure-relative reported sign is a different
  quantity from discharge in a fixed geographic direction. The original NetCDFs
  reject a polyline-only hydraulic reversal on a four-link constant-capacity
  fixture, so the CLI exposes no such reversal and never rescales capacity from
  that observation. Check storage on both banks and a stationary control
  ([pump orientation](../research/notes/verification/pump-orientation.md)).
  `pump inspect MDU [--id ID]` is read-only. `pump set` previews or applies
  exactly one existing orientation or signed capacity token, and its
  `result.sha256` binds the request and the input graph.
  `run start --profile pump-scalar --route direct` uses all six inputs, rechecks
  source and staged identities before launch, and confirms member exits and the
  original Job close before recording completion
  ([public pump](../research/notes/verification/pump-orientation.md#public-pump)).
- **Weirs (G16):** the three `weir series-*` commands are file operations with
  explicit units and a UTC origin
  ([example](../examples/weir_series/README.md)). The 0 s native history and
  the authored first knot are different points. The editor does not validate GUI
  CSV equivalence or qualify a run profile. For a matching 11-file, 48-cell
  channel use `run start --route direct --profile weir-series`; the
  [public replay](../research/notes/verification/weir-crest-series.md#public-run)
  compared all 189 variables per case without certifying a hydraulic sign or GUI
  equivalence.
- **Sources (B06):** `source inspect/add/set/forcing-create` treat a preserved
  EXT edit and the creation of a fresh BC as two operations. Apply binds to the
  exact preview `result.sha256`, the full input graph, the request and the
  destination. Preserve the ordered intake/outfall coordinates and BC Name =
  SourceSink ID. Add no boundary support suffix, and keep `salinity` and
  `salinityDelta` as separate names. The
  [six public-input trials](../research/notes/verification/source-sink.md#public-225)
  qualify a bounded inline 2D source case through a research runner. They do not
  qualify a public run profile or GUI export.

## Model fields and modules

- **E014** `model fields` describes MDU text only. A static editor is not a
  validated edit: read `edit_eligibility.state` and inspect the connected
  input/candidate preview ([fields](../research/notes/verification/fields.md)).
  Read [network controls](../research/notes/verification/network-exchange.md)
  before broadening the network commands.
- The [module evidence index](../research/catalog/module-gates.json) records
  raw-output checks for bounded FM–Waves exchange in both directions, in-kernel
  nitrification and BMI observation reads. Keep each profile's mechanism and
  clock: stationary Waves samples start each scheduled interval, and a process
  timer can count initialization separately from regular computation. The BMI
  clock gate checks observation reads against NetCDF storage precision. A
  successful read does not show that a controlled structure responded to a
  write.
- **Morphology:** the native signed section counters and dry stock are separate
  quantities, because a frozen MorFac=0 bed can report transport without
  updating stock. The [two-design eight-case replay](../research/notes/verification/morph-trial.md)
  checks both and joins final restart cells by physical coordinates.
- **DELWAQ 06** positive/control replay uses model-local time, 1,130 segments and
  retained volume records. Preserve duplicate non-target statistic columns by
  ordinal, and refuse a physical target name that is ambiguous.

## Releases and performance

Historical manifests stay read-only. Release scope and migration are in
[CLI 0.3 verification](../research/notes/verification/cli-03.md). For
performance work use the [0.3.1 scale benchmark](../research/notes/verification/cli-scale-031.md).
Measure MDU, NetCDF and logs in separate processes on identical inputs. When
changing the scanner, preserve diagnostic context, markers and file hashes.

## Tests

- Portable tests generate their own inputs. They need neither the installation
  nor the research artifacts, so a fresh CI environment can run them.
- Every edit change keeps exit codes and JSON errors, preview-hash checks and
  byte preservation under test.
- Keep every existing assertion. A changed contract gets a new assertion next to
  the old one, and the G review checks that all prior assertions survived.
- Execution changes need bounded integration cases. The native release check
  needs both replay commands in the [experiment index](../research/notes/experiments.md).
