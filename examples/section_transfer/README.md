# Copy observation cross-sections

`section export` copies sections from an existing MDU's `CrsFile` to a new
standalone `.pli`. `section import` adds sections or replaces matching sections
in that existing file. These commands do not edit river cross-section profiles.
Use a build that lists both commands in `dfm schema inspect`.

This example exercises file operations only. Its mesh is an opaque placeholder,
so the generated folder is **not a model to run**. No NetCDF reader or suite
installation is needed. Use a fresh directory in an existing parent:

```powershell
python examples/section_transfer/make_example.py --out section-demo
$mdu = 'section-demo/model/model.mdu'
$inventory = dfm section export $mdu --all --out 'section-demo/exports/inventory.pli' | ConvertFrom-Json
if (-not $inventory.ok) { throw $inventory.error.message }
$inventory.result.sections | Select-Object id, vertices
```

The two full names are `Harbour entrance #1` and `Mid-channel (7,7)..(7,14)`.

## Export a whole file or selected sections

Preview, then apply the exact same request with its `input_sha256`:

```powershell
$export = @('section', 'export', $mdu, '--all', '--out', 'section-demo/exports/all.pli')
$p = dfm @export | ConvertFrom-Json
if (-not $p.ok) { throw $p.error.message }
dfm @export --apply --expect-sha256 $p.result.input_sha256

$selected = @('section', 'export', $mdu, '--id', 'Mid-channel (7,7)..(7,14)', '--id', 'Harbour entrance #1', '--out', 'section-demo/exports/selected.pli')
$p = dfm @selected | ConvertFrom-Json
if (-not $p.ok) { throw $p.error.message }
dfm @selected --apply --expect-sha256 $p.result.input_sha256
```

Every export or import requires exactly one selector: `--all` or one or more
distinct `--id` arguments. `--all` copies every byte, including file comments
and gaps. Selected export copies each selected header, count and XY rows, with
their original line endings.
It omits file comments and gaps. Despite the argument order above, the output
starts with `Harbour entrance #1`: **source-file order wins**. Names match exactly,
including case, spaces and punctuation. Repeat `--id` for different names;
duplicate selectors and mixing `--all` with `--id` are errors.

The output must not exist. Standalone export destinations and import sources
must be lowercase `.pli` paths outside the model folder, with existing parents
and no parent traversal (`..`). Quote paths containing spaces. Export never
overwrites a file, even when its contents would be identical.

## Import with an explicit name policy

Before making changes, importing the whole export back with `replace-matching`
is a no-op. Preview reports `changed: false` and `no_op: true`; apply rechecks
the inputs and leaves file identity, modification time and permissions unchanged:

```powershell
$copyBack = @('section', 'import', $mdu, '--source', 'section-demo/exports/all.pli', '--all', '--mode', 'replace-matching', '--coordinates', 'model-xy-as-is')
$p = dfm @copyBack | ConvertFrom-Json
if (-not $p.ok) { throw $p.error.message }
dfm @copyBack --apply --expect-sha256 $p.result.input_sha256
```

Choose the policy for incoming names explicitly:

| Mode | Result |
|---|---|
| `append` | Add selected new names in source order, before the destination footer. Every selected name must be new; existing or case-only collisions fail. |
| `replace-matching` | Every selected name must exactly match an existing name. Replace those sections in their destination slots; keep other sections and file comments/gaps. No new names are appended. |

```powershell
$add = @('section', 'import', $mdu, '--source', 'section-demo/incoming/new.pli', '--all', '--mode', 'append', '--coordinates', 'model-xy-as-is')
$p = dfm @add | ConvertFrom-Json
if (-not $p.ok) { throw $p.error.message }
dfm @add --apply --expect-sha256 $p.result.input_sha256

$replace = @('section', 'import', $mdu, '--source', 'section-demo/incoming/replacement.pli', '--id', 'Harbour entrance #1', '--mode', 'replace-matching', '--coordinates', 'model-xy-as-is')
$p = dfm @replace | ConvertFrom-Json
if (-not $p.ok) { throw $p.error.message }
dfm @replace --apply --expect-sha256 $p.result.input_sha256
```

`model-xy-as-is` asserts that the incoming XY values are already suitable for
this model. It performs no CRS, height-datum or unit conversion or compatibility
check. If a copied final row lacks a line ending and more bytes follow, import
adds a disclosed separator using the destination's first line-ending style.

Preview writes nothing. Its hash includes the request and connected files,
including unselected source content, identities and relevant permissions. If
anything changes, preview again; do not reuse the old hash or an inspection hash.

## File limits and evidence

Use one existing lowercase `.pli` CrsFile with an explicit path mode (0 or 1).
Its MDU reference must be one unquoted relative path without spaces or traversal.
Both selected and whole-file operations require strict validation of the complete
file: ASCII, canonical full names up to 64 bytes, contiguous two-column XY
records, finite normal numbers or zero, no duplicate/case-only names. Unsupported
unselected content is refused too. The maximum PLI size is 8 MiB, with at most
512 sections and 100,000 total vertices; `dfm schema inspect` lists further
path, numeric and graph limits. Unrelated model bytes are preserved.

These examples have portable file/CLI checks. They establish neither solver
results nor GUI standalone import/export behavior. The GUI's file formats,
name-collision policy and save timing remain unverified.
