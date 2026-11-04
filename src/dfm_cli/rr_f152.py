"""f152-only RR/FM preparation adapter; no subprocess/native start here.

register(groups)/execute(args): rr-f152 prepare SPEC --out NEW [--apply
--expect-sha256 HASH], inspect CASE. Common coupling_run.case_guard dispatches
rr-f152-provenance.json to guard; that module exclusively owns execution/Jobs.
The full62 source blobs are pinned/reconstructable. Native return-code/output
placeholders are not mislabeled immutable runtime inputs. Controls are authored
derivatives. Accepted fixture evidence is historical metadata; prepare/inspect
do not execute or verify an individual native run.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zlib

from .common import DfmError,inside,sha
from .coupling_common import encoded,digest
from . import rr_f152_source as source_data, rr_f152_inputs as author

SPEC='rr-f152-spec.json'
SOURCE='rr-f152-source.json'
RECEIPT=author.RECEIPT


def register(groups):
    actions=groups.add_parser('rr-f152',help='Pinned62-blob f152 RR/FM derivative preparation, no launch').add_subparsers(dest='action',required=True)
    p=actions.add_parser('prepare');p.add_argument('spec',type=Path);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--expect-sha256')
    actions.add_parser('inspect').add_argument('case',type=Path)
    return actions


def execute(args):
    if args.action=='prepare':return prepare(args.spec,args.out,args.apply,args.expect_sha256)
    return inspect(args.case)


def _error(message,details=None,code='rr_f152_input',exit_code=4):
    source_data.fail(message,details,code,exit_code)


def _original_proof(source,original,payload):
    replaced={name:base64.b64encode(zlib.compress(raw,9)).decode('ascii') for name,raw in original.items() if name not in payload or payload[name]!=raw}
    return dict(schema_version=1,source_repository='Deltares/HYDROLIB-core',revision=source_data.REVISION,
                source_root=str(source),source_files=source_data.inventory(original),
                changed_or_unstaged_originals_zlib_base64=replaced,source_only_disposition=source_data.SOURCE_ONLY)


def _receipt(payload,fingerprint):
    body=dict(schema_version=1,kind='rr_f152_prepared',input_sha256=fingerprint,files=source_data.inventory(payload))
    return dict(body,prepared_sha256=digest(body))


def _put(folder,payload):
    for name,raw in payload.items():
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)


def prepare(spec:Path,out:Path,apply=False,expect_sha256=None):
    try:
        if type(apply) is not bool:_error('apply must be boolean')
        if apply and expect_sha256 is None:_error('Applying requires the preview input_sha256',code='expected_hash_required',exit_code=2)
        spec=Path(spec).resolve(strict=True);data,raw=author.load_spec(spec)
        source,original=source_data.load(spec.parent/data['source'])
        out=Path(out)
        if os.path.lexists(out):_error('Output must be a new directory; no overwrite',str(out),'rr_f152_output_exists')
        out=out.resolve()
        if not out.parent.is_dir() or out.is_relative_to(source):_error('Output parent must exist and output must be outside source',str(out))
        payload,case_spec=author.build(original,data['role'])
        fingerprint=digest(dict(source_root=str(source),source_files=source_data.inventory(original),spec_sha256=hashlib.sha256(raw).hexdigest(),
                                role=data['role'],destination=str(out),adapter='rr_f152_v1'))
        if expect_sha256 is not None and expect_sha256!=fingerprint:_error('Preview source/spec/destination fingerprint differs',code='rr_f152_input_changed')
        proof=_original_proof(source,original,payload)
        payload[SPEC]=encoded(case_spec);payload[SOURCE]=encoded(proof)
        receipt=_receipt(payload,fingerprint);payload[RECEIPT]=encoded(receipt)
        with tempfile.TemporaryDirectory(prefix='.dfm-f152-',dir=out.parent) as tmp:
            staged=Path(tmp);_put(staged,payload);info=guard(staged)
            # Source is rechecked after preparation and immediately before publication.
            _,current=source_data.load(source)
            if current!=original or spec.read_bytes()!=raw:_error('Source/spec changed before publication',code='rr_f152_input_changed')
            if apply:
                out.mkdir(exist_ok=False);owned=[]
                try:
                    for name in sorted(payload):
                        target=out/name;target.parent.mkdir(parents=True,exist_ok=True)
                        with target.open('xb') as dst:
                            owned.append(target);dst.write(payload[name])
                        if sha(target)!=hashlib.sha256(payload[name]).hexdigest():_error('Published bytes differ',name,'rr_f152_input_changed')
                except BaseException:
                    for target in reversed(owned):target.unlink(missing_ok=True)
                    # Only remove verified owned directories, never recurse through unrelated content.
                    for parent in sorted({p.parent for p in owned},key=lambda p:len(p.parts),reverse=True):
                        while parent!=out and parent.is_relative_to(out):
                            try:parent.rmdir()
                            except OSError:break
                            parent=parent.parent
                    try:out.rmdir()
                    except OSError:pass
                    raise
        return dict(applied=apply,input_sha256=fingerprint,prepared_sha256=receipt['prepared_sha256'],directory=str(out),
                    role=data['role'],source_blob_count=62,runtime_native_inputs=len(source_data.FILES)-len(source_data.SOURCE_ONLY),
                    files=receipt['files'],profile=info['profile'],checks=info['preparation_checks'],
                    changes=[dict(relative_path=name,source_sha256=source_data.FILES[name]['sha256'],authored_sha256=hashlib.sha256(content).hexdigest()) for name,content in payload.items() if name in original and content!=original[name]],
                    observations=case_spec['observables'],native_execution='not_performed')
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,OverflowError,zlib.error) as exc:
        raise DfmError('rr_f152_prepare','Cannot prepare the pinned f152 derivative',4,str(exc)) from exc


def _read_json(path):
    from .coupling_common import load_json
    data,_=load_json(path);return data


def _reconstruct(root,proof,actual):
    if proof.get('schema_version')!=1 or proof.get('revision')!=source_data.REVISION or not isinstance(proof.get('source_files'),list) or len(proof['source_files'])!=62:
        _error('Source proof revision/cardinality differs')
    replaced=proof.get('changed_or_unstaged_originals_zlib_base64')
    if not isinstance(replaced,dict) or not set(replaced)<=set(source_data.FILES):_error('Foreign original-blob proof')
    original={}
    for name,pin in source_data.FILES.items():
        if name in replaced:
            obj=zlib.decompressobj();raw=obj.decompress(base64.b64decode(replaced[name],validate=True),pin['size']+1)
            if not obj.eof or obj.unused_data or len(raw)!=pin['size']:_error('Original blob proof is incomplete/oversize',name)
        else:
            if name not in actual:_error('Missing original/runtime input',name)
            raw=actual[name]
        if len(raw)!=pin['size'] or hashlib.sha256(raw).hexdigest()!=pin['sha256'] or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=pin['git_blob']:
            _error('Reconstructed original is not a pinned source blob',name)
        original[name]=raw
    if proof.get('source_files')!=source_data.inventory(original) or proof.get('source_only_disposition')!=source_data.SOURCE_ONLY:_error('Source provenance inventory/disposition differs')
    return original


def guard(case):
    try:
        root=Path(case).resolve(strict=True)
        if root.is_file():root=root.parent
        if (root/'coupling-provenance.json').exists():_error('Ambiguous ordinary coupling/f152 receipts')
        receipt=_read_json(root/RECEIPT)
        body={k:receipt[k] for k in ('schema_version','kind','input_sha256','files')}
        if body['schema_version']!=1 or body['kind']!='rr_f152_prepared' or digest(body)!=receipt.get('prepared_sha256'):_error('Invalid prepared receipt binding')
        entries=body['files']
        if not isinstance(entries,list) or len(entries)>100:_error('Invalid bounded prepared inventory')
        actual={};identities=set()
        for entry in entries:
            name=entry['relative_path']
            if name in actual or name==RECEIPT:_error('Duplicate/recursive prepared file identity',name)
            path=source_data.regular(inside(root,name,root=root));st=path.stat();identity=(st.st_dev,st.st_ino)
            if identity in identities:_error('Prepared inputs alias',name)
            identities.add(identity)
            if st.st_size!=entry['bytes'] or sha(path)!=entry['sha256']:_error('Prepared bytes changed',name,'rr_f152_input_changed')
            actual[name]=path.read_bytes()
        if SOURCE not in actual or SPEC not in actual:_error('Missing adapter source/spec proof')
        proof=_read_json(root/SOURCE);original=_reconstruct(root,proof,actual)
        specification=_read_json(root/SPEC)
        expected,spec_expected=author.build(original,specification.get('role'))
        if specification!=spec_expected:_error('Prepared spec changes the fixed native contract')
        if set(actual)!=set(expected)|{SOURCE,SPEC} or any(actual[name]!=raw for name,raw in expected.items()):_error('Prepared inputs differ from the pinned derivative recipe')
        from .coupling_xml import inspect as inspect_xml
        from .coupling_rr import inspect as source_audit
        inspection=inspect_xml(root/'dimr_config.xml');audit=source_audit(root/'dimr_config.xml')
        if inspection['issues']:_error('Invalid native DIMR graph',inspection['issues'])
        if audit['node_count']!=95 or audit['link_count']!=61 or len(audit['couplers'])!=2:_error('f152 RR graph identity/count differs')
        if audit['rr_clock']['step_seconds']!=300 or audit['rr_clock']['start']!='2000-01-01T00:00:00+00:00' or audit['rr_clock']['stop']!='2000-01-01T00:10:00+00:00':_error('RR component clock was not really corrected')
        if audit['fm_clock']['start']!=audit['rr_clock']['start'] or audit['fm_clock']['stop']!=audit['rr_clock']['stop']:_error('FM/RR component clock mismatch')
        from .rr_f152_slots import disposition
        fnm=disposition(root,original,actual,audit)
        unresolved=fnm['unresolved_slots'];references=fnm['slots']
        blockers=[dict(code='rr_f152_unresolved_native_reference',slots=unresolved)] if unresolved else []
        # Only the specifically reconciled generic slot issue is superseded.
        # Any other future audit error remains a real readiness blocker.
        blockers.extend(issue for issue in audit['issues'] if issue['code']!='rr_optional_slot_classification_pending')
        files=[dict(e,path=str(root/e['relative_path'])) for e in entries]
        receipt_path=source_data.regular(root/RECEIPT);files.append(dict(relative_path=RECEIPT,path=str(receipt_path),sha256=sha(receipt_path),bytes=receipt_path.stat().st_size))
        files.sort(key=lambda e:e['relative_path'])
        from .rr_f152_evidence import fixture_evidence
        evidence=fixture_evidence(specification['role'],[entry for entry in entries if entry['relative_path'] in expected])
        profile=dict(name='rr_f152',launchable=not blockers,native_gate='passed_fixture' if evidence['state']=='passed_fixture' else 'pending',evidence=evidence,
                     clock=dict(author.CLOCK),mechanism='before-master FM level -> RR completed step -> actual FM lateral discharge',readiness_blockers=blockers,
                     source_blob_count=62,runtime_native_inputs=60,source_revision=source_data.REVISION,engine_source_revision=source_data.ENGINE_SOURCE,
                     expected_outputs=dict(rr_boundary='rr/bndflodt.nc',rr_return_code='rr/sobek_3b.rtn',fm_history='fm/output/f152_his.nc',fm_map='fm/output/f152_map.nc',fm_final_restart='fm/output/moergestels_broek_20000101_001000_rst.nc'),
                     phase=specification['physics']['rr_phase'],fnm_disposition=fnm,
                     installed_engine_source_commit='unknown',scientific_validation='not_performed')
        return dict(preflight='passed',prepared_sha256=receipt['prepared_sha256'],profile=profile,files=files,spec=specification,inspection=inspection,references=references,
                    preparation_checks=dict(pinned62_source_blobs='passed',derivative_preservation='passed',component_and_controller_clocks='passed',all34_ids_each_direction='passed',
                                            native_readiness='blocked' if blockers else 'prepared_only',native_initialization='not_performed'),source_audit=audit)
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,OverflowError,zlib.error) as exc:
        raise DfmError('rr_f152_guard','Cannot establish the fixed prepared f152 graph',4,str(exc)) from exc


def inspect(case):
    info=guard(case)
    return dict(prepared_sha256=info['prepared_sha256'],profile=info['profile'],files=info['files'],checks=info['preparation_checks'],
                source_audit=info['source_audit'],references=info['references'],observables=info['spec']['observables'],native_execution='not_performed')


def observe(path,observable,clock,case):
    from .rr_f152_outputs import observe as read_native
    return read_native(Path(path),observable,clock,case)
