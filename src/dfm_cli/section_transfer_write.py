"""One-file import adapter and exclusive new export, using reviewed guards.

Import delegates unchanged ACL writer/rollback logic. Fresh export adapts the
existing no-clobber primitive, adding pinned parents, security consent and
truthful post-publication receipts. Final exported names are never cleaned up.
"""
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from . import pump_edit_security as security, pump_edit_write as importer
from .boundary_support_write import parent_guard
from .observation_inputs import plain, snapshot
from .section_transfer_contract import fail
from .section_transfer_text import digest, sha
from .common import DfmError


def read_access(path):
    """Consent fingerprint only: no read-only input ACL migration/admission."""
    path = plain(path); info = path.stat()
    if os.name == "nt":
        return {"platform": "windows-read-only-input", "descriptor_sha256": sha(security._descriptor(path)["sddl"].encode()),
                "attributes": info.st_file_attributes}
    if os.name == "posix" and hasattr(os, "listxattr"):
        return {"platform": "posix-read-only-input", "uid": info.st_uid, "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode), "xattrs_sha256": digest({n: sha(os.getxattr(path, n)) for n in os.listxattr(path)})}
    fail("security", "No qualified input security fingerprint reader")


def parent_access(parent):
    parent = plain(parent); info = parent.stat()
    if not stat.S_ISDIR(info.st_mode): fail("parent", "Existing ordinary output parent required")
    if os.name == "nt":
        descriptor = security._descriptor(parent)
        return {"platform": "windows-parent-inherited-new-file", "descriptor_sha256": sha(descriptor["sddl"].encode()),
                "attributes": info.st_file_attributes, "source_ACL_copied": False}
    if os.name == "posix" and hasattr(os, "listxattr"):
        attrs = {name: sha(os.getxattr(parent, name)) for name in os.listxattr(parent)}
        return {"platform": "posix-parent-new-file", "uid": info.st_uid, "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode), "xattrs_sha256": digest(attrs), "source_ACL_copied": False}
    fail("security", "No qualified new-file parent security reader on this platform")


def stage_access(path):
    if os.name == "nt": return sha(security._descriptor(path)["sddl"].encode())
    info = plain(path).stat()
    return digest({"uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode),
                   "xattrs": {n: sha(os.getxattr(path, n)) for n in os.listxattr(path)}})


def _observe(path):
    try:
        path = plain(path); info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink not in (1, 2) or info.st_size > 8 * 1024**2: return None
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno()); data = stream.read(8 * 1024**2 + 1); ended = os.fstat(stream.fileno())
        final = path.lstat()
        keys = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
        if not keys(info) == keys(opened) == keys(ended) == keys(final) or len(data) != info.st_size: return None
        return {"identity": (info.st_dev, info.st_ino), "bytes": data}
    except (OSError, DfmError): return None


def _publish_new(stage, output):
    if os.name == "nt": os.rename(stage, output)  # Windows refuses existing name.
    else: os.link(stage, output)  # Atomic exclusive creation, no clobber fallback.


def _cleanup(stage, owned, expected, parent_identity):
    if stage is None: return {"state": "complete", "temporary": "consumed_or_not_created"}
    try:
        p = plain(stage.parent).stat(); value = _observe(stage)
        if not os.path.lexists(stage): return {"state": "complete", "temporary": "absent"}
        if (p.st_dev, p.st_ino) != parent_identity or value is None or value["identity"] != owned or value["bytes"] != expected:
            return {"state": "cleanup_failed", "temporary": str(stage), "reason": "foreign_or_unknown_preserved"}
        stage.unlink(); return {"state": "complete", "temporary": "removed_exact_owned_stage"}
    except (OSError, DfmError) as exc: return {"state": "cleanup_failed", "temporary": str(stage), "reason": str(exc)}


def export_new(graph, data, access):
    output = graph.out; temporary = owned = parent_id = None; expected = b""; consumed = False
    attempted = returned = False; failure = None
    receipt = {"phase": "pre_commit", "committed": False, "verification": "not_performed", "output": str(output),
               "target_state": "absent_at_preview", "rollback": "not_attempted; final output never deleted", "input_files_written": [],
               "atomicity_limit": "No global input lock or filesystem CAS against uncooperative writers"}
    try:
        with parent_guard(output.parent) as parent_id:
            if parent_access(output.parent) != access: fail("security_stale", "Output parent security changed", exit_code=4)
            graph.recheck()
            fd, name = tempfile.mkstemp(prefix=".dfm-section-export-", dir=output.parent); temporary = Path(name)
            with os.fdopen(fd, "wb") as stream:
                info = os.fstat(stream.fileno()); owned = info.st_dev, info.st_ino
                stage_acl = stage_access(temporary)
                stream.write(data); expected = data; stream.flush(); os.fsync(stream.fileno())
            value = _observe(temporary)
            if value is None or value["identity"] != owned or value["bytes"] != data or stage_access(temporary) != stage_acl:
                fail("stage", "Owned export stage bytes/identity/security changed", exit_code=4)
            graph.recheck()
            if parent_access(output.parent) != access: fail("security_stale", "Output parent security changed after fsync", exit_code=4)
            value = _observe(temporary)
            if value is None or value["identity"] != owned or value["bytes"] != data or stage_access(temporary) != stage_acl:
                fail("stage", "Owned stage changed during final guard", exit_code=4)
            attempted = True; _publish_new(temporary, output); returned = True
            if os.name == "nt": consumed = True
            receipt.update(phase="post_commit", committed=True, commit_operation="rename-no-clobber" if os.name == "nt" else "exclusive-link", commit_returned=True)
            if not consumed:
                cleanup = _cleanup(temporary, owned, expected, parent_id)
                if cleanup["state"] != "complete": fail("cleanup", "Exclusive export created but temporary cleanup failed", cleanup, 4)
                consumed = True
            record, readback = snapshot(output, text=True)
            if tuple(record["identity"][:2]) != owned or readback != data or stage_access(output) != stage_acl:
                fail("readback", "Cannot verify original owned exported file", exit_code=4)
            if parent_access(output.parent) != access: fail("security_stale", "Parent changed after publication", exit_code=4)
            receipt.update(verification="passed", target_state="owned_export_bytes", output_record=record, stage_security_sha256=stage_acl)
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc; value = _observe(output)
        actual = value is not None and value["identity"] == owned and value["bytes"] == data
        stage = _observe(temporary) if temporary is not None else None
        if actual or returned:
            receipt.update(phase="post_commit", committed=True)
            if os.name == "nt": consumed = True
        elif attempted and not isinstance(exc, FileExistsError):
            definitely_not_moved = stage is not None and stage["identity"] == owned and not os.path.lexists(output)
            receipt.update(phase="pre_commit" if definitely_not_moved else "commit_uncertain", committed=False if definitely_not_moved else None)
        receipt.update(verification="failed", commit_attempted=attempted, commit_returned=returned,
                       target_state="owned_export_bytes" if actual else "foreign_or_unknown" if os.path.lexists(output) else "absent_observed")
    receipt["cleanup"] = _cleanup(None if consumed else temporary, owned, expected, parent_id)
    if failure is not None or receipt["cleanup"]["state"] != "complete":
        raise DfmError("section_transfer_publication", "Exclusive section export failed; retained final output and cleanup facts attached", 4,
                       {"cause": getattr(failure, "code", type(failure).__name__) if failure else "cleanup_failed", "message": str(failure), "publication": receipt}) from failure
    return receipt


def import_replace(graph, original, changed, access):
    def recheck(): graph.recheck(); security.recheck(graph.target, access)
    return importer.replace(graph, graph.target, original, changed, access=access, recheck=recheck)
