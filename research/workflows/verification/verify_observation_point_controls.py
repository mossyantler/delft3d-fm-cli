"""G06 independent manual XYN/native-file oracle; no launch or editor imports.

Freeze: python -B -m research.workflows.verification.verify_observation_point_controls
  --freeze --out NEW
Replay: same module --spec independently-authored-spec.json --out NEW
Spec: source, control_inputs, control_output, cases:[{name,kind:move|add,
inputs,output,id,x,y}]. Coordinates are explicit decimal strings. Paths are
relative to the working directory. Exactly one move and one addition required.
Use profile:m3-48 for the nine-file, 120s authored UGRID channel. The default
f34 profile is retained calibration support, not the M3 acceptance target.
Native-file evidence never establishes GUI actions or process ownership.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import difflib
import hashlib
import json
import math
from pathlib import Path
import re

import netCDF4 as nc
import numpy as np

FILES = {'f34.mdu','f34.wnd','f34_001.bc','f34_001.pli','f34_bnd.ext',
         'f34_crs.pli','f34_drypoints_dry.xyz','f34_net.nc','f34_obs.xyn','f34_thd.pli'}
EPOCH = 'seconds since 1990-08-05 00:00:00'
PROFILES = {
    'f34':dict(files=FILES,obs='f34_obs.xyn',mesh='f34_net.nc',prefix='f34',epoch=EPOCH,stop=600,step=60,
               node_x='NetNode_x',node_y='NetNode_y',edges='NetLink',faces='NetElemNode',
               contour_x='FlowElemContour_x',contour_y='FlowElemContour_y',center_x='FlowElem_xcc',center_y='FlowElem_ycc',
               level='s1',face_dim='nFlowElem'),
    'm3-48':dict(files={'boundaries.bc','boundaries.ext','boundary_east.pli','boundary_west.pli','create-provenance.json',
                       'create-spec.json','mesh_net.nc','model.mdu','observations.xyn'},
                obs='observations.xyn',mesh='mesh_net.nc',prefix='model',epoch='seconds since 2001-01-01 00:00:00',stop=120,step=10,
                node_x='mesh2d_node_x',node_y='mesh2d_node_y',edges='mesh2d_edge_nodes',faces='mesh2d_face_nodes',
                contour_x='mesh2d_face_x_bnd',contour_y='mesh2d_face_y_bnd',center_x='mesh2d_face_x',center_y='mesh2d_face_y',
                level='mesh2d_s1',face_dim='mesh2d_nFaces'),
}
PLAN = {
    'version':'G06-OBS-V-3',
    'scope':'Manual authored M3 48-cell XYN move/add, direct raw files only; f34 is separate calibration. No GUI, editor, CRS correctness or native ownership claim',
    'input':'M3 exactly nine files, eight non-XYN files byte-identical; f34 calibration exactly ten/nine. Move changes only coordinate tokens of one unchanged-ID/ordinal row. Add preserves the entire original prefix and appends one explicit new-ID row.',
    'identity':'station_id authoritative, exact XYN ordinal and unique IDs; station_name displayed separately and never used to join data',
    'CF_point_geometry':'Follow waterlevel.geometry -> scalar geometry_type=point container -> node_count(station) -> node_coordinates on its actual node dimension; explicit count/offset to ID association. Exactly one finite metre XY node per point. Refuse broken descriptor, wrong count/axes/dimensions or unassociated geometry changes.',
    'CF':'Decode actual units/calendar; authoritative time 1D, finite/unmasked, no second coordinate. M3 history/map 0:10:120 from 2001-01-01, checkpoints 0/120. Separate f34 calibration 0:60:600 from 1990-08-05, checkpoints 0/600. Check referenced bounds separately.',
    'location':'Unique strictly interior 2D polygon from raw map contours; unique exact node-coordinate join handles runtime renumbering. Check mapped node connectivity against independently reconstructed bounded faces of original input edge graph; legacy cached NetElemNode differences inventoried separately. Refuse boundaries/overlap/outside; no nearest-centre guess.',
    'waterlevel':'Every CF time, finite/unmasked history waterlevel equals the corresponding map s1 after exactly one cast to history storage dtype, with equal physical units. No adjustable numerical tolerance.',
    'move_response':'Moved ID keeps ordinal, maps to a different actual cell and has at least one different stored waterlevel; all other station variables/geometry exact',
    'add_response':'Original IDs/order/rows and all their history variables exact; new station location and full waterlevel time series independently mapped',
    'm3_predeclared_controls':{'move':{'id':'centre','x':'500025.0','y':'5700015.0'},'add':{'id':'east_probe','x':'500095.0','y':'5700025.0'}},
    'm3_effect':'Both moved centre and added east_probe differ from original centre waterlevel by >=0.001m at >=3 actual CF samples; geometry targets independently confirmed strictly interior, no fit to fresh outcomes',
    'non_targets':'Full map and both restarts: all variable inventories, dtype/dimensions/metadata, masks and unmasked values exact. History non-station variables exact; per-ID unchanged station values exact. Global provenance differences inventoried separately.',
    'runtime_input_binding':'M3 source nine-file hashes prospectively pinned in independent spec. Actual run/model seven referenced native inputs must byte-match each authored case; two create metadata JSONs are not copied by public run and remain pinned in authored input inventory.',
    'geometry_boundary_guard_m':1e-7,
    'numerical_tolerance':0,
    'upstream_reference_commit':'5a4649830b1e5072caf019fb4850bbdefd9ad431',
    'engine_source_commit':'unknown',
    'negative':'Adulterated fresh copies must fail the same gates; no receipt-based acceptance',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix():digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def decimal(text):
    try:
        value = Decimal(str(text))
    except InvalidOperation as exc:
        raise ValueError('Invalid coordinate') from exc
    require(value.is_finite(), 'Nonfinite coordinate')
    return value


def read_xyn(raw):
    """Keep byte offsets and line bytes; do not normalize the original file."""
    rows = []
    offset = 0
    for line_number, line in enumerate(raw.splitlines(keepends=True), 1):
        code = line.split(b'#', 1)[0].rstrip(b'\r\n')
        if code.strip():
            match = re.fullmatch(rb"[ \t]*(\S+)[ \t]+(\S+)[ \t]+('(?:[^']+)'|[^ \t']+)[ \t]*", code)
            require(match is not None, 'Unsupported/ambiguous XYN row')
            identity = match[3].decode('utf-8')
            if identity.startswith("'"):identity=identity[1:-1]
            require(identity not in {r['id'] for r in rows}, 'Duplicate XYN ID')
            rows.append({'id':identity,'x':decimal(match[1].decode('ascii')),
                         'y':decimal(match[2].decode('ascii')),'line':line_number,
                         'spans':[(offset+match.start(i),offset+match.end(i)) for i in (1,2)],
                         'raw':line})
        offset += len(line)
    require(rows, 'Empty XYN')
    return rows


def check_inputs(source, target, edit=None, profile='f34'):
    cfg = PROFILES[profile]
    source, target = Path(source), Path(target)
    require(set(inventory(source)) == cfg['files'], 'Original input inventory differs')
    require(set(inventory(target)) == cfg['files'], 'Case input inventory differs')
    for name in cfg['files']-{cfg['obs']}:
        require((source/name).read_bytes() == (target/name).read_bytes(), 'Non-target input changed: '+name)
    before, after = (source/cfg['obs']).read_bytes(), (target/cfg['obs']).read_bytes()
    old, new = read_xyn(before), read_xyn(after)
    if edit is None:
        require(before == after, 'Control XYN differs from original')
    else:
        identity, kind = edit['id'], edit['kind']
        xy = decimal(edit['x']), decimal(edit['y'])
        if kind == 'move':
            require([r['id'] for r in new] == [r['id'] for r in old], 'Move altered ID/ordinal')
            indices = [i for i,r in enumerate(old) if r['id'] == identity]
            require(len(indices) == 1, 'Move ID absent/ambiguous')
            i = indices[0]
            require((new[i]['x'],new[i]['y']) == xy and xy != (old[i]['x'],old[i]['y']), 'Move coordinates differ from declaration or unchanged')
            # Coordinate-token widths may change; all intervening/outside bytes must stay exact.
            def outside(raw, row):
                (a,b),(c,d) = row['spans']
                return raw[:a],raw[b:c],raw[d:]
            require(outside(before,old[i]) == outside(after,new[i]), 'XYN move changed non-coordinate bytes')
        elif kind == 'add':
            require(identity not in [r['id'] for r in old], 'Added ID already exists')
            require(after.startswith(before) and before.endswith((b'\n',b'\r')), 'Addition did not preserve original XYN bytes')
            appended = read_xyn(after[len(before):])
            require(len(appended) == 1 and appended[0]['raw'] == after[len(before):], 'Addition is not exactly one data row')
            require([r['id'] for r in new] == [r['id'] for r in old]+[identity], 'Addition changed original ordinal/IDs')
            require((new[-1]['x'],new[-1]['y']) == xy, 'Added coordinates differ from declaration')
        else:
            raise ValueError('Unknown edit kind')
    return {'before_sha256':hashlib.sha256(before).hexdigest(), 'after_sha256':hashlib.sha256(after).hexdigest(),
            'other_inputs_exact':len(cfg['files'])-1,
            'xyn_diff':''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='original.xyn',tofile='case.xyn'))}


def values(var):
    var.set_auto_chartostring(False)
    a = np.ma.asarray(var[...])
    return np.asarray(a.data), np.ma.getmaskarray(a)


def finite(var):
    a,m = values(var)
    require(a.dtype.kind in 'fiu' and not m.any() and np.isfinite(a).all(), 'Masked/nonfinite physical variable: '+var.name)
    return a


def attrs(var):
    def normal(v):
        if isinstance(v,np.ndarray):return [normal(x) for x in v.tolist()] if v.ndim else normal(v.item())
        if isinstance(v,np.generic):return normal(v.item())
        if isinstance(v,bytes):return {'hex':v.hex()}
        if isinstance(v,float) and not math.isfinite(v):return {'nonfinite':str(v)}
        return v
    return {k:normal(var.getncattr(k)) for k in var.ncattrs()}


def names(var, *, unique=True):
    a,m = values(var)
    require(a.ndim == 2 and a.dtype.kind == 'S' and a.dtype.itemsize == 1, 'Expected fixed-width station characters')
    result = []
    for row, mask in zip(a,m):
        positions = np.flatnonzero(mask)
        end = int(positions[0]) if positions.size else len(row)
        require(not mask[:end].any() and (not positions.size or mask[end:].all()), 'Interior masked station character')
        require(all(x in (b'',b'\x00',b' ') for x in row[end:]), 'Masked station suffix contains identity bytes')
        raw = b''.join(row[:end]).rstrip(b'\x00 ')
        require(b'\x00' not in raw and raw, 'Invalid station identity')
        result.append(raw.decode(getattr(var,'_Encoding','utf-8')))
    require(not unique or len(result) == len(set(result)), 'Duplicate station identity')
    return result


def clock(ds, expected, epoch=EPOCH):
    require('time' in ds.variables, 'Missing CF time')
    v = ds['time']; a = finite(v).reshape(-1)
    require(v.dimensions == ('time',), 'Time must be authoritative 1D coordinate')
    bounds = getattr(v,'bounds',None)
    for name,other in ds.variables.items():
        if name not in ('time',bounds) and (getattr(other,'axis',None) == 'T' or getattr(other,'standard_name',None) == 'time' and other.dimensions == (name,)):
            raise ValueError('Ambiguous CF time coordinate')
    units, calendar = getattr(v,'units',None),getattr(v,'calendar','standard')
    require(isinstance(units,str) and ' since ' in units, 'CF units absent')
    def seconds(data):
        return np.asarray(nc.date2num(nc.num2date(data,units,calendar=calendar),epoch,calendar=calendar),dtype=float)
    t = seconds(a)
    require(np.array_equal(t,np.asarray(expected)), 'CF time coordinate differs from frozen schedule')
    result = {'units':units,'calendar':calendar,'seconds':t.tolist()}
    if bounds:
        require(bounds in ds.variables, 'Missing CF bounds')
        b = finite(ds[bounds])
        require(b.shape == (len(t),2), 'Invalid CF bounds shape')
        require(getattr(ds[bounds],'units',units) == units and getattr(ds[bounds],'calendar',calendar) == calendar, 'Bounds units/calendar differ')
        b = seconds(b)
        require(np.all(b[:,0] <= t) and np.all(t <= b[:,1]), 'CF coordinate outside bounds')
        result['bounds_seconds'] = b.tolist()
    return result


def exact_var(a,b,label):
    require(a.dimensions == b.dimensions and a.shape == b.shape and a.dtype == b.dtype, 'Variable shape/type differs: '+label)
    require(attrs(a) == attrs(b), 'Variable metadata differs: '+label)
    av,am = values(a); bv,bm = values(b)
    require(np.array_equal(am,bm), 'Variable mask differs: '+label)
    aa,bb = av[~am],bv[~bm]
    require(np.array_equal(aa,bb,equal_nan=True) if aa.dtype.kind in 'fc' else np.array_equal(aa,bb), 'Variable values differ: '+label)


def compare_full(left,right):
    with nc.Dataset(left) as a,nc.Dataset(right) as b:
        require({n:(len(v),v.isunlimited()) for n,v in a.dimensions.items()} == {n:(len(v),v.isunlimited()) for n,v in b.dimensions.items()}, 'Full-output dimensions differ')
        require(set(a.variables) == set(b.variables), 'Full-output variable inventory differs')
        for name in a.variables:exact_var(a[name],b[name],name)
        return {'variables_exact':len(a.variables),'global_attributes_equal':attrs(a) == attrs(b),
                'global_attributes_left':attrs(a),'global_attributes_right':attrs(b)}


def polygon_cell(ds,x,y,profile='f34'):
    """Independent ray crossings, with a strict boundary-distance refusal."""
    cfg = PROFILES[profile]
    xs,ys = finite(ds[cfg['contour_x']]),finite(ds[cfg['contour_y']])
    nodes,nmask = values(ds[cfg['faces']])
    nx,ny = finite(ds[cfg['node_x']]),finite(ds[cfg['node_y']])
    start = int(getattr(ds[cfg['faces']],'start_index',1))
    require(xs.shape == ys.shape and len(nodes) == len(xs), 'Contour/connectivity shape differs')
    found = []
    for k,(px,py) in enumerate(zip(xs,ys)):
        nn = nodes[k][~nmask[k]]-start
        require(len(nn) == len(px) and np.array_equal(nx[nn],px) and np.array_equal(ny[nn],py), 'Map contour differs from raw node topology')
        inside = False
        for i in range(len(px)):
            ax,ay,bx,by = px[i-1],py[i-1],px[i],py[i]
            dx,dy = bx-ax,by-ay; length = dx*dx+dy*dy
            require(length > 0, 'Degenerate polygon edge')
            f = min(1.,max(0.,((x-ax)*dx+(y-ay)*dy)/length))
            distance = math.hypot(x-ax-f*dx,y-ay-f*dy)
            require(distance > PLAN['geometry_boundary_guard_m'], 'Observation on/near ambiguous polygon boundary')
            if (ay > y) != (by > y) and x < ax+(y-ay)*dx/dy:inside = not inside
        if inside:found.append(k)
    require(len(found) == 1, 'Observation outside or in multiple physical cells')
    return found[0]


def graph_faces(x,y,links):
    """Walk directed half edges; positive-area cycles are bounded planar faces."""
    neighbours = {i:[] for i in range(len(x))}
    edge_set = set()
    for u,v in links:
        u,v = int(u),int(v)
        require(0 <= u < len(x) and 0 <= v < len(x) and u != v, 'Invalid input graph edge')
        edge = tuple(sorted((u,v)))
        require(edge not in edge_set, 'Duplicate input graph edge')
        edge_set.add(edge);neighbours[u].append(v);neighbours[v].append(u)
    for u,near in neighbours.items():near.sort(key=lambda v:math.atan2(y[v]-y[u],x[v]-x[u]))
    visited = set();faces = []
    for u,v in sorted((u,v) for u in neighbours for v in neighbours[u]):
        if (u,v) in visited:continue
        first = (u,v);edge = first;row = []
        while edge not in visited:
            visited.add(edge);a,b = edge;row.append(a)
            near = neighbours[b];edge = (b,near[(near.index(a)-1)%len(near)])
        require(edge == first, 'Input graph face walk did not close')
        area = sum(x[row[i-1]]*y[row[i]]-x[row[i]]*y[row[i-1]] for i in range(len(row)))/2
        if area > 0:
            require(len(set(row)) == len(row) and len(row) >= 3, 'Non-simple bounded input face')
            faces.append(tuple(row))
    require(faces, 'No bounded input mesh faces')
    return faces


def mesh_identity(mesh,map_ds,profile='f34'):
    cfg = PROFILES[profile]
    with nc.Dataset(mesh) as source:
        sx,sy=finite(source[cfg['node_x']]),finite(source[cfg['node_y']])
        mx,my=finite(map_ds[cfg['node_x']]),finite(map_ds[cfg['node_y']])
        original_xy=list(zip(sx.tolist(),sy.tolist()));map_xy=list(zip(mx.tolist(),my.tolist()))
        require(len(set(original_xy)) == len(original_xy) and len(set(map_xy)) == len(map_xy), 'Duplicate/ambiguous physical node coordinates')
        require(set(original_xy) == set(map_xy), 'Map nodes differ from unchanged input mesh')
        lookup={xy:i for i,xy in enumerate(original_xy)}
        node_join=[lookup[xy] for xy in map_xy]
        def rows(v):
            a,m = values(v); start = int(getattr(v,'start_index',1))
            return [tuple(int(x)-start for x in row[~mask]) for row,mask in zip(a,m)]
        def cycle(row):return min(row[i:]+row[:i] for i in range(len(row)))
        cached = [cycle(r) for r in rows(source[cfg['faces']])]
        links = finite(source[cfg['edges']])-int(getattr(source[cfg['edges']],'start_index',1))
        original = [cycle(r) for r in graph_faces(finite(source[cfg['node_x']]),finite(source[cfg['node_y']]),links)]
        actual = [cycle(tuple(node_join[n] for n in r)) for r in rows(map_ds[cfg['faces']])]
        require(len(set(actual)) == len(actual), 'Duplicate map cell identity')
        require(set(original) == set(actual), 'Map faces differ from original input graph bounded faces')
        if profile == 'm3-48':
            require(set(original) == set(cached) and len(original) == 48, 'Authored M3 input graph/cached faces differ or not 48 cells')
            require('projected_coordinate_system' in source.variables, 'Explicit M3 input CRS missing')
            crs = source['projected_coordinate_system']
            require(int(getattr(crs,'epsg',-1)) == 32631 and getattr(crs,'EPSG_code',None) == 'EPSG:32631', 'M3 input EPSG metadata differs')
        matched = []
        for row in actual:
            indices = [i for i,r in enumerate(original) if r == row]
            require(len(indices) == 1, 'Map cell has missing/ambiguous original mesh identity')
            matched.append(indices[0]+1)
        return {'map_to_reconstructed_input_face_one_based':matched,'map_input_face_node_IDs_one_based':[[n+1 for n in row] for row in actual],
                'map_node_to_input_node_one_based':[n+1 for n in node_join],
                'reconstructed_input_faces':len(original),'cached_input_NetElemNode_rows':len(cached),
                'map_faces_absent_from_input_cache_one_based':[i+1 for i,r in enumerate(actual) if r not in cached],
                'cached_NetElemNode_is_not_identity_authority':True}


def point_geometry(ds):
    """Resolve the actual CF geometry descriptor and per-station node offsets."""
    name=getattr(ds['waterlevel'],'geometry',None)
    require(isinstance(name,str) and len(name.split()) == 1 and name in ds.variables, 'CF point geometry descriptor missing/ambiguous')
    geom=ds[name]
    require(geom.ndim == 0 and getattr(geom,'geometry_type',None) == 'point', 'CF geometry is not scalar point container')
    count_name=getattr(geom,'node_count',None)
    require(isinstance(count_name,str) and count_name in ds.variables, 'CF point node_count missing')
    count=ds[count_name]
    require(count.dimensions == ('station',) and count.dtype.kind in 'iu', 'CF node_count is not indexed by station')
    counts=finite(count)
    require(np.array_equal(counts,np.ones(len(ds.dimensions['station']))), 'CF point geometry requires exactly one node per station')
    coordinate_names=getattr(geom,'node_coordinates','').split()
    require(len(coordinate_names) == 2 and len(set(coordinate_names)) == 2 and all(n in ds.variables for n in coordinate_names), 'CF point node_coordinates invalid')
    axes={};node_dim=None
    for n in coordinate_names:
        v=ds[n]
        require(len(v.dimensions) == 1 and v.dimensions[0] != 'station', 'CF node coordinate dimension invalid')
        if node_dim is None:node_dim=v.dimensions[0]
        require(v.dimensions == (node_dim,) and v.shape == (int(counts.sum()),), 'CF node count/coordinate extent differs')
        axis=getattr(v,'axis',None)
        require(axis in ('X','Y') and axis not in axes and getattr(v,'units',None) == 'm', 'CF point coordinate axes/units invalid')
        axes[axis]=n
        finite(v)
    require(set(axes) == {'X','Y'}, 'CF point XY axes missing')
    starts=np.r_[0,np.cumsum(counts)[:-1]].astype(int)
    for axis,station_coordinate in [('X','station_x_coordinate'),('Y','station_y_coordinate')]:
        require(np.array_equal(finite(ds[axes[axis]])[starts],finite(ds[station_coordinate])), 'CF geometry nodes differ from associated station coordinates')
    associated=[n for n,v in ds.variables.items() if getattr(v,'geometry',None) == name]
    require('waterlevel' in associated and all('station' in ds[n].dimensions for n in associated), 'CF geometry associated variable lacks station identity axis')
    return {'descriptor':name,'geometry_type':'point','node_count_variable':count_name,'node_dimension':node_dim,
            'node_coordinates_by_axis':axes,'node_counts':counts.tolist(),'station_node_offsets_zero_based':starts.tolist(),
            'associated_variables':associated}


def observe(inputs,output,profile='f34'):
    cfg = PROFILES[profile]
    inputs,output = Path(inputs),Path(output)
    rows = read_xyn((inputs/cfg['obs']).read_bytes())
    with nc.Dataset(output/(cfg['prefix']+'_his.nc')) as h,nc.Dataset(output/(cfg['prefix']+'_map.nc')) as m:
        expected = range(0,cfg['stop']+1,cfg['step'])
        hc,mc = clock(h,expected,cfg['epoch']),clock(m,expected,cfg['epoch'])
        require(hc['calendar'] == mc['calendar'], 'History/map calendars differ')
        ids,display = names(h['station_id']),names(h['station_name'],unique=False)
        require(ids == [r['id'] for r in rows], 'History ID/ordinal differs from XYN')
        hx,hy = finite(h['station_x_coordinate']),finite(h['station_y_coordinate'])
        require(hx.shape == hy.shape == (len(rows),), 'History coordinate shape differs')
        for n in ('station_x_coordinate','station_y_coordinate',cfg['center_x'],cfg['center_y'],cfg['contour_x'],cfg['contour_y']):
            require(getattr((h if n.startswith('station') else m)[n],'units',None) == 'm', 'Undeclared/non-metre planar coordinates')
        require(h['waterlevel'].dimensions == ('time','station') and m[cfg['level']].dimensions == ('time',cfg['face_dim']), 'Waterlevel dimensions differ')
        require(getattr(h['waterlevel'],'units',None) == getattr(m[cfg['level']],'units',None) == 'm', 'Waterlevel units differ')
        levels,map_levels = finite(h['waterlevel']),finite(m[cfg['level']])
        topo = mesh_identity(inputs/cfg['mesh'],m,profile)
        if profile == 'm3-48':
            for ds in (h,m):
                require('projected_coordinate_system' in ds.variables, 'Explicit M3 output CRS missing')
                v=ds['projected_coordinate_system']
                require(int(getattr(v,'epsg',-1)) == 32631 and getattr(v,'EPSG_code',None) == 'EPSG:32631', 'M3 output EPSG metadata differs')
        result = []
        for i,row in enumerate(rows):
            x,y = float(row['x']),float(row['y'])
            require((hx[i],hy[i]) == (x,y), 'History coordinate differs from declared XYN')
            k = polygon_cell(m,x,y,profile)
            require(np.array_equal(levels[:,i],map_levels[:,k].astype(h['waterlevel'].dtype)), 'History waterlevel differs from physical map cell at one or more CF times')
            result.append({'id':ids[i],'display_name':display[i],'ordinal_one_based':i+1,'xy':[x,y],
                           'map_cell_one_based':k+1,'input_face_node_IDs_one_based':topo['map_input_face_node_IDs_one_based'][k],
                           'map_cell_center':[float(m[cfg['center_x']][k]),float(m[cfg['center_y']][k])],
                           'all_CF_samples_exact_at_history_storage_dtype':True,'waterlevel':levels[:,i].tolist()})
        geometry=point_geometry(h)
    return {'history_clock':hc,'map_clock':mc,'stations':result,'mesh_identity':topo,'CF_point_geometry':geometry}


def compare_history(left,right,changed_id):
    with nc.Dataset(left) as a,nc.Dataset(right) as b:
        ga,gb=point_geometry(a),point_geometry(b)
        require({k:v for k,v in ga.items() if k not in ('node_counts','station_node_offsets_zero_based')} == {k:v for k,v in gb.items() if k not in ('node_counts','station_node_offsets_zero_based')}, 'CF geometry descriptor relationship differs')
        require(set(a.variables) == set(b.variables), 'History variable inventory differs')
        require(set(a.dimensions) == set(b.dimensions), 'History dimension inventory differs')
        for n in a.dimensions:
            if n not in ('station',ga['node_dimension']):
                require((len(a.dimensions[n]),a.dimensions[n].isunlimited()) == (len(b.dimensions[n]),b.dimensions[n].isunlimited()), 'Non-station history dimension differs')
        ids_a,ids_b = names(a['station_id']),names(b['station_id'])
        display_a,display_b = names(a['station_name'],unique=False),names(b['station_name'],unique=False)
        for i,identity in enumerate(ids_a):
            require(identity in ids_b and display_a[i] == display_b[ids_b.index(identity)], 'Original station display name changed')
        exact = []
        for n,va in a.variables.items():
            vb = b[n]
            require(va.dimensions == vb.dimensions and va.dtype == vb.dtype and attrs(va) == attrs(vb), 'History variable metadata differs: '+n)
            axes = [i for i,d in enumerate(va.dimensions) if d in ('station',ga['node_dimension'])]
            if not axes:
                exact_var(va,vb,n);exact.append(n);continue
            require(len(axes) == 1, 'Unsupported multi-station-axis variable')
            av,am = values(va);bv,bm = values(vb);axis = axes[0]
            for identity in ids_a:
                if identity == changed_id:continue
                require(identity in ids_b, 'Original station disappeared')
                ia,ib=ids_a.index(identity),ids_b.index(identity)
                if va.dimensions[axis] == ga['node_dimension']:
                    ia=[ga['station_node_offsets_zero_based'][ia]];ib=[gb['station_node_offsets_zero_based'][ib]]
                x = np.take(av,ia,axis=axis);y = np.take(bv,ib,axis=axis)
                xm = np.take(am,ia,axis=axis);ym = np.take(bm,ib,axis=axis)
                require(np.array_equal(xm,ym), 'Unchanged station mask differs: '+n+'/'+identity)
                require(np.array_equal(x[~xm],y[~ym],equal_nan=True) if x.dtype.kind in 'fc' else np.array_equal(x[~xm],y[~ym]), 'Unchanged station values differ: '+n+'/'+identity)
        return {'unchanged_IDs':[i for i in ids_a if i != changed_id], 'non_station_variables_exact':exact,
                'CF_point_geometry_control':ga,'CF_point_geometry_case':gb,
                'global_attributes_equal':attrs(a) == attrs(b),'global_attributes_left':attrs(a),'global_attributes_right':attrs(b)}


def restart_files(output,profile='f34'):
    cfg = PROFILES[profile]
    paths = list(Path(output).glob('*_rst.nc'));by_time = {}
    require(len(paths) == 2, 'Expected exactly two raw checkpoint files')
    for path in paths:
        with nc.Dataset(path) as ds:
            data = finite(ds['time']).reshape(-1)
            require(data.size == 1, 'Checkpoint not singleton')
            seconds = float(nc.date2num(nc.num2date(data[0],ds['time'].units,calendar=getattr(ds['time'],'calendar','standard')),cfg['epoch'],calendar=getattr(ds['time'],'calendar','standard')))
            require(seconds in (0.,cfg['stop']) and seconds not in by_time, 'Duplicate/off-axis checkpoint')
            clock(ds,[seconds],cfg['epoch'])
            by_time[seconds] = path
    require(set(by_time) == {0.,cfg['stop']}, 'Missing initial/final checkpoint')
    return by_time


def check_runtime(authored,runtime,profile):
    cfg=PROFILES[profile]
    files=cfg['files']-({'create-provenance.json','create-spec.json'} if profile == 'm3-48' else set())
    report={}
    for name in sorted(files):
        a,b=Path(authored)/name,Path(runtime)/name
        require(a.read_bytes() == b.read_bytes(), 'Runtime input differs from authored case: '+name)
        report[name]=digest(b)
    return report


def verify(spec):
    profile = spec.get('profile','f34');cfg = PROFILES[profile]
    require({c['kind'] for c in spec['cases']} == {'move','add'} and len(spec['cases']) == 2, 'Expected one move and one add')
    source,control,output = Path(spec['source']),Path(spec['control_inputs']),Path(spec['control_output'])
    if profile == 'm3-48':
        require(spec.get('expected_source_sha256') == inventory(source), 'Source differs from prospectively pinned inventory')
    result = {'profile':profile,'control_inputs':check_inputs(source,control,profile=profile),'control':observe(control,output,profile),'cases':[]}
    if profile == 'm3-48':result['control_runtime_inputs']=check_runtime(control,spec['control_runtime_inputs'],profile)
    originals = restart_files(output,profile)
    for case in spec['cases']:
        if profile == 'm3-48':
            declared=PLAN['m3_predeclared_controls'][case['kind']]
            require(case['id'] == declared['id'] and decimal(case['x']) == decimal(declared['x']) and decimal(case['y']) == decimal(declared['y']), 'M3 control differs from frozen declaration')
        item = {'name':case['name'],'kind':case['kind'],'inputs':check_inputs(source,case['inputs'],case,profile),
                'observations':observe(case['inputs'],case['output'],profile)}
        if profile == 'm3-48':item['runtime_inputs']=check_runtime(case['inputs'],case['runtime_inputs'],profile)
        item['history'] = compare_history(output/(cfg['prefix']+'_his.nc'),Path(case['output'])/(cfg['prefix']+'_his.nc'),case['id'] if case['kind'] == 'move' else None)
        item['full_map'] = compare_full(output/(cfg['prefix']+'_map.nc'),Path(case['output'])/(cfg['prefix']+'_map.nc'))
        checkpoints = restart_files(case['output'],profile)
        item['full_checkpoints'] = {str(t):compare_full(originals[t],checkpoints[t]) for t in originals}
        if case['kind'] == 'move':
            old = next(r for r in result['control']['stations'] if r['id'] == case['id'])
            new = next(r for r in item['observations']['stations'] if r['id'] == case['id'])
            require(old['map_cell_one_based'] != new['map_cell_one_based'], 'Moved point did not change physical cell')
            require(old['waterlevel'] != new['waterlevel'], 'Moved point has no observed stored hydraulic response')
            item['changed_physical_cell_and_stored_signal'] = True
        if profile == 'm3-48':
            old=next(r for r in result['control']['stations'] if r['id'] == 'centre')
            new=next(r for r in item['observations']['stations'] if r['id'] == case['id'])
            delta=np.abs(np.asarray(new['waterlevel'])-np.asarray(old['waterlevel']))
            count=int((delta >= .001).sum())
            require(count >= 3, 'M3 stored hydraulic contrast below frozen 0.001m/3-sample criterion')
            item['causal_observation_relocation_contrast']={'samples_ge_0_001m':count,'max_abs_m':float(delta.max())}
        result['cases'].append(item)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec');parser.add_argument('--freeze',action='store_true');parser.add_argument('--out',required=True)
    args = parser.parse_args(argv)
    require(bool(args.spec) != args.freeze, 'Use exactly one of --spec/--freeze')
    out = Path(args.out).resolve()
    paths = []
    spec = None
    if args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
        paths = [Path(spec[n]).resolve() for n in ('source','control_inputs','control_output')]
        paths += [Path(c[n]).resolve() for c in spec['cases'] for n in ('inputs','output')]
        if 'control_runtime_inputs' in spec:paths.append(Path(spec['control_runtime_inputs']).resolve())
        paths += [Path(c['runtime_inputs']).resolve() for c in spec['cases'] if 'runtime_inputs' in c]
        require(all(not (out.is_relative_to(p) or p.is_relative_to(out)) for p in paths), 'Output overlaps evidence')
    out.mkdir(parents=True,exist_ok=False)
    (out/'predeclared-oracle.json').write_text(json.dumps(PLAN,indent=2),encoding='utf-8')
    receipt = {'state':'prepared_pending_native_files' if args.freeze else 'failed','native_started':False,'GUI_observed':False,
               'process_ownership':'not_assessed','verifier_sha256':digest(__file__),'oracle':PLAN}
    before = {str(p):inventory(p) for p in paths}
    if spec is not None:(out/'spec.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    code = 0
    try:
        if spec is not None:
            receipt['result'] = verify(spec);receipt['state'] = 'passed_native_file_oracle'
    except FileNotFoundError as exc:
        receipt.update(state='pending_missing_evidence',error=str(exc));code = 2
    except (ValueError,KeyError,IndexError,OSError) as exc:
        receipt.update(state='failed',error=str(exc),error_type=type(exc).__name__);code = 3
    finally:
        after = {str(p):inventory(p) for p in paths}
        receipt['evidence_hashes_before'] = before
        receipt['evidence_hashes_after'] = after
        receipt['evidence_read_only'] = before == after
        if before != after:receipt.update(state='failed',error='Evidence changed while auditing');code = 3
        (out/'verification.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'state':receipt['state'],'receipt':str(out/'verification.json'),'error':receipt.get('error')},indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
