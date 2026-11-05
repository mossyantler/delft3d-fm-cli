"""Exact frozen225 comparison, unchanged function AST."""
import netCDF4
from raw_arrays import differences
GLOBAL_PROVENANCE={'history','date_created','date_modified','uuid'}
def exact(a, b):
    changes = differences(a, b, False)
    with netCDF4.Dataset(a) as aa, netCDF4.Dataset(b) as bb:
        left = {k: str(aa.getncattr(k)) for k in aa.ncattrs()}
        right = {k: str(bb.getncattr(k)) for k in bb.ncattrs()}
    metadata = [{'attribute': k, 'left': left.get(k), 'right': right.get(k), 'provenance_only': k in GLOBAL_PROVENANCE} for k in left.keys() | right.keys() if left.get(k) != right.get(k)]
    return {'passed': not changes and all((x['provenance_only'] for x in metadata)), 'all_unequal_variables': changes, 'global_attribute_differences': metadata}
