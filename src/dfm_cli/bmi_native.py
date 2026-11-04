"""Pinned narrow C ABI. FM is loaded ONLY by the isolated BMI worker."""
import ctypes as c
import math
import os
from pathlib import Path

from .common import sha
from .bmi_inputs import fail, scalar


class Native:
    def __init__(self, installation, scalars):
        if os.name != 'nt' or os.environ.get('DFM_BMI_ISOLATED_WORKER') != '1':
            fail('bmi_worker_required', 'FM DLL may only be loaded inside the isolated owned worker')
        kernels = Path(installation['kernels']).resolve(strict=True)
        selected = installation['binaries']['lib/dflowfm.dll']
        dll = Path(selected['path']).resolve(strict=True)
        if dll != (kernels/'lib/dflowfm.dll').resolve(strict=True) or sha(dll) != selected['sha256']:
            fail('bmi_binary_changed', 'Selected fixed FM library path/hash differs')
        self.directories = [os.add_dll_directory(str(kernels/p)) for p in ('lib','bin','share')]
        # Bind(C) uses C calling convention, not stdcall/WinDLL.
        self.dll = c.CDLL(str(dll))
        signatures = {'initialize':([c.c_char_p],c.c_int), 'update':([c.c_double],c.c_int),
            'finalize':([],c.c_int), 'get_var':([c.c_char_p,c.POINTER(c.c_void_p)],None),
            'set_var':([c.c_char_p,c.c_void_p],None)}
        for name in ('get_start_time','get_end_time','get_current_time','get_time_step'):
            signatures[name]=([c.POINTER(c.c_double)],None)
        for name, (args, result) in signatures.items():
            method=getattr(self.dll,name);method.argtypes=args;method.restype=result
        self.scalars=scalars;self.initialized=False;self.closed=False

    def initialize(self, filename):
        # basename only; the worker has already changed into its staged model.
        if Path(filename).name != filename:fail('invalid_bmi_input','Initialize accepts staged basename only')
        code=self.dll.initialize(filename.encode('utf-8'))
        if code != 0:fail('bmi_native_initialize','Native initialize returned nonzero',code,5)
        self.initialized=True
        return self.clock()

    def clock(self):
        result={}
        for key,name in [('start','get_start_time'),('stop','get_end_time'),('current','get_current_time'),('dt_user','get_time_step')]:
            value=c.c_double();getattr(self.dll,name)(c.byref(value));result[key]=scalar(value.value)
        return dict(result,unit='s')

    def get(self, name):
        pointer=self._pointer(name)
        value=pointer.contents.value
        if not math.isfinite(value):fail('bmi_nonfinite_scalar','Native scalar is not finite',name,5)
        return value

    def _pointer(self, name):
        declaration=self.scalars[name]
        pointer=c.c_void_p()  # refresh every read; never cache native addresses
        self.dll.get_var(declaration['get'].encode('ascii'),c.byref(pointer))
        if not pointer.value:fail('bmi_scalar_unavailable','Native scalar lookup returned null',name,5)
        return c.cast(pointer,c.POINTER(c.c_double))

    def set(self, name, value):
        declaration=self.scalars[name]
        if not declaration.get('set'):fail('bmi_read_only_scalar','Scalar is read-only',name)
        value=scalar(value)
        if not declaration['minimum'] <= value <= declaration['maximum']:
            fail('bmi_scalar_bounds','Value is outside explicit physical bounds',name)
        if declaration.get('transfer')!='dimr_address_scalar' or not name.startswith('weirs/'):
            fail('unsupported_bmi_transfer','Only explicit bounded DIMR-address weir transfer is supported')
        # Same FM-specific ABI used by pinned Dimr::receive (COMP_TYPE_FM):
        # refresh get_var address, then copy ONE double into model-owned state.
        # No address escapes this isolated worker. No set_var fallback/caching.
        self._pointer(name).contents.value=value
        actual=self.get(name)
        if actual != value:fail('bmi_set_readback','Native set did not read back exactly',{'name':name,'requested':value,'observed':actual},5)
        return actual

    def step(self, seconds):
        code=self.dll.update(c.c_double(seconds))
        if code != 0:fail('bmi_native_step','Native update returned nonzero',code,5)
        return self.clock()

    def finalize(self):
        if self.closed:return
        self.closed=True
        if self.initialized:
            code=self.dll.finalize()
            if code != 0:fail('bmi_native_finalize','Native finalize returned nonzero',code,5)
