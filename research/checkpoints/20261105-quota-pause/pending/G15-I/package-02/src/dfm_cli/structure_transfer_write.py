"""Reviewed one-file writer and explicit owned/exclusive collection adapter.

Directory adapter reuses B04 ownership verification/cleanup, adding file and
directory security capture BEFORE payload, pinned parent and truthful outcomes.
No final collection is deleted after publication, even on failed verification.
"""
import ctypes
import os
from pathlib import Path
import sys
import tempfile

from .common import DfmError
from .boundary_support_write import parent_guard
from .boundary_export_stage import OwnedStage,identity
from . import pump_edit_write as file_writer,pump_edit_security as security
from .structure_transfer_contract import fail
from .structure_transfer_paths import plain,relative,access
from .structure_transfer_text import sha


class CollectionStage(OwnedStage):
    def __init__(self,path):
        super().__init__(path);self.security={'':access(self.root)}

    def write(self,relative_name,raw):
        path=Path(relative_name)
        if path.is_absolute() or '..' in path.parts or not self.owned_root():fail('stage','Unsafe or reassigned owned collection stage',exit_code=4)
        # Same captured directory/file bookkeeping consumed by original B04
        # verify/cleanup. Fresh file access is observed before writing any data.
        current=Path('.')
        for part in path.parent.parts:
            current=current/part;key=current.as_posix();folder=self.root/current
            if key not in self.directories:
                if not self.parents_owned(key):fail('stage','Parent reassigned before child creation',exit_code=4)
                folder.mkdir();captured=identity(folder,True)
                if captured is None:fail('stage','Cannot capture created directory',exit_code=4)
                self.directories[key]=captured;self.security[key]=access(folder)
        if not self.parents_owned(relative_name):fail('stage','Stage parent identity changed',exit_code=4)
        target=self.root/path
        with target.open('xb') as stream:
            info=os.fstat(stream.fileno());self.files[relative_name]={'identity':(info.st_dev,info.st_ino),'sha256':sha(raw),'bytes':len(raw)}
            self.security[relative_name]=access(target)
            stream.write(raw);stream.flush();os.fsync(stream.fileno())

    def verify(self):
        super().verify()
        for name,expected in self.security.items():
            if access(self.root/name)!=expected:fail('stage_security','Owned collection metadata changed',name,4)


def _make_stage(parent):
    # Retain B04's reviewed prefix admission, not an unreviewed global rebind.
    return CollectionStage(Path(tempfile.mkdtemp(prefix='.dfm-boundary-export-structure-',dir=parent)))


def _exclusive_supported():
    if os.name=='nt':return
    if sys.platform.startswith('linux') and hasattr(ctypes.CDLL(None,use_errno=True),'renameat2'):return
    fail('platform','No qualified exclusive-directory publication primitive on this platform')


def _commit_new_directory(source,out):
    if os.name=='nt':os.rename(source,out);return  # Windows: existing name fails.
    libc=ctypes.CDLL(None,use_errno=True);call=libc.renameat2
    call.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];call.restype=ctypes.c_int
    if call(-100,os.fsencode(source),-100,os.fsencode(out),1):
        error=ctypes.get_errno();raise OSError(error,os.strerror(error),str(out))


def _root_identity(path):
    try:return identity(plain(path),True)
    except (OSError,DfmError):return None


def _owned_stage(stage):
    try:return stage is not None and stage.owned_root()
    except (OSError,DfmError):return False


def _verify_published(out,stage):
    if _root_identity(out)!=stage.root_identity:fail('readback','Final directory is not the publisher-owned root',exit_code=4)
    for name,expected in stage.directories.items():
        path=plain(out/name)
        if identity(path,True)!=expected or access(path)!=stage.security[name]:fail('readback','Published directory identity/security mismatch',name,4)
        allowed={Path(n).name for n in stage.files if Path(n).parent==Path(name or '.')}
        allowed|={Path(n).name for n in stage.directories if n and Path(n).parent==Path(name or '.')}
        if {p.name for p in path.iterdir()}!=allowed:fail('readback','Unexpected final collection member',name,4)
    for name,expected in stage.files.items():
        path=plain(out/name)
        if identity(path,False)!=expected['identity'] or path.stat().st_nlink!=1 or path.stat().st_size!=expected['bytes'] or sha(path.read_bytes())!=expected['sha256'] or access(path)!=stage.security[name]:
            fail('readback','Published member identity/content/security mismatch',name,4)
    return {'root_identity':list(stage.root_identity),'files':len(stage.files),'directories':len(stage.directories),'security':'created-stage equivalent; no source ACL migration claimed'}


def export_collection(out,payload,guard,parent_security):
    _exclusive_supported();stage=None;attempted=returned=consumed=False;failure=None
    receipt={'phase':'pre_commit','committed':False,'verification':'not_performed','output':str(out),
             'target_state':'absent_at_preview','rollback':'not_attempted; final collection never removed',
             'input_files_written':[],'atomicity_limit':'bounded late rechecks and exclusive new directory, not global input CAS/lock'}
    try:
        with parent_guard(out.parent):
            guard()
            if access(out.parent)!=parent_security:fail('security_stale','Export parent changed',exit_code=4)
            stage=_make_stage(out.parent)
            for name,raw in sorted(payload.items()):stage.write(name,raw)
            stage.verify();guard()
            if access(out.parent)!=parent_security:fail('security_stale','Export parent changed after fsync',exit_code=4)
            stage.verify()
            attempted=True;_commit_new_directory(stage.root,out);returned=True;consumed=True
            receipt.update(phase='post_commit',committed=True,commit_returned=True)
            receipt['readback']=_verify_published(out,stage)
            if access(out.parent)!=parent_security:fail('security_stale','Export parent changed after publication',exit_code=4)
            receipt.update(verification='passed',target_state='owned_complete_collection')
    except (Exception,KeyboardInterrupt) as exc:
        failure=exc;actual_owned=stage is not None and _root_identity(out)==stage.root_identity
        if returned or actual_owned:
            consumed=True;receipt.update(phase='post_commit',committed=True)
        elif attempted and not isinstance(exc,FileExistsError):
            still_stage=_owned_stage(stage) and not os.path.lexists(out)
            receipt.update(phase='pre_commit' if still_stage else 'commit_uncertain',committed=False if still_stage else None)
        receipt.update(verification='failed',commit_attempted=attempted,commit_returned=returned,
                       target_state='owned_directory_verification_failed' if actual_owned else 'foreign_or_unknown' if os.path.lexists(out) else 'absent_observed')
    cleanup={'state':'complete','detail':'no_stage_created'}
    if stage is not None:
        if consumed:cleanup={'state':'complete','detail':'consumed_stage_name_not_cleaned; final output retained'}
        else:
            try:
                raw=stage.cleanup();cleanup={'state':'complete' if raw['state']=='removed_owned_stage' else 'cleanup_failed','raw':raw}
            except (OSError,DfmError) as exc:cleanup={'state':'cleanup_failed','reason':str(exc)}
    receipt['cleanup']=cleanup
    if failure is not None or cleanup['state']!='complete':
        raise DfmError('structure_transfer_publication','Structure collection publication failed; raw commit/cleanup facts retained',4,
                       {'cause':getattr(failure,'code',type(failure).__name__) if failure else 'cleanup_failed','message':str(failure),'publication':receipt}) from failure
    return receipt


def import_file(graph,target,original,data,access_control,guard):
    return file_writer.replace(graph,target,original,data,access=access_control,recheck=guard)
