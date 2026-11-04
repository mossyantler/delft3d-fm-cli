# Standalone boundary collection

Work with a copied model and a fresh output directory:

```text
dfm boundary export COPY/model.mdu --out NEW_COLLECTION --group-by process --process-map examples/boundary_export/process-map.json
```

Preview writes nothing. Repeat the same arguments with
`--apply --expect-sha256 HASH` using the preview's `input_sha256`.
Other grouping choices are `all`, `boundary`, and `quantity`; `--boundary LABEL`
selects one exact PLI label. Existing output directories are refused.

The compact map explicitly declares example collection groups, **not GUI process
identities**. Adjust it to cover every selected quantity; unused declarations are
reported. Without a map, non-process modes report process membership as unknown.

PLI positions and active Forcing blocks remain exact source bytes, including
support identities, units and comments. The manifest links every exported block
to its boundary, quantity, declared process and source span. This collection is
not a runnable EXT rewrite. GIS conversion and PLI replacement are separate work.

Machine-specific producer evidence is kept outside the portable examples:
[authoritative freeze](../../research/experiments/B04-EXPORT-I-freeze-01/freeze.json)
and [raw producer receipt](../../research/experiments/B04-EXPORT-I-freeze-01/producer-receipt.json).
Those files retain their original SHA256 values. Example-path receipt files are
small compatibility indexes only. No native or guest execution is performed by
this example.
