# Preserved boundary import

The small synthetic `fixture/` copies the input files of the parent's reviewed
three-support channel. Its shared BC has west harmonic signals and east signals
at points 1 and 3. Both example sources supply points 1 and 2. Work on a private
copy: the replay below does this automatically and never launches an engine.

```powershell
.venv/Scripts/python.exe -B examples/boundary_import/replay.py
```

The supported product commands are:

```text
dfm boundary import COPY/model.mdu --boundary east --source examples/boundary_import/signal.bc --format bc --mode replace
dfm boundary import COPY/model.mdu --boundary east --source examples/boundary_import/signal.csv --format csv --mapping examples/boundary_import/mapping.json --mode overwrite-all
```

Preview writes nothing. To apply the exact preview, repeat its arguments with
`--apply --expect-sha256 INPUT_SHA256`. The hash binds canonical input paths,
all supported MDU/EXT/PLI/BC/Meteo input bytes, source, mapping and mode. Large
inputs use streamed SHA256. Output destinations are not treated as inputs.
Unsupported input-file fields and dependency containers are refused. Every apply
rehashes actual content immediately before committing, including a no-op apply.

| Mode | east_0001 | east_0002 | east_0003 |
| --- | --- | --- | --- |
| replace | replaced | added | preserved |
| extend | preserved | added | preserved |
| overwrite-all | replaced | added | cleared |

Clearing comments each active line of the existing block, retaining its original
text and comments. Other-boundary bytes are preserved. Replacement preserves
existing metadata, whitespace and comments; surplus rows lose numeric cells only.
No function switching or implicit unit/origin conversion is supported.

Mapping version 1 explicitly declares UTC. The zone-free epoch in `mapping.json`
means UTC by this schema, never the machine's local timezone. The importer writes
`+00:00` in BC units. CSV times are offsets from that declared epoch; the MDU has
its own reference date. Full coverage of its explicit UTC start/stop is checked.
Nonzero offsets, duplicate/colliding times, nonfinite values and ambiguous support
identities are refused. Valid unmatched BC sources and unused CSV columns are
reported explicitly. Unknown source blocks are refused.

The exact preview receipt includes every affected support, source hashes, input
fingerprint and intended BC `after_sha256`. Small patch lists remain complete;
larger lists retain the first 256 spans, total/omitted counts and SHA256 of the
canonical JSON array of **all** ordered span records. Offsets describe the original
BC, not the result. A stored receipt's input hash is invocation/path specific;
moving these examples requires a fresh preview.

`portable-evidence.json` is an implementation replay receipt, not independent
verification or native evidence. `preview-receipt.json` is a real no-write preview
for this checkout. All invocation validation flags remain separate from retained
profile evidence. FM User Manual section 7.4.8.2, PDF pages 121–125 documents the
GUI import choices, but the original GUI/console import and file diff are untested.
This file-level product does not claim GUI runtime parity or scientific validity.

## Destination encoding observation

Import preserves a leading destination UTF-8 BOM. The retained native A/B gate
`B09-G-BC-BOM-01/verification.json` found that installed FM `1.2.184.Unknown`
rejects `U+FEFF[General]` (return code 1); removing only the three leading
`EF BB BF` bytes from the same model let its control complete 120 seconds.
The result and exact receipt expose `native_compatibility`: destination BOM is
reported as `known_native_marker_incompatibility`, with the suite, binary hashes
and gate. A no-BOM result reports `no_leading_utf8_bom`, which checks only that
marker and never claims initialization of the selected model.

External source/CSV/mapping BOMs are decoding markers, not copied destination
header bytes. They are reported separately. No encoding normalization occurs.
If remediation is wanted, separately author or explicitly normalize a **copy**;
this importer neither strips markers nor provides a normalization command.

The original `freeze.json` and `preview-receipt.json` remain historical revision
receipts. The current encoding-observation revision uses
`freeze-bom-observation.json` and `preview-receipt-bom-observation.json`.
