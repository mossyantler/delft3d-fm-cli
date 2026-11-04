# Synthetic sigma-layer salinity channel

Two specifications are provided. [vertical-cell.json](vertical-cell.json) regenerates the three-layer, 20-second case used in the [installed CLI and solver comparison](../../research/notes/verification/layers.md#b13). The following description is for the separate four-layer [channel.json](channel.json) example.
It builds its own 120 × 40 m horizontal UGRID grid: 65 nodes, 112 edges, 48 cells,
flat bed −4 m, explicit EPSG:32631 and a declared synthetic vertical zero. Four
sigma layers have bottom-to-top thickness fractions 0.25 each. Constant vertical
viscosity is 1e-4 m²/s; constant vertical diffusivity is 1e-6 m²/s. Salinity is
active, temperature transport is off, and the density formula is UNESCO (2).

The initial salinity profile varies linearly from 30 ppt at −4 m to 10 ppt at
0 m. Both ends have matching time-zero t3D profiles defined at bed/surface
fractions 0/1, with one-based column indices. West water level rises linearly
from 0 to 0.02 m over 120 seconds; east remains at 0. Neither boundary dries.
History/map cadence is 10 seconds; final restart is requested at 120 seconds.
These are explicit synthetic test choices, not calibration recommendations.

## Create and inspect a model

Use a new directory for each case. To reproduce the three-layer input:

```powershell
dfm layers create examples/layers/vertical-cell.json --out NEW_MODEL
dfm layers inspect NEW_MODEL/model.mdu
dfm boundary vertical-inspect NEW_MODEL/model.mdu --boundary west --point west_0001 --quantity salinitybnd
dfm run start NEW_MODEL/model.mdu --profile layers --route direct --install SUITE --out NEW_RUN --timeout 45
dfm layers verify NEW_RUN/model/model.mdu
```

For the one-cell edit, see the [exact preview and apply commands](../../README.md).
To create the four-layer, 120-second example instead, pass `examples/layers/channel.json`
to `layers create`. Its authored BC positions differ from those of the three-layer
case, so inspect its signals before choosing a cell.

## Independent checks declared before native execution

1. Read NetCDF topology independently: correct one-based CCW cells, unique
   edges, known flat bed, CRS/datum, observations inside and PLI ends on exterior
   edges. Move the bundle, re-inspect and confirm every native reference resolves.
2. Read MDU/INI/BC independently, including repeated quantity/unit/index columns.
   Initial profile is elevation/salinity; BC positions are fractions from bed,
   not model sigma coordinates or zero-based column indices. Require clock and
   full forcing coverage, and exactly one signal per endpoint/quantity.
3. Existing serial markers plus decoded CF time/cadence and final restart must
   pass. The example has 13 history/map samples from 0 through 120 seconds.
4. History and map salinity must have a real four-layer dimension; physical
   center and interface coordinates must have 4 and 5 positions respectively.
   Initial interfaces are −4, −3, −2, −1, 0 m, centers −3.5, −2.5, −1.5, −0.5 m.
   Initial layer salinities are 27.5, 22.5, 17.5, 12.5 ppt. Use 1e-6 m geometry
   and 1e-5 ppt initial-value tolerances, accounting for native output precision.
5. At every output time: finite unmasked wet-column arrays, increasing interface
   elevations, center/interface consistency, positive thicknesses, layer
   fractions, bed/interface identity and surface/water-level identity. Check
   salinity stays in the supplied global [10,30] ppt envelope within 1e-5 ppt.
   Read and check layered final restart salinity too. Report the final vertical
   contrast and column integral; do not call ppt·m or ppt·m³ a mass in kg.
6. A vanishing final vertical contrast is an investigation finding, not an
   arbitrary new runner gate. Compare the raw result with the prescribed initial
   and boundary fields and fixed mixing. Do not declare scientific validity from
   file existence, dimensions or successful exit alone.

Negative cases must fail without publication/launch as appropriate: duplicate
JSON/MDU/BC identity; Kmx=0 or one-layer/percentage mismatch; zero/negative or
non-summing layer thicknesses; unsupported z layers/temperature/coupling;
nonfinite, overflow or nonzero underflow; bad units; reversed/repeated vertical
positions; wrong one-based column index; wrong time/profile width; missing
initial/profile/mesh/BC; insufficient initial-height/forcing-time coverage;
inconsistent time-zero initial/boundary profiles; out-of-domain observations;
changed staged files or clock; budget overflow; existing output. Vertical-result
corruptions should reject 2D salinity, masked/NaN cells, missing coordinates,
reversed/zero interfaces, wrong layer fraction, mismatching surface/bed, bad
initial salinity, changed salinity units and missing/early final restart.

## Sources and limits

Deltares D-Flow FM User Manual **2026.02**, revision **81168**, draft:
§10.1 printed pp.148–149 / PDF pp.174–175 (sigma/user layer distribution);
Appendix C.5 printed pp.421–425 / PDF pp.447–451 (t3D columns and vertical
positions); D.3.4 p.484 / PDF p.510 and D.4.4 p.486 / PDF p.512 (initial profile).
Technical Reference 2026.02 §7.2–7.7 pp.141–152 / PDF pp.152–163 distinguishes
layer coordinates, moving interfaces, water volume and transported quantities.

Collected official source revision
`5a4649830b1e5072caf019fb4850bbdefd9ad431`:

- `unstruc_model.f90`: 938–983 (layer settings), 1215 (turbulence),
  1368–1382 (mixing), 1408–1423 (salinity/density), 2048/2075/2118 and
  2290 (physical-coordinate/salinity output).
- `unstruc_inifields.f90`: 660–668 requires an explicit `value` for
  polygon/constant providers; 1492–1495 and 2112–2114 dispatch the 3D profile.
  Consequently `initial.ini` includes `value=0`; this is a required provider
  field, not a replacement for the profile values.
- `setinitialverticalprofile.f90`: 64–86 interpolates the first profile column
  (elevation) onto actual layer centers; its second column supplies salinity.
- `ec_bcreader.f90`: 509, 522–535 and 564–600 recognize t3D, one-based indices,
  linear interpolation and `percBed`; 681–700 distinguishes fractions/percentages.
- `unstruc_netcdf.f90`: 5451–5454 writes physical map center/interface coordinates;
  5680 writes layered salinity. `unc_write_his.F90` uses `zcoordinate_c/w`.

These sources establish intended syntax and semantics. They do not identify the
installed executable's commit or establish a successful native run. Scope is a
flat, wet, hydrostatic sigma-channel with salinity and fixed mixing. Z/z-sigma,
nonhydrostatic, heat fluxes, sediments, wet/dry, restart execution, MPI and
component coupling are separate cases. No existing user model is modified.
