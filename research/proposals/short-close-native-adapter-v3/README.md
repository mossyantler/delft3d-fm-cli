# Short serial replay adapter candidate

This is the separate `NATIVE-ADAPTER-DISPOSAL-I` correction candidate based on
`../short-close-native-adapter-v2` freeze `1001d570…`. Both earlier candidates
remain unchanged. It retains the complete `*-survival-final.json` before reader
invocation and addresses the independent review's remaining disposal findings:

- An unstarted warm CLI is aborted without fabricating a native manifest or
  sending a native cancellation. The reserved one-attempt budget is not reused.
- Delivery tracks `not_attempted`, `unknown` and `delivered`. A failed pipe call
  records `command_started: null` and cannot be retried. Only a failure before
  the pipe call remains known undelivered and eligible for mandatory disposal.
- Cancellation is marked delivered after go succeeds. A pre-pipe receipt
  failure leaves disposal able to submit the actual request; uncertain delivery
  never causes a duplicate request.
- A failed observer snapshot still closes the retained query handle and records
  an unavailable final snapshot, not exit proof.
- Sharing/lock violations 32/33 while polling the manifest remain unavailable
  observations and are retained in the final adapter report. Other access
  errors still raise. The final read uses the existing bounded finish deadline.
- Observer and numerical-reader roles require their original canonical source
  paths as well as hashes; an arbitrary pinned module cannot fill either role.

These are synthetic candidate checks, pending independent verification and G
review. No native permission is granted by this folder.

Node `NATIVE-ADAPTER-I` resumes the paused native-I proposal in a separate source
folder. It is research code, not installed product code or a native execution
grant. The immutable checkpoint and old native experiment #227 remain untouched.

The runtime binding selects only the independently reviewed compatibility wheel
`e32bf84f…`, with 191 installed payload files, protocol 2 and manifest 3. There
are twelve planned cases: natural completion, bad mesh, empty BC, control,
timeout and cancellation for direct FM and DIMR. At most two native owners may
coexist and each case has one attempt. No retry, PID adoption, native kill or
replacement Job implementation exists here. The installed CLI owns each launch.

`bind_runtime.py` verifies and pins the existing isolated installation without
launching an engine. `prepare.py` prepares forty input files from the retained
#227 source graphs. The current plan is `prepared-02` in the fresh experiment
folder `SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01`; `prepared-01` is retained as an
earlier clock description. Each family changes only its declared input.

The 600-second scheduling clock is distinct from request-client warming,
request-result waiting, owner-terminal waiting and final client waiting. Each
stage has its own bound in the plan. There is no claim of 600 seconds total wall
time or 110 seconds for the entire disposal operation. Mandatory disposal is
attempted for every started owner even when readiness, audit or storage fails.
Observer handles are always released on finish errors; releasing an observer
does not establish native exit. A pre-go storage failure leaves a warm client
unstarted and abortable.

Offline validation commands use the application Python with `-I -B`:

- `run_checks.py --out <fresh experiment child>` runs the adapter's synthetic
  control-flow tests with subprocess and FFI creation blocked.
- `check_composition.py --reader-freeze <file> --reader-freeze-sha256 <hash>
  --out <fresh experiment child>` runs actual frozen-reader/adapter decisions
  on labelled metadata copies of the old raw records, including negative and
  natural-race cases. It never relabels the historical records.
- `freeze_source.py` writes one source/plan freeze for independent review.
- `check_admission.py --out <fresh experiment child>` joins the real source,
  installation and reader files while substituting explicitly synthetic lease
  data. It also checks that the actual canonical idle dispatcher refuses the
  lookalike. It grants no native authority.

`draft_grant.py` only produces `draft_NOT_AUTHORIZED`. Real execution additionally
requires the coordinator's exact offline composition review, an admitted grant
binding the source/reader/runtime/plan/output and a current exclusive lease in
the canonical dispatcher. Admission is checked before output creation or warm
CLI launch and rechecked before every owner start. Historical cleanup failures
remain failures; all original member lifetimes, original Job/collector closure,
public state, independent control survival and native numerical results are
separate gates.
