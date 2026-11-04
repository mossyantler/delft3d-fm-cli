"""Small, file-only source/sink fixtures; no native mesh or suite dependency.

Literal authored MDU/EXT/BC bytes are the oracle. mesh.nc is deliberately opaque:
these tests cover input graph preservation and authoring, never solver validity.
"""
import hashlib
import json
from pathlib import Path
import tempfile

from dfm_cli import source_sink as subject
from dfm_cli.common import DfmError
from dfm_cli.source_sink_graph import Graph

UNIT = 'seconds since 2026-01-01 00:00:00 +00:00'

MDU = '''[General]
Program = D-Flow FM
FileVersion = 1.09
PathsRelativeToParent = 0
[geometry]
NetFile = mesh.nc
Kmx = 0
[time]
RefDate = 20260101
TZone = 0
TUnit = S
StartDateTime = 20260101000000
StopDateTime = 20260101000200
[physics]
Salinity = 1
Temperature = 1
[external forcing]
ExtForceFileNew = sources.ext
[output]
OutputDir = output
ObsFile = points.xyn
'''

EXT = '''# preserve header
[General]
fileVersion = 2.02
fileType = extForce
[SourceSink]
id = Outfall+A
name = original name # keep annotation
numCoordinates = 1 # keep count note
xCoordinates = 25
yCoordinates = 15
discharge = sources.bc # Q declaration
salinityDelta = sources.bc
area = 0
[Meteo]
quantity = windxy
forcingFile = wind.wnd
forcingFileType = uniMagDir
'''

BC = '''[General]
fileVersion = 1.01
fileType = boundConds
[Forcing]
Name = Outfall+A
Function = timeseries
Time-interpolation = linear
Quantity = time
Unit = seconds since 2026-01-01 00:00:00 +00:00
Quantity = sourcesink_discharge
Unit = m3/s
Quantity = sourcesink_salinityDelta
Unit = ppt
0 0.1 5 # first literal
120 0.1 5
[Forcing]
Name = OtherConsumer
Function = constant
Quantity = waterlevelbnd
Unit = m
99
'''

def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return path

def hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


class SourceSinkFixture:
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, text in [('model.mdu', MDU), ('sources.ext', EXT), ('sources.bc', BC)]:
            (self.root / name).write_bytes(text.replace('\n', '\r\n').encode())
        for name, raw in [('mesh.nc', b'opaque mesh bytes'), ('wind.wnd', b'0 0 0\n120 0 0\n'),
                          ('points.xyn', b'25 15 near_source\n'), ('pair.pli', b'geometry-not-object-ID\n2 2\n25 15\n95 25\n')]:
            (self.root / name).write_bytes(raw)
        self.mdu = self.root / 'model.mdu'
        self.request = self.root / 'request.json'
        self.assertEqual(subject.inspect(self.mdu)['sources'][0]['id'], 'Outfall+A')
        Graph(self.mdu).ready()  # Broken positive fixtures never masquerade as refusals.

    def replace(self, name, old, new):
        p = self.root / name
        raw = p.read_bytes()
        self.assertIn(old, raw)
        p.write_bytes(raw.replace(old, new))

    def error(self, suffix, function, *args, **kwargs):
        with self.assertRaises(DfmError) as exc:
            function(*args, **kwargs)
        self.assertTrue(exc.exception.code.endswith(suffix), exc.exception.code)

    def forcing_spec(self):
        return {'version': 1, 'id': 'NewID', 'time_unit': UNIT,
                'columns': [{'quantity': 'sourcesink_salinityDelta', 'unit': 'ppt'}, {'quantity': 'sourcesink_discharge', 'unit': 'm3/s'}],
                'rows': [['0', '5', '0.1'], ['120', '15', '0.1']]}
