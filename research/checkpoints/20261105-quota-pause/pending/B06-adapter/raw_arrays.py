"""Independent raw-array helpers copied from frozen V source, never product/I. No launches."""
from pathlib import Path
import hashlib,json
from provenance import need
class Missing(ValueError):pass

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def plain(path):
    path=Path(path).absolute()
    for part in (path,*path.parents):
        if part.is_symlink() or getattr(part.lstat(),'st_file_attributes',0)&0x400:raise ValueError('aliased raw path')
    return path

def load(path):return json.loads(plain(path).read_text(encoding='utf-8'))

def inventory(ds):
    import numpy as np
    result={}
    for name,var in ds.variables.items():
        data=var[:];mask=np.ma.getmaskarray(data)
        item={'dimensions':list(var.dimensions),'shape':list(var.shape),'dtype':str(var.dtype),
              'units':getattr(var,'units',None),'masked_samples':int(mask.sum()),
              'attributes':{k:str(var.getncattr(k)) for k in var.ncattrs()}}
        if np.issubdtype(data.dtype,np.number):
            raw=np.ma.getdata(data);good=~mask & np.isfinite(raw)
            item.update(finite_samples=int(good.sum()),nonfinite_unmasked=int((~mask & ~np.isfinite(raw)).sum()))
            if good.any():item.update(min=float(raw[good].min()),max=float(raw[good].max()))
        result[name]=item
    return result

def clock(ds,expected):
    import netCDF4
    import numpy as np
    if 'time' not in ds.variables:raise Missing('native time variable absent')
    var=ds['time'];raw=var[:]
    if var.ndim!=1 or np.ma.getmaskarray(raw).any():raise ValueError('time shape/mask')
    calendar=getattr(var,'calendar','standard')
    if calendar not in {'standard','gregorian','proleptic_gregorian'}:raise ValueError('unqualified native calendar')
    if not getattr(var,'units',None):raise Missing('native CF time units absent')
    dates=netCDF4.num2date(raw,var.units,calendar=calendar)
    seconds=np.asarray(netCDF4.date2num(dates,'seconds since 2001-01-01 00:00:00 +00:00',calendar=calendar),dtype=float)
    need(len(seconds)==len(expected) and np.isfinite(seconds).all() and np.allclose(seconds,expected,rtol=0,atol=1e-6),'native time axis missing/mismatched/truncated')
    need(len(seconds)<2 or np.all(np.diff(seconds)>0),'native repeated/reversed clock')
    return seconds

def field(ds,names,units,shape):
    import numpy as np
    hits=[n for n in names if n in ds.variables]
    if len(hits)!=1:raise Missing('required native field absent/ambiguous: '+','.join(names))
    var=ds[hits[0]];need(getattr(var,'units',None) in units,'native field units mismatch: '+hits[0])
    data=var[:]
    if 'time' in var.dimensions:data=np.moveaxis(data,var.dimensions.index('time'),0)
    need(data.shape==shape,'required native field shape: '+hits[0])
    need(not np.ma.getmaskarray(data).any() and np.isfinite(np.ma.getdata(data)).all(),'required native field has missing/nonfinite samples:'+hits[0])
    return hits[0],np.asarray(data,dtype=float)

def one_file(output,pattern):
    hits=list(output.glob(pattern))
    if len(hits)!=1:raise Missing('require exactly one raw '+pattern)
    return plain(hits[0])

def differences(path_a,path_b,salt_allowed):
    import netCDF4
    import numpy as np
    result=[]
    with netCDF4.Dataset(path_a) as a,netCDF4.Dataset(path_b) as b:
        need(set(a.variables)==set(b.variables),'paired variable schema differs')
        need({k:len(v) for k,v in a.dimensions.items()}=={k:len(v) for k,v in b.dimensions.items()},'paired dimensions differ')
        for name in a.variables:
            av,bv=a[name],b[name];need(av.dimensions==bv.dimensions and av.shape==bv.shape,'paired variable dimensions:'+name)
            need(av.dtype==bv.dtype,'paired variable storage dtype:'+name)
            need({k:str(av.getncattr(k)) for k in av.ncattrs()}=={k:str(bv.getncattr(k)) for k in bv.ncattrs()},'paired variable attributes:'+name)
            aa,bb=av[:],bv[:];mask_a,mask_b=np.ma.getmaskarray(aa),np.ma.getmaskarray(bb)
            masks=int(np.count_nonzero(mask_a!=mask_b));valid=~mask_a & ~mask_b
            raw_a,raw_b=np.ma.getdata(aa),np.ma.getdata(bb)
            numeric=np.issubdtype(raw_a.dtype,np.number)
            if numeric:
                nonfinite=int(np.count_nonzero(valid & (~np.isfinite(raw_a)|~np.isfinite(raw_b))))
                unequal=valid & (raw_a!=raw_b);delta=np.abs(raw_a.astype(float)-raw_b.astype(float))
                key=name.removeprefix('mesh2d_').lower()
                tol=(2e-6 if key in {'s0','s1','waterlevel','sa1','salinity'} else .0001 if key=='vol1'
                     else 1e-6 if key in {'u1','ucx','ucy','velocity'} else 1e-5 if key in {'q1','flux'} else 0)
                outside=valid & (delta>tol)
            else:
                unequal=valid & (raw_a!=raw_b);outside=unequal;nonfinite=0;tol=0
            count=int(np.count_nonzero(unequal))
            if count or masks or nonfinite:
                allowed=salt_allowed and name.removeprefix('mesh2d_').lower() in {'sa1','sa0','salinity','source_sink_prescribed_salinity_increment'}
                item={'variable':name,'unequal_samples':count,'mask_mismatches':masks,'nonfinite_unmasked':nonfinite,
                      'outside_numeric_tolerance':int(np.count_nonzero(outside)),'absolute_tolerance':tol,
                      'expected_salinity_contrast':bool(allowed),'first_indices':np.argwhere(unequal)[:8].tolist()}
                if numeric and np.any(unequal & np.isfinite(delta)):item['max_abs_difference']=float(delta[unequal & np.isfinite(delta)].max())
                if 'time' in av.dimensions:
                    axis=av.dimensions.index('time');different=np.moveaxis(unequal,axis,0).reshape((av.shape[axis],-1)).sum(axis=1)
                    missing=np.moveaxis(mask_a!=mask_b,axis,0).reshape((av.shape[axis],-1)).sum(axis=1)
                    item['time_domain']=[{'time_index':i,'native_time_value':float(a['time'][i]),
                                          'unequal_samples':int(different[i]),'mask_mismatches':int(missing[i])}
                                         for i in range(len(different)) if different[i] or missing[i]]
                    item['native_time_units']=a['time'].units
                item['passed']=not masks and not nonfinite and (allowed or not item['outside_numeric_tolerance'])
                result.append(item)
    return result
