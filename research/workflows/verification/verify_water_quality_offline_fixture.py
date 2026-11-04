"""Small independent int32/real32 STREAM fixtures; never native evidence."""
from pathlib import Path
import struct


def write_series(path, width=12, times=(45000, 45900, 46800, 47700, 48600), volume=True):
    with Path(path).open("wb") as stream:
        for tick in times:
            values = [(i + 1) * 10. + (tick - 45000) / 900 for i in range(width)] if volume else [0.] * width
            stream.write(struct.pack("<i", tick))
            stream.write(struct.pack("<" + str(width) + "f", *values))


def write_output(path, positive=False, history=False, cells=12, duration=3600, cadence=300, zero_history=False):
    names = ("Salinity", "IM1", "EColi", "ExtUv", "MrtToEColi", "SURF", "LocalDepth")
    header = ("INDEPENDENT SYNTHETIC READER TEST", "Not a native or calibrated prediction", "Controlled stream layout",
              "T0: 1990.08.05 00:00:00  (scu=       1s)")
    raw = bytearray(b"".join(item.encode().ljust(40) for item in header))
    raw.extend(struct.pack("<2i", len(names), cells))
    raw.extend(b"".join(name.encode().ljust(20) for name in names))
    if history:
        for i in range(cells):
            raw.extend(struct.pack("<i", i + 1) + ("sample " + str(i + 1)).encode().ljust(20))
    for offset in range(0, duration + 1, cadence):
        raw.extend(struct.pack("<i", 45000 + offset))
        for i in range(cells):
            ecoli = 0. if zero_history else offset / 300 * (i + 1)
            if positive:
                ecoli *= .99
            mortality = 1.2 + (.8 * 1.07 ** -2 if positive else 0.)
            # Deliberately nonuniform concentrations/volumes expose cell-average
            # substitutions in an inventory calculation.
            values = (35., 10. + i, ecoli, .1, mortality, 10., 1. + .1 * i)
            raw.extend(struct.pack("<7f", *values))
    Path(path).write_bytes(raw)
