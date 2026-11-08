"""Write a fresh, file-only cross-section transfer example. Never runs FM."""
import argparse
import json
from pathlib import Path


def create_fixture(out):
    out = Path(out).absolute()
    # Check first: never overwrite an existing example or create its parents.
    out.mkdir(mode=0o777)
    for folder in ('model', 'incoming', 'exports'):
        (out/folder).mkdir(mode=0o777)
    files = {
        'model/model.mdu': (
            b'\xef\xbb\xbf# file-only example\r\n[general]\r\nPathsRelativeToParent = 0\r\n'
            b'[geometry]\r\nNetFile = mesh.nc\r\n[output]\r\nCrsFile = sections.pli # keep\r\n'
            b'[custom]\r\nLabel = first\r\n[custom]\r\nLabel = second\r\n'),
        'model/mesh.nc': b'Opaque example leaf, deliberately not a NetCDF model. Do not run FM.\n',
        'model/sections.pli': (
            b'* section file\r\nHarbour entrance #1\r\n2 2\r\n0.000 0.0\r\n0.0 10.0\r\n'
            b'\r\n* gap belongs to the file\nMid-channel (7,7)..(7,14)\n3 2\n5 0\n5 5\n5 10\n'
            b'\n* keep footer\r\n'),
        'incoming/new.pli': b'* survey note\nSurvey east\n2 2\n10.0 0\n10.0 10.0',
        'incoming/replacement.pli': b'* incoming note\nHarbour entrance #1\n2 2\n-5 0\n-5 10',
    }
    for name, data in files.items():
        with (out/name).open('xb') as stream:
            stream.write(data)
    return {'model': str(out/'model/model.mdu'), 'new_sections': str(out/'incoming/new.pli'),
            'replacement': str(out/'incoming/replacement.pli'), 'exports': str(out/'exports')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New directory in an existing parent')
    args = parser.parse_args()
    print(json.dumps(create_fixture(args.out)))
