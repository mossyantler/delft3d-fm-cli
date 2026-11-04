"""Native diagnostics are evidence even when initialize/update return zero."""
import re
from pathlib import Path

from .common import sha
from .diagnostics import ERROR, WARNING
from .bmi_inputs import fail


def inspect(folder):
    folder=Path(folder)
    paths=[folder/'native.stdout.log',folder/'native.stderr.log',*sorted((folder/'model').rglob('*.dia'))]
    errors=[];warnings=[];files=[];error_count=0
    for path in paths:
        if not path.is_file():continue
        size=path.stat().st_size
        if size>32*1024*1024:fail('bmi_diagnostic_limit','Native log exceeds bounded scan size',str(path),5)
        with path.open('r',encoding='utf-8',errors='replace') as stream:
            for line_number,line in enumerate(stream,1):
                # Structure reader reports some rejected fields as WARNING.
                rejected_structure=bool(re.search(r'Error Reading Structure|no flow links.*structure|structure.*no flow links',line,re.I))
                item={'path':str(path),'line':line_number,'text':line.rstrip()[:2048]}
                if ERROR.search(line) or rejected_structure:
                    error_count+=1
                    if len(errors)<32:errors.append(item)
                elif WARNING.search(line) and len(warnings)<32:warnings.append(item)
        files.append({'path':str(path),'sha256':sha(path),'bytes':size})
    return {'state':'failed' if error_count else 'passed','primary_error':errors[0] if errors else None,
            'error_count':error_count,'errors':errors,'warnings':warnings,'raw_files':files,
            'scope':'native errors and structure-read rejections; no active-link/scientific proof'}


def guard(folder):
    report=inspect(folder)
    if report['state']=='failed':fail('bmi_native_diagnostic','Native error/structure rejection despite return code',report,5)
    return report
