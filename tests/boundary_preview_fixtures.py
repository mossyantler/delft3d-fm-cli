"""Portable authored boundary-preview inputs; not an engine-ready model."""
from pathlib import Path

BOUNDARY="east.edge+1"
POINT=BOUNDARY+"_0001"
REQUEST_UNIT="seconds since 2001-01-01 00:00:00 +00:00"
BC_UNIT="minutes since 2000-12-31 23:58:00 +00:00"
MDU="""# B12 authored input-reader fixture; opaque mesh, NEVER launch.
# CRS EPSG:32631; synthetic local zero, no geodetic vertical realization.
[General]
Program = D-Flow FM
FileVersion = 1.09
FileType = modelDef
PathsRelativeToParent = 0
[geometry]
NetFile = opaque-mesh.nc
Kmx = 0
[time]
RefDate = 20010101
TZone = 0
TUnit = S
TStart = 0
TStop = 240
StartDateTime = 20010101000000
StopDateTime = 20010101000400
DtUser = 1
[external forcing]
ExtForceFile =
ExtForceFileNew = boundary.ext
[output]
HisInterval = 1
MapInterval = 1
"""
EXT="""[General]
fileVersion = 2.01
fileType = extForce
[Boundary]
quantity = waterlevelbnd
locationFile = east.pli
forcingFile = signal.bc
"""
PLI=BOUNDARY+"\n3 2\n500120 5700000\n500120 5700020\n500120 5700040\n"
GENERAL="[General]\nfileVersion = 1.01\nfileType = boundConds\n"
LINEAR=f"""[Forcing]
Name = {POINT}
Function = timeseries
Time-interpolation = linear
Factor = 2
Offset = -0.5
Quantity = time
Unit = {BC_UNIT}
Quantity = waterlevelbnd
Unit = m
2 1 # first exact endpoint; preserve comment
3 4
6 -2 # final exact endpoint
"""
CONSTANT=f"""[Forcing]
Name = {BOUNDARY}_0002
Function = constant
Quantity = waterlevelbnd
Unit = m
0.75
"""
ORPHAN="""[Forcing]
Name = unreferenced+point_0001
Function = constant
Quantity = waterlevelbnd
Unit = m
99
"""
HARMONIC=f"""[Forcing]
Name = {POINT}
Function = harmonic
Quantity = harmonic component
Unit = minutes
Quantity = waterlevelbnd amplitude
Unit = m
Quantity = waterlevelbnd phase
Unit = degrees
2 2 90
"""
def create(folder,variant="linear"):
    folder=Path(folder);folder.mkdir()
    data={"model.mdu":MDU.encode(),"boundary.ext":EXT.encode(),"east.pli":PLI.encode(),"opaque-mesh.nc":b"Opaque read-only placeholder; not a native NetCDF mesh\n"}
    signal=GENERAL+(HARMONIC if variant.startswith("harmonic") else LINEAR)+CONSTANT+ORPHAN
    if variant=="harmonic_components":signal=signal.replace("2 2 90\n","2 2 90\n4 1 0\n")
    if variant=="harmonic_coefficients":signal=signal.replace("Function = harmonic\n","Function = harmonic\nFactor = 3\nOffset = 99\n")
    if variant=="shifted_harmonic_start":data["model.mdu"]=data["model.mdu"].replace(b"20010101000000",b"20010101000030");signal=GENERAL+HARMONIC+CONSTANT
    if variant=="two_quantities":
        data["boundary.ext"]+=b"[Boundary]\nquantity = salinitybnd\nlocationFile = east.pli\nforcingFile = signal.bc\n"
        signal+=f"[Forcing]\nName = {POINT}\nFunction = constant\nQuantity = salinitybnd\nUnit = ppt\n10\n"
    if variant=="empty":signal+=f"[Forcing]\nName = {BOUNDARY}_0003\nFunction = timeseries\nTime-interpolation = linear\nQuantity = time\nUnit = {BC_UNIT}\nQuantity = waterlevelbnd\nUnit = m\n"
    if variant=="duplicate":signal+=LINEAR
    data["signal.bc"]=signal.replace("\n","\r\n").encode()
    for name,raw in data.items():(folder/name).write_bytes(raw)
    return folder/"model.mdu"
