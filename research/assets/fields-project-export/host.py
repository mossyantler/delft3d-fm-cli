# IronPython 2.7, ONLY through the reviewed disposable-guest lifecycle hook.
# FM-only E014. No P08 FM/DIMR experiment, acceptance or model mutations.
import os

fields_bundle = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
execfile(os.path.join(fields_bundle, 'runtime', 'fields_host.py'), globals())
