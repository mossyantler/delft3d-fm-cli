"""One EXT publisher; preserve simple NTFS ACLs without changing their policy.

Reuse the existing secure-stage, descriptor and ReplaceFileW primitives. Unlike
the pump profile, this staged profile admits simple explicit allow/deny ACEs.
Protected DACLs and special metadata remain outside this candidate's scope.
"""
import hashlib
import os
from pathlib import Path
import stat

from . import pump_edit_security as primitives
from .boundary_support_write import parent_guard, identity
from .observation_inputs import snapshot, plain
from .common import DfmError
from .source_sink_graph import fail


def capture(target):
    if os.name != 'nt':
        return primitives.capture(target)
    target = plain(target)
    info = target.stat()
    if getattr(info, 'st_file_attributes', 0) & ~(0x20 | 0x80):
        fail('access_control', 'Special/read-only file attributes not supported')
    primitives._ntfs(target)
    descriptor = primitives._descriptor(target)
    if descriptor['control'] & 0x1000 or any(a[0] not in (0, 1) or a[1] not in (0, 0x10) for a in descriptor['aces']):
        fail('access_control', 'Protected/special ACE policies require a separate preservation gate')
    parent = primitives._descriptor(target.parent)
    descriptor['public'] = {'platform': 'windows-ntfs-simple-explicit-or-inherited-aces',
        'descriptor_sha256': hashlib.sha256(descriptor['sddl'].encode()).hexdigest(),
        'parent_descriptor_sha256': hashlib.sha256(parent['sddl'].encode()).hexdigest(),
        'file_attributes': info.st_file_attributes,
        'audit_sacl': 'not qualified; no audit-policy migration claim'}
    return descriptor


def recheck(target, expected):
    actual = capture(target)['public']
    if actual != expected['public']:
        fail('access_control', 'Target/parent captured access control changed', expected=expected['public'], actual=actual)


def restore_dacl_provenance(target, expected, owned):
    """ReplaceFileW can normalize explicit ACEs to inherited ones. Restore exact
    captured DACL on the verified committed file, held open without delete share.
    Rights/owner/group are checked before this metadata-only restoration.
    """
    if os.name != 'nt':
        return
    current = primitives._descriptor(target)
    if current['owner_group'] != expected['owner_group'] or current['aces'] != expected['aces']:
        fail('access_control', 'Unexpected committed access rights; cannot restore by assumption')
    if current['sddl'] == expected['sddl']:
        return
    import msvcrt
    c, w, adv, kernel = primitives._win()
    handle = kernel.CreateFileW(str(target), 1 | 0x20000 | 0x40000, 1 | 2, None, 3, 0x00200000, None)
    if handle == c.c_void_p(-1).value:
        primitives._check(False)
    fd = None
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != owned or identity(target) != owned:
            fail('access_control', 'Committed target handle identity changed before ACL restoration')
        adv.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, c.c_void_p]
        adv.SetFileSecurityW.restype = w.BOOL
        data = c.create_string_buffer(expected['raw'])
        primitives._check(adv.SetFileSecurityW(str(target), 4, data))
        recheck(target, expected)
    finally:
        if fd is not None:
            os.close(fd)
        if handle is not None:
            kernel.CloseHandle(handle)


def replace(graph, target, original, changed, *, access, recheck_inputs):
    stage, owned, parent_id, consumed = None, None, None, False
    receipt = {'committed': False, 'verification': 'not_performed', 'rollback': 'not_attempted',
               'atomicity': 'single EXT; pinned parent and full graph rechecks, no global filesystem lock'}
    try:
        with parent_guard(target.parent) as parent_id:
            recheck(target, access)
            fd, name = primitives.create_stage(target, access)
            stage = Path(name)
            with os.fdopen(fd, 'wb') as stream:
                info = os.fstat(stream.fileno())
                owned = (info.st_dev, info.st_ino)
                if os.name != 'nt':
                    os.fchmod(stream.fileno(), stat.S_IMODE(target.stat().st_mode))
                if not primitives.stage_matches(stage, access):
                    fail('access_control', 'Stage descriptor differs before payload')
                stream.write(changed)
                stream.flush()
                os.fsync(stream.fileno())
            recheck_inputs()
            if identity(stage) != owned or stage.read_bytes() != changed:
                fail('publication', 'Owned stage changed before commit')
            if snapshot(target, text=True)[0] != graph.files[target] or target.read_bytes() != original:
                fail('stale', 'Original target changed before commit')
            recheck(target, access)
            if not primitives.stage_matches(stage, access):
                fail('access_control', 'Stage descriptor changed before commit')
            primitives.publish(stage, target)
            consumed = True  # Never remove a reoccupied former stage name.
            receipt['committed'] = True
            record, raw = snapshot(target, text=True)
            if tuple(record['identity'][:2]) != owned or raw != changed:
                fail('publication', 'Committed target bytes or ownership not confirmed')
            restore_dacl_provenance(target, access, owned)
            recheck(target, access)
            receipt.update(verification='passed', access_control='preserved_and_verified')
    except (Exception, KeyboardInterrupt) as exc:
        try:
            record, raw = snapshot(target, text=True)
            if tuple(record['identity'][:2]) == owned and raw == changed:
                consumed = True
                receipt['committed'] = True
            elif record != graph.files[target] or raw != original:
                receipt['committed'] = None
        except (OSError, DfmError):
            receipt['committed'] = None
        receipt['verification'] = 'failed'
        raise DfmError('source_sink_publication', 'Source EXT publication failed; inspect commit evidence', 4,
                       {'cause': getattr(exc, 'code', type(exc).__name__), 'message': str(exc),
                        'publication': receipt, 'target': str(target), 'cause_details': getattr(exc, 'details', None),
                        'limit': 'No automatic rollback after unconfirmed commit; foreign paths preserved'}) from exc
    finally:
        receipt['cleanup'] = {'state': 'published_stage_consumed' if consumed else 'no_stage'}
        if stage is not None and not consumed:
            try:
                info = plain(stage.parent).stat()
                if ((info.st_dev, info.st_ino) == parent_id and identity(stage) == owned and
                        stage.read_bytes() in (b'', changed)):
                    stage.unlink()
                    receipt['cleanup'] = {'state': 'removed_exact_owned_stage'}
                else:
                    receipt['cleanup'] = {'state': 'unproven_or_foreign_stage_preserved', 'path': str(stage)}
            except (OSError, DfmError) as cleanup_error:
                receipt['cleanup'] = {'state': 'unproven_stage_preserved', 'path': str(stage), 'reason': str(cleanup_error)}
    return receipt
