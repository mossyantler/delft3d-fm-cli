"""Bounded RR-local cause attribution for the owned coupling controller.

The fixed f152 FNM22 names sobek_3b.log; root DIMR diagnostics can contain only
the propagated abort. Read the staged component log, preserve its raw hash and
context, and distinguish warnings from actual ERROR/FATAL lines. No input edits,
ambient log discovery, native launches, or rewriting of historical manifests.
"""
from collections import deque
import hashlib
from pathlib import Path

from .common import DfmError
from .coupling_references import ordinary
from .diagnostics import ERROR,WARNING,LIMIT,WIDTH

MAX_BYTES=32*1024*1024


def collect(folder,manifest,digests):
    rr=[c for c in manifest.get('coupling',{}).get('spec',{}).get('components',[]) if c['library']=='rr_dll']
    if not rr:return digests
    root=Path(folder)/'model';diagnostics=manifest['diagnostics'];logs=[]
    diagnostics['component_logs']=logs
    for component in rr:
        base={'component':component['name'],'library':'rr_dll','role':'native RR local diagnostic',
            'path':str(root/component['working_dir']/'sobek_3b.log')}
        candidate=Path(base['path'])
        if not candidate.exists() and not candidate.is_symlink() and not candidate.is_junction():
            logs.append({**base,'state':'not_present'});continue
        try:path=ordinary(root,root/component['working_dir'],'sobek_3b.log')
        except DfmError as exc:
            logs.append({**base,'state':'unavailable','error_code':exc.code,'message':str(exc)});continue
        before=path.stat()
        if before.st_size>MAX_BYTES:
            logs.append({**base,'state':'scan_incomplete','bytes':before.st_size,'maximum_bytes':MAX_BYTES});continue
        errors=[];warnings=[];counts={'errors':0,'warnings':0};previous=deque(maxlen=2);pending=[];clipped=0
        scanned=0;hasher=hashlib.sha256();complete=True
        with path.open('rb') as stream:
            for number,raw in enumerate(iter(lambda:stream.readline(MAX_BYTES-scanned+1),b''),1):
                scanned+=len(raw)
                if scanned>MAX_BYTES:complete=False;break
                hasher.update(raw)
                line=raw.decode('utf-8',errors='replace').rstrip('\r\n');excerpt=line[:WIDTH]
                clipped+=len(line)>WIDTH
                for entry in pending:entry['context'].append(excerpt)
                pending=[entry for entry in pending if number<entry['line']+2]
                severity='error' if ERROR.search(line) else 'warning' if WARNING.search(line) else None
                if severity:
                    category=severity+'s';counts[category]+=1;target=errors if severity=='error' else warnings
                    if len(target)<LIMIT:
                        entry={**base,'line':number,'text':excerpt,'severity':severity,'context':[*previous,excerpt]}
                        target.append(entry);pending.append(entry)
                previous.append(excerpt)
        digest=hasher.hexdigest() if complete else None;after=path.stat();stable=(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
        if digest is not None:digests[path]=digest
        logs.append({**base,'state':'scan_incomplete' if not complete else 'captured' if stable else 'changed_during_scan','bytes':after.st_size,'sha256':digest,
            'error_lines':errors,'warning_lines':warnings,'counts':counts,'clipped_source_lines':clipped,
            'limits':{'entries_per_list':LIMIT,'characters_per_line':WIDTH,'context_each_side':2,'maximum_bytes':MAX_BYTES}})
        if errors:
            # Keep the propagated controller abort separately from component cause.
            if 'controller_primary_error' not in diagnostics:
                diagnostics['controller_primary_error']=diagnostics.get('primary_error')
            if diagnostics.get('primary_component_error') is None:
                diagnostics['primary_component_error']={**errors[0],'sha256':digest}
                diagnostics['primary_error']=diagnostics['primary_component_error']
            existing=diagnostics.setdefault('error_lines',[]);room=max(0,LIMIT-len(existing));existing.extend(errors[:room])
            diagnostics.setdefault('omitted',{}).setdefault('error_lines',0)
            diagnostics['omitted']['error_lines']+=counts['errors']-min(room,len(errors))
            # FM's initialization marker remains separately recorded. A local
            # ERROR is not by itself enough to infer RR's failure phase.
            manifest['validation']['component_diagnostics']='failed_native_RR_diagnostic'
        manifest.setdefault('component_diagnostic_status',{})[component['name']]={
            'state':'native_error' if errors else 'no_ERROR_FATAL_observed' if stable else 'unconfirmed',
            'path':base['path'],'sha256':digest,'native_finalization':'not_inferred_from_log'}
    return digests
