"""Native-only closed graph for one FM total-load fraction.

Pinned Deltares 5a4649830b1e5072caf019fb4850bbdefd9ad431:
unstruc_model.f90:1508-1518; flow_sedmorinit.f90:117-148,189-220;
addopenbndsection.f90:86; rdsed.f90:659-918,2121-2154;
rdtrafrm.f90:1324-1327; rdmor.f90:725-778,850-907,1988-2047;
m_fm_bott3d.f90:924-1049 (IBedCond=5 sets inflow e_sbn; :997-1000 skips outflow).
setbedlevelfromnetfile.f90:76-132 (altitude at faces, explicit _FillValue,
nearest-neighbour association to flow cells); setbedlevelfromextfile.f90:261-269
(BedlevUni fallback). MORPH-V-native-20261104-01 observed -5 m fallback when
the otherwise correct face bed had no explicit _FillValue. rdmorlyr.f90:1324-1357
converts scalar IniSedThick in metres to available mass using CDryB.
The D-Morphology UM A.1/A.2/A.7 defines keyword SED/MOR/BCM. No D3D4
grid, dep, bcc or compiled/user-defined formula is consumed here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shlex

from .common import DfmError, sha
from .model import Mdu, clock, inspect_mdu
from .outputs import reader
from .serial_profile import LIMITS
from .morph_spec import fail, scalar, validate


@dataclass
class Block:
    kind: str
    fields: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    def one(self, key):
        values=[v for k,v in self.fields if k==key.casefold()]
        if len(values)!=1: fail('Expected one explicit unambiguous native field',dict(section=self.kind,key=key))
        return values[0]


def blocks(raw):
    result=[]
    for line in raw.decode('utf-8-sig').splitlines():
        code=line.split('#',1)[0].strip()
        if not code or code.startswith(';'): continue
        if code.startswith('['):
            if not re.fullmatch(r'\[[A-Za-z ]+\]',code): fail('Malformed native input section',code)
            result.append(Block(code[1:-1].strip().casefold()))
        elif not result: fail('Content precedes native section',code)
        elif '=' in code:
            if result[-1].rows: fail('Metadata following numeric data is unsupported')
            k,v=code.split('=',1); result[-1].fields.append((k.strip().casefold(),v.strip()))
        else: result[-1].rows.append(code)
    return result


def section(parsed, name):
    values=[b for b in parsed if b.kind==name]
    if len(values)!=1: fail('Expected exactly one native section',name)
    return values[0]


def canonical_tokens(text):
    """Ignore comments/spacing/numeric spelling, never unknown fields/rows."""
    result=[]
    real_fields={'sedd50','rhosol','cdryb','inisedthick','waterlevini','tstart','tstop','dtuser','dtmax','uniffrictcoef','hisinterval','mapinterval','rstinterval','morfac','bed','acal','cref','rhomean','ag','cflmax'}
    for original in text.splitlines():
        line=original.split('#',1)[0].strip()
        if not line or line.startswith(';'): continue
        tokens=shlex.split(line.replace('=', ' = '),posix=True)
        row=[]
        for index,token in enumerate(tokens):
            if '=' in tokens and index>1 and tokens[0].casefold() not in real_fields: row.append(token)
            elif re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?',token): row.append(scalar(token))
            else: row.append(token.casefold() if index==0 and (token.startswith('[') or '=' in tokens) else token)
        result.append(row)
    return result


def regular(path):
    absolute=Path(os.path.abspath(path))
    if absolute.is_symlink() or absolute.is_junction() or os.path.normcase(str(absolute))!=os.path.normcase(str(absolute.resolve(strict=True))) or not absolute.is_file():
        fail('Only ordinary local relocatable input paths are supported',str(path))
    return absolute.resolve(strict=True)


def mesh(path):
    nc,np=reader()
    with nc.Dataset(path) as ds:
        required={'projected_coordinate_system','mesh2d','mesh2d_node_x','mesh2d_node_y','mesh2d_node_z','mesh2d_face_x','mesh2d_face_y','mesh2d_face_z','mesh2d_face_nodes','mesh2d_edge_nodes'}
        if set(ds.variables)!=required: fail('Expected the explicit rectangle UGRID variables only',sorted(ds.variables))
        crs=ds['projected_coordinate_system']; topo=ds['mesh2d']
        if crs.ndim or getattr(crs,'epsg',None)!=32631 or getattr(crs,'EPSG_code',None)!='EPSG:32631' or getattr(crs,'grid_mapping_name',None)!='transverse_mercator': fail('Explicit EPSG:32631 CRS required')
        crs_values=dict(longitude_of_central_meridian=3.,latitude_of_projection_origin=0.,scale_factor_at_central_meridian=.9996,false_easting=500000.,false_northing=0.,semi_major_axis=6378137.,inverse_flattening=298.257223563,proj4_params='+proj=utm +zone=31 +datum=WGS84 +units=m +no_defs')
        if any(getattr(crs,k,None)!=v for k,v in crs_values.items()): fail('CRS parameters contradict the explicit EPSG identity')
        if getattr(topo,'cf_role',None)!='mesh_topology' or getattr(topo,'topology_dimension',None)!=2 or getattr(topo,'node_coordinates',None)!='mesh2d_node_x mesh2d_node_y' or getattr(topo,'face_node_connectivity',None)!='mesh2d_face_nodes' or getattr(topo,'edge_node_connectivity',None)!='mesh2d_edge_nodes': fail('Unsupported mesh topology/coordinate identity')
        datum=getattr(ds,'vertical_datum',None)
        if not isinstance(datum,str) or not datum.strip(): fail('Explicit synthetic vertical datum required')
        def array(name):
            v=ds[name]
            if v.size>LIMITS['links']*4: fail('Existing mesh array budget exceeded',name)
            a=np.ma.asarray(v[:])
            if not a.size or np.ma.getmaskarray(a).any() or not np.isfinite(a.data).all(): fail('Incomplete/nonfinite/oversize mesh array',name)
            return np.asarray(a.data)
        for loc in ('node','face'):
            for axis in ('x','y','z'):
                v=ds[f'mesh2d_{loc}_{axis}']
                if v.dimensions!=(f'mesh2d_n{loc.title()}s',) or getattr(v,'units',None)!='m' or getattr(v,'location',None)!=loc or getattr(v,'mesh',None)!='mesh2d' or getattr(v,'grid_mapping',None)!=crs.name: fail('Mesh dimension/coordinate units/identity conflict',v.name)
                if axis=='z':
                    if getattr(v,'standard_name',None)!='altitude' or getattr(v,'positive',None)!='up' or getattr(v,'vertical_datum',None)!=datum: fail('Mesh bed datum/positive convention conflict',v.name)
                elif getattr(v,'standard_name',None)!=f'projection_{axis}_coordinate': fail('Mesh coordinate standard name conflict',v.name)
        face_bed=ds['mesh2d_face_z']
        if '_FillValue' not in face_bed.ncattrs() or not np.isscalar(face_bed._FillValue) or not np.isfinite(face_bed._FillValue):
            fail('BedlevType=1 requires explicit finite face-bed _FillValue; the pinned reader otherwise skips the bed and uses BedlevUni',dict(variable=face_bed.name,source='setbedlevelfromnetfile.f90:113-115'))
        x,y,z=[array('mesh2d_node_'+axis) for axis in ('x','y','z')]
        xs,ys=np.unique(x),np.unique(y); nx,ny=len(xs)-1,len(ys)-1
        if nx<1 or ny<1 or len(x)!=(nx+1)*(ny+1) or nx*ny>LIMITS['faces'] or len(x)>LIMITS['nodes']: fail('Mesh must be a bounded complete rectangle')
        dx,dy=float(xs[1]-xs[0]),float(ys[1]-ys[0])
        if not np.allclose(np.diff(xs),dx,rtol=0,atol=1e-9) or not np.allclose(np.diff(ys),dy,rtol=0,atol=1e-9): fail('Uniform explicit cell sizes required')
        ex,ey=np.meshgrid(xs,ys)
        if not np.array_equal(x,ex.ravel()) or not np.array_equal(y,ey.ravel()): fail('Rectangle node ordering/identity differs')
        node=lambda i,j:j*(nx+1)+i+1
        faces=np.asarray([(node(i,j),node(i+1,j),node(i+1,j+1),node(i,j+1)) for j in range(ny) for i in range(nx)])
        edges=np.asarray([(node(i,j),node(i+1,j)) for j in range(ny+1) for i in range(nx)]+[(node(i,j),node(i,j+1)) for j in range(ny) for i in range(nx+1)])
        if len(edges)>LIMITS['links']: fail('Existing mesh link budget exceeded')
        for name,expected in [('face',faces),('edge',edges)]:
            v=ds[f'mesh2d_{name}_nodes']
            if getattr(v,'start_index',None)!=1 or v.dtype.kind not in 'iu' or not np.array_equal(array(v.name),expected): fail('Explicit rectangle connectivity differs',v.name)
        fx,fy,fz=[array('mesh2d_face_'+a) for a in ('x','y','z')]
        if not np.allclose(fx,x[faces-1].mean(axis=1),rtol=0,atol=1e-9) or not np.allclose(fy,y[faces-1].mean(axis=1),rtol=0,atol=1e-9): fail('Face coordinate identity differs from connectivity')
        if len(fz)!=nx*ny or not np.allclose(fz.reshape(ny,nx),fz[:nx],rtol=0,atol=1e-12): fail('Bed must be uniform across channel width')
        grid=dict(origin_m=[float(xs[0]),float(ys[0])],length_m=float(xs[-1]-xs[0]),width_m=float(ys[-1]-ys[0]),cell_size_m=[dx,dy],bed_base_m=float(min(z.min(),fz.min())),hump_height_m=float(max(z.max(),fz.max())-min(z.min(),fz.min())))
        details=dict(nodes=len(x),faces=nx*ny,links=len(edges),area_m2=dx*dy,face_x_m=fx.tolist(),face_y_m=fy.tolist(),initial_bed_m=fz.tolist(),vertical_datum=datum)
        return grid,details


def inspect_inputs(path):
    from .morph import texts, ACCEPTANCE, LIMITATIONS
    path=regular(path); root=path.parent
    if path.stat().st_size>LIMITS['text_file_bytes']: fail('MDU exceeds existing text budget')
    mdu=Mdu(path); c=clock(mdu)
    # References are closed before any generic traversal can read an unrelated file.
    fixed={'geometry/netfile':'mesh_net.nc','external forcing/extforcefilenew':'boundaries.ext','sediment/sedfile':'sediment.sed','sediment/morfile':'morphology.mor','output/obsfile':'observations.xyn'}
    exchange=bool(mdu.get('output/crsfile',''))
    if exchange: fixed['output/crsfile']='sediment_sections.pli'
    if any(mdu.get(k)!=v for k,v in fixed.items()): fail('Only the explicit standalone relative native graph is supported',fixed)
    raw={}; paths={path.name:path}
    def read(name):
        p=regular(root/name)
        if p.stat().st_size>LIMITS['text_file_bytes']: fail('Existing text-input budget exceeded',name)
        paths[name]=p; raw[name]=p.read_bytes(); return raw[name]
    raw[path.name]=mdu.raw
    sed=blocks(read('sediment.sed')); mor=blocks(read('morphology.mor')); bc=blocks(read('boundaries.bc')); ext=blocks(read('boundaries.ext'))
    grain=section(sed,'sediment'); morph=section(mor,'morphology')
    # rdsed.f90:908-919 probes TraFrm as a filename before its integer formula
    # number. An unrelated file literally named 2 would change the native graph.
    if grain.one('trafrm')!='2' or os.path.lexists(root/'2'):
        fail('MPM requires literal TraFrm=2 and no colliding file/directory named 2')
    if morph.one('bcfil')!='bedload.bcm': fail('Only the explicit zero-inflow/free-outflow BCM is supported')
    read('bedload.bcm'); read('observations.xyn')
    if exchange: read('sediment_sections.pli')
    net=regular(root/'mesh_net.nc'); paths[net.name]=net
    if net.stat().st_size>LIMITS['input_bytes']: fail('Existing graph byte budget exceeded')
    g,geometry=mesh(net)
    start=datetime.strptime(mdu.get('time/startdatetime'),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    stop=datetime.strptime(mdu.get('time/stopdatetime'),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    value=lambda key: dict(value=scalar(grain.one(key)),unit='m' if key in ('sedd50','inisedthick') else 'kg/m3')
    mode='control' if scalar(morph.one('morfac'))==0 else 'transport_disabled' if scalar(morph.one('bed'))==0 else 'mobile'
    s=dict(schema_version=1,name='native_morph',mode=mode,crs=dict(epsg=32631,kind='projected',unit='m'),vertical_datum=geometry['vertical_datum'],grid=g,
           clock=dict(start=start.isoformat(),stop=stop.isoformat(),dt_user_seconds=scalar(mdu.get('time/dtuser'))),
           output={key:scalar(mdu.get('output/'+native)) for key,native in [('history_seconds','hisinterval'),('map_seconds','mapinterval'),('restart_seconds','rstinterval')]},
           initial_water_level_m=scalar(mdu.get('geometry/waterlevini')),roughness=dict(value=scalar(mdu.get('physics/uniffrictcoef')),unit='s m-1/3'),
           grain=dict(name=grain.one('name'),type='sand',formula='meyer-peter-muller',volume_fraction=1,d50=value('sedd50'),particle_density=value('rhosol'),dry_bulk_density=value('cdryb'),initial_bed_thickness=value('inisedthick')),
           boundaries=[],observations=[],acceptance=ACCEPTANCE.copy())
    boundary_blocks=[b for b in ext if b.kind=='boundary']
    if len(boundary_blocks)!=2: fail('Exactly two hydraulic boundaries required')
    forcing=[b for b in bc if b.kind=='forcing']
    if len(forcing)!=4: fail('Exactly four endpoint timeseries blocks required')
    for index,b in enumerate(boundary_blocks):
        name=b.one('locationfile')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,18}\.pli',name): fail('Unsupported or ambiguous morphology boundary identity',name)
        content=read(name).decode('utf-8-sig').splitlines()
        if len(content)!=4 or content[0]!=Path(name).stem or content[1].split()!=['2','2']: fail('Explicit two-point PLI identity required',name)
        xy=[[scalar(v) for v in line.split()] for line in content[2:]]
        if any(len(row)!=2 for row in xy): fail('PLI requires x/y pairs')
        side='west' if xy[0][0]==g['origin_m'][0] else 'east'
        rows=[[scalar(v) for v in line.split()] for line in forcing[2*index].rows]
        s['boundaries'].append(dict(id=Path(name).stem,side=side,water_level_m=rows))
    for line in raw['observations.xyn'].decode('utf-8-sig').splitlines():
        if not line.strip(): continue
        row=shlex.split(line)
        if len(row)!=3: fail('Explicit point observations required')
        s['observations'].append(dict(id=row[2],x_m=scalar(row[0]),y_m=scalar(row[1])))
    if s['mode']=='mobile' and all(row[1]==s['initial_water_level_m'] for b in s['boundaries'] for row in b['water_level_m']): s['mode']='rest'
    validate(s)
    expected=texts(s,exchange=exchange); expected[path.name]=expected.pop('model.mdu') if path.name!='model.mdu' else expected['model.mdu']
    if set(expected)!=set(raw): fail('Native graph shape differs from the closed authored scope')
    for name,template in expected.items():
        if canonical_tokens(raw[name].decode('utf-8-sig'))!=canonical_tokens(template): fail('Unsupported native field, unit, forcing, formula or clock; exact narrow semantics required',name)
    identities=set()
    for p in paths.values():
        st=p.stat(); identity=(st.st_dev,st.st_ino)
        if identity in identities: fail('Native input roles alias the same file',str(p))
        identities.add(identity)
    report=inspect_mdu(mdu)
    allowed={'sediment/sedfile','sediment/morfile'}
    issues=[i for i in report['issues'] if not (i.get('code')=='unsupported_reference' and i.get('setting') in allowed)]
    if issues: fail('Missing or unsupported additional native references',issues)
    report['files']=[dict(path=str(p),relative_path=name,sha256=hashlib.sha256(raw[name]).hexdigest() if name in raw else sha(p),bytes=len(raw[name]) if name in raw else p.stat().st_size) for name,p in sorted(paths.items())]
    if sum(f['bytes'] for f in report['files'])>LIMITS['input_bytes']: fail('Existing combined input byte budget exceeded')
    for parent,key,name in [(path,'sediment/sedfile','sediment.sed'),(path,'sediment/morfile','morphology.mor'),(paths['morphology.mor'],'morphology/bcfil','bedload.bcm')]:
        report['references'].append({'from':str(parent),'setting':key,'value':name,'path':str(paths[name]),'exists':True})
    report['issues']=[]
    report['morph']=dict(selection='morph',clock=c,mode=s['mode'],grain=s['grain'],mesh=geometry,acceptance=ACCEPTANCE.copy(),native_spec=s,
                         sediment_units=dict(bed_elevation='m positive up',available_mass='kg m-2',bedload='kg s-1 m-1',boundary_solid_volume_flux='m3/s/m'),
                         morphology=dict(model_number=4,MorFac=0 if s['mode']=='control' else 1,bed_update=True,composition_update=True,underlayer=1,
                                         sediment_boundary_names=[b['id'] for b in s['boundaries']],
                                         boundary_mass_balance=dict(state='not_established',inflow='IBedCond=5, prescribed zero solid-volume transport',outflow='Free transport; BCM prescription skipped when u1<0',required_evidence='Source-justified native cumulative or interval-integrated normal boundary transport; instantaneous sbn is insufficient')))
    report['morph']['initial_state']=dict(
        schema_version=1,bedlevtype=1,
        bed=dict(relative_path='mesh_net.nc',variable='mesh2d_face_z',location='face',units='m',positive='up',explicit_fill_value_required=True,
                 coordinates=['mesh2d_face_x','mesh2d_face_y'],association='nearest native face coordinate to flow-cell centre; never output array index',
                 x_m=geometry['face_x_m'],y_m=geometry['face_y_m'],values_m=geometry['initial_bed_m'],
                 corner_variable='mesh2d_node_z',corner_role='Geometry metadata; not the initial BedlevType=1 cell bed'),
        material=dict(relative_path='sediment.sed',fraction=s['grain']['name'],volume_fraction=1,thickness_m=s['grain']['initial_bed_thickness']['value'],
                      dry_bulk_density_kg_m3=s['grain']['dry_bulk_density']['value'],available_mass_kg_m2=s['grain']['dry_bulk_density']['value']*s['grain']['initial_bed_thickness']['value'],
                      d50_m=s['grain']['d50']['value'],underlayer=1,bed_update=True,composition_update=True,
                      rule='IUnderLyr=1, IniSedThick[m] * CDryB[kg/m3]; particle density is not the stock conversion'))
    if exchange:
        from .morph_exchange import specification
        report['morph']['exchange']=specification(s)
        report['morph']['morphology']['boundary_mass_balance']['required_evidence']='Native cumulative history kg counters, snapped boundary/interior geometry, reverse signs, and column/global dry-stock closure'
    report['checks']=dict(syntax='passed',supported_morph_references_and_semantics='passed',engine_initialization='not_performed',simulation='not_performed',physical_validation='not_performed')
    report['limitations']=LIMITATIONS
    return report
