# SHORT-CLOSE rev04: auxiliary supplied-image contradiction

Private correction of independent V121 finding against immutable rev03 e4a7.
Rev03 remains 120/121 against that corpus; no expectation or input is changed.
See the preceding rev03 HANDOFF/contract02 for the complete per-member API and
lifetime/attribution/close semantics, which this amendment preserves.

The only product amendment is two lines in `_cleanup_auxiliaries` in
`run_pump_lifecycle.py`: when a top-level auxiliary `image` is supplied, require
it to equal the original retained member's capture image. A conflict or malformed
value refuses with `auxiliary_capture_image_contradiction`. This check does not
make auxiliary observations original lifetime coverage. `runs.py` is unchanged.

The actual producer invokes the auxiliary capture with data=None and currently
does not emit this top-level auxiliary image. The independent corpus supplies it
as an observed optional field. This is a conservative contradiction check, not
a claim of a newly discovered malformed #227 original receipt. Pre-request and
exit-image checks remain separate. No image is synthesized or substituted.

The added portable regression accepts the matching supplied field and refuses a
contradictory image plus None/Boolean/numeric/list/object values, checking input
immutability. All preceding 115 tests are retained; the full result is 116 tests.
No V121 verdict on these new bytes is claimed by I. Original #227 manifests,
legacy missing-original-capture negatives, root191, old wheels and frozen e4a7
are unchanged. No native/Job/GUI launch, install, wheel or package composition.

Importable API and persisted derived component remain
`native_cleanup_evidence(record)` and
`ownership.<family>_lifecycle.exit_evidence.native_cleanup_evidence`.
Actual raw original close at `ownership.job_close` is independently required;
shutdown confirmation remains distinct from kill attribution and science.

Run private checks with an existing netCDF4-capable Python:
`<python> -I -B <this-folder>/run_checks.py`.
Final exact freeze requires independent Plato/G review. Packaging, composition,
root edits and native launches remain held pending their own authorization.
