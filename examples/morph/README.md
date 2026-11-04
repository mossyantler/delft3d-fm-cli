# Bounded FM mobile-sand response case

Revision 2 is a prospective physical-case redesign after MORPH-V slot #26.
It has not been run natively. It changes explicit model inputs; it does not
change response thresholds, morphology acceleration, runner limits, or default
hydrodynamic profiles. Retained experiment inputs/outputs remain unchanged.

## Physical design fixed before the next native trial

| Quantity | Explicit value |
| --- | --- |
| CRS / datum | EPSG:32631 metres / declared synthetic local zero |
| Domain / cells | 120 m by 40 m / 5 m by 5 m; 192 physical faces |
| Bed at cell centres | `-3 + 0.8*sin(pi*(x-500000)/120)^2` m, positive up |
| Initial free surface | +0.5 m; minimum initial analytic depth 2.7 m |
| West free surface | +0.5 to +0.55 m, linear over 30 s, then constant |
| East free surface | +0.5 to +0.45 m, linear over 30 s, then constant |
| Clock | 2001-01-01 00:00:00–00:03:00 UTC; 180 s |
| DtUser / DtMax / CFLMax | 1 s / 1 s / 0.7; actual internal step remains adaptive |
| Output | History/map every 1 s, 181 samples; final restart at 180 s |
| Fraction | Pure total-load sand, MPM `TraFrm=2`, `ACal=1`, D50=0.0002 m |
| Particle / dry bulk density | 2650 / 1600 kg/m3 |
| Available bed | 1 m; 1600 kg/m2, initial domain dry mass 7,680,000 kg |
| Update rules | `BedlevType=1`, `Conveyance2D=-1`, `IUnderLyr=1`, `BedUpd=true`, `CmpUpd=true` |

The face bed and corner bed are separate explicit arrays. Face-bed `altitude`
metadata and finite `_FillValue` are required by the pinned native initialization
path. The expected initial bed must be computed from native face coordinates,
never substituted with the first observed output. The available bed inventory
is `IniSedThick*CDryB`, not thickness multiplied by particle density.

The failed 60 s trial had 0.000637894 m maximum erosion but only
0.00000856632 m final deposition. Revision 2 increases the hump from that
trial's 0.2 m to 0.8 m and decreases total imposed head difference from 0.6 m
to 0.1 m. On the downstream half the 0.8 m bed recovery now dominates the
imposed head fall, promoting deeper flow, deceleration and lower transport
capacity away from the crest. The 30 s momentum ramp spans about 1.5 initial
shallow-water transit times; 180 s spans about nine transit times. These are
design arguments, not predictions of native acceptance or a calibrated solution.

## Controls and unchanged gates

`mobile.json` is the active case (`MorFac=1`, `Bed=1`). `control.json` changes
only `MorFac` to 0: transport may persist, while bed and stock must remain fixed.
`transport-disabled.json` changes only `Bed` to 0 with `MorFac=1`: transport,
bed change and stock change must vanish within the original tolerances.
`rest.json` keeps mobile material but holds both hydraulic boundaries at the
initial surface; only hydraulic BC bytes differ from the active native graph.

All acceptance values are unchanged: final resolved erosion AND deposition
each at least 1e-5 m; bedload at least 1e-6 kg/(m s); control bed tolerance
1e-7 m and rest/disabled transport tolerance 1e-12 kg/(m s). Stock bookkeeping
uses the original 1e-6 kg absolute floor, explicit binary64 representation
allowance, and 1e-8 relative coefficient applied to redistributed mass, not to
the multi-million-kilogram initial inventory.

Both hydraulic boundaries retain zero inflow sediment supply. In the pinned FM
implementation `IBedCond=5` is skipped at outflow. The domain is therefore open
to sediment export. Check local `delta(bodsed)=CDryB*delta(bed)` at every cell,
with areas and physical face identity established independently. Report net
stock change and measured boundary flux separately. Do not equate zero BCM or
sampled instantaneous normal transport with an integrated conservation budget.
Full mobile mass acceptance remains blocked until a source-justified native
boundary integral is available; increasing duration does not resolve that gap.

## Handoff for Nash's independent verification

Before any launch, freeze a fresh held-out active geometry and a distinct dry
bulk density without changing acceptance. Select those independently of native
results. Preserve the strong hump versus head-difference design; scale ramp and
duration with the new domain transit time while staying within the existing
600 s ceiling. Recompute expected available mass from the held-out density and
thickness, using actual cell areas. Do not assume 1600 kg/m2 or 192 cells.

Derive all four controls from each frozen geometry/material spec. Prove native
file hashes differ only in `morphology.mor:MorFac` for frozen,
`morphology.mor:Bed` for disabled, and hydraulic BC for rest. Retain finite wet
fields, initial bed/material equality, negative-stock rejection, both signed
final responses, final map/restart agreement, and dry-mass bookkeeping checks.
Evaluate the same response and stock gates on the held-out active case.

The previous native verifier hardcodes 61 samples and a 60 s restart. Its owner
must derive the expected schedule and final state from the newly frozen clock
before replay; never infer the requested clock from observed output. For this
repository case the expected schedule is 0 through 180 s inclusive.

The product offers `morph.initial_state_contract(mdu)`,
`morph.verify_fields(mdu, clock, base_verification=...)`, and
`morph.compare_fields(mobile, control)` for the separate field/influence
handshake. Independent checks must read raw native arrays and use their own
oracle. A field-check pass is not full mobile conservation acceptance;
`morph.verify_outputs` continues to refuse an unresolved boundary budget.

No separately addressable Nash chat was exposed to this worker. This handoff
is ready for the coordinator to relay and for Nash to freeze independently.

## Commands and evidence

Portable public preparation (all output directories must be new):

```powershell
.venv/Scripts/dfm.exe morph create examples/morph/mobile.json --out <new-active>
.venv/Scripts/dfm.exe morph inspect <new-active>/model.mdu
.venv/Scripts/dfm.exe morph create examples/morph/control.json --out <new-frozen>
.venv/Scripts/dfm.exe morph create examples/morph/transport-disabled.json --out <new-disabled>
.venv/Scripts/dfm.exe morph create examples/morph/rest.json --out <new-rest>
.venv/Scripts/python.exe -B -m unittest discover -s tests -p test_morph.py -v
```

Native replay requires a separately assigned exclusive slot. Keep the existing
owned-runner process lifecycle and wall-clock limits. This revision has no
native launch or physical acceptance claim.

Primary source is collected Deltares commit
`5a4649830b1e5072caf019fb4850bbdefd9ad431`, not an inferred installed-binary
commit. `morphology_kernel/src/eqtran.f90:360-369` dispatches MPM;
`tranb2.f90:67-91` supplies its excess-stress transport-capacity relation.
`morphology_io/src/rdmorlyr.f90:1324-1357` establishes initial dry stock.
FM `setbedlevelfromnetfile.f90:76-132` reads face altitude, requires explicit
fill metadata and associates by nearest face coordinates.
`m_fm_bott3d.f90:997-1000` permits free outflow despite prescribed BCM.
D-Morphology UM 2026.02 §8.7 pp92–96 (PDF pp100–104), A.1/A.2/A.7 supplies
the bed/material update meanings and SED/MOR/BCM formats.
The prior response numbers above come from retained raw slot #26 outputs under
`research/experiments/MORPH-V-native-20261104-02/active-run/model/output/`.
