# Bounded coupling fixtures

`waves.json` describes the standalone Waves example. Discover each profile's
separate evidence and launch eligibility with `dfm coupling profiles`.

## Official10 FM–RTC pair

The public author creates a bounded derivative of the pinned official10 input
tree, with FM and RTC only. `SOURCE` contains its `fm/` and `rtc/` directories.
Preview and apply to a fresh folder:

```powershell
dfm coupling rtc-pair SOURCE --out NEW_BUNDLE
dfm coupling rtc-pair SOURCE --out NEW_BUNDLE --apply --expect-sha256 HASH_FROM_PREVIEW
dfm coupling prepare NEW_BUNDLE/spec-control.json --out NEW_CONTROL
dfm coupling prepare NEW_BUNDLE/spec-control.json --out NEW_CONTROL --apply --expect-sha256 HASH_FROM_PREVIEW
```

Prepare `spec-shifted.json` in another new folder using its own preview hash.
`dfm coupling plan CASE --out NEW_PLAN --install SUITE --timeout 60` stages and
checks inputs and binaries without starting a native process. Native runs require
a separately allocated coordinator lease and fresh output folders.

The author preserves the explicit synthetic storm, UTC 0–600-second clock and
60-second cadence in both cases. Only the lookup's y values differ by +0.25 m.
Incremental RTC uses `limitedMemory=true` and reads received slot n with
`EXPLICIT`; native streamed CSV is the output observable. PI export is unavailable
in this mode.

The coordinator accepted the bounded live exchange and causal hydraulic gate in
`RTC-G-exchange-01` (#68), following independent #67. Each arm has ten transfers at
0–540 seconds, with actual receipt, lookup evaluation, output and applied FM crest
at 60–600 seconds. Both owned DIMR/cmd.exe member exits were verified separately.

The final signed discharge uses 50 fixed topology-derived map links across the
weir, oriented Upstream to Downstream: control 63011.093017578125 m³/s and changed
58631.78076171875 m³/s. Changed-minus-control final crest is +0.31801366806030273 m
and Downstream water level is −0.10158085823059082 m. Raw history discharge has
four masked control samples and five masked changed samples; those remain missing.
The map section is a distinct observable and does not fill those history values.

The native 600-second hydraulic checkpoint matches all 2,500 water levels and
4,950 flow-link discharges through physical/topology mapping and exact projection
to map float storage. The 150 additional map closed edges remain actual zeros.

**Saved actuator restore is not established.** The legacy 34-variable restart
contains no actuator/crest state. History's live crest is not a saved restart
value. Overall evidence remains partial: the live gate passed; actuator save/restore,
RTC cancellation/timeout/isolation, broader models and scientific accuracy remain
pending. Earlier failed trials remain unchanged.
