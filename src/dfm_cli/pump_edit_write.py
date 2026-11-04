"""One-file pump publisher with honest commit, readback and rollback receipts.

Reuse the established pinned-directory guard, not another editor's receipt or
rollback assumptions. No global lock or filesystem compare-and-swap is claimed.
"""
import os
from pathlib import Path
import stat

from .common import DfmError
from .observation_inputs import snapshot, plain
from .boundary_support_write import parent_guard, identity
from . import pump_edit_security as security


def _publish(stage, target):
    security.publish(stage, target)


def _readback(target):
    return snapshot(target, text=True)


def _observe(target):
    # Independent observation is also used after a failed readback. Failure to
    # observe is unknown, never evidence that the input remained unchanged.
    try:
        return snapshot(target, text=True)
    except (OSError, DfmError):
        return None, None


def _same(record, raw, owned, expected):
    return record is not None and tuple(record["identity"][:2]) == owned and raw == expected


def _stage(target, data, mode, owned, access):
    fd, name = security.create_stage(target, access)
    path = Path(name)
    info = os.fstat(fd)
    parent = target.parent.stat()
    item = {"path": path, "identity": (info.st_dev, info.st_ino), "expected": b"",
            "parent_identity": (parent.st_dev, parent.st_ino), "consumed": False}
    owned.append(item)  # Capture before any write/flush that can fail.
    with os.fdopen(fd, "wb") as stream:
        if os.name != "nt":
            os.fchmod(stream.fileno(), mode)
        if not security.stage_matches(path, access):
            raise DfmError("pump_stage_acl", "Protected stage access control differs before payload", 4)
        stream.write(data)
        item["expected"] = data
        if os.name == "nt":
            if identity(path) != item["identity"]:
                raise DfmError("pump_stage", "Owned stage identity changed while open", 4)
            os.chmod(path, mode)
        else:
            os.fchmod(stream.fileno(), mode)
        stream.flush()
        os.fsync(stream.fileno())
    return item


def _cleanup(owned):
    result = {"state": "complete", "paths": []}
    for item in owned:
        if item["consumed"]:
            continue  # Never clean a published stage name, even if reused.
        path = item["path"]
        try:
            # Only our captured ordinary, singly-linked inode can be removed.
            # No following a reassigned name or an original target path.
            parent = plain(path.parent).stat()
            if (parent.st_dev, parent.st_ino) != item["parent_identity"]:
                result["paths"].append({"path": str(path), "state": "changed_parent_preserved"})
                continue
            if not path.exists() and not path.is_symlink():
                continue
            record, raw = _observe(path)
            if not _same(record, raw, item["identity"], item["expected"]):
                result["paths"].append({"path": str(path), "state": "foreign_or_unknown_preserved"})
                continue
            path.unlink()
        except (OSError, DfmError) as exc:
            result["paths"].append({"path": str(path), "state": "not_removed", "error": str(exc)})
    if result["paths"]:
        result["state"] = "cleanup_failed"
    return result


def _rollback(target, original, changed, captured, mode, owned, access):
    record, raw = _observe(target)
    if not _same(record, raw, captured, changed):
        return {"state": "not_safe", "attempted": False, "reason": "Target is not the exact publisher-owned proposed bytes"}, "foreign_or_unknown"
    try:
        security.recheck(target, access)
    except (OSError, DfmError):
        return {"state": "not_safe", "attempted": False, "reason": "Target access control changed; preserved"}, "foreign_or_unknown"
    rollback_stage = _stage(target, original, mode, owned, access)
    staged, staged_raw = _observe(rollback_stage["path"])
    if not _same(staged, staged_raw, rollback_stage["identity"], original):
        raise DfmError("pump_rollback_stage", "Rollback stage changed", 4)
    # Recheck the precise ownership/content predicate immediately before replace.
    record, raw = _observe(target)
    if not _same(record, raw, captured, changed):
        return {"state": "not_safe", "attempted": False, "reason": "Concurrent target change before rollback; preserved"}, "foreign_or_unknown"
    security.recheck(target, access)
    _publish(rollback_stage["path"], target)
    rollback_stage["consumed"] = True
    record, raw = _observe(target)
    if not _same(record, raw, rollback_stage["identity"], original):
        return {"state": "failed", "attempted": True, "reason": "Cannot verify owned restored original bytes"}, "foreign_or_unknown"
    security.recheck(target, access)
    return {"state": "restored_original_bytes", "attempted": True, "access_control": "preserved_and_verified",
            "metadata_restored": False, "reason": "Original bytes restored in a new inode; timestamps/inode are not restored"}, "restored_original_bytes"


def replace(graph, target, original, changed, *, access, recheck):
    """Called only after exact preview consent; no-op is handled without a stage."""
    owned, stage = [], None
    attempted, returned = False, False
    failure = None
    receipt = {"phase": "pre_commit", "committed": False, "target_state": "unknown",
               "verification": "not_performed", "rollback": {"state": "not_attempted_pre_commit", "attempted": False},
               "other_inputs_written": [], "metadata_restored": False,
               "atomicity_limit": "Pinned directories and bounded rechecks; no global lock or filesystem compare-and-swap against uncooperative writers"}
    try:
        with parent_guard(target.parent):
            try:
                mode = stat.S_IMODE(target.stat().st_mode)
                security.recheck(target, access)
                stage = _stage(target, changed, mode, owned, access)
                recheck()  # Full graph content and aliases after fsync, once.
                record, raw = _readback(stage["path"])
                if not _same(record, raw, stage["identity"], changed):
                    raise DfmError("pump_stage", "Owned proposed stage changed before publication", 4)
                record, raw = _readback(target)
                if record != graph.files[target] or raw != original:
                    raise DfmError("pump_stale", "Original target changed at final publication check", 4)
                security.recheck(target, access)
                if not security.stage_matches(stage["path"], access):
                    raise DfmError("pump_stage_acl", "Stage access control changed before publication", 4)
                attempted = True
                _publish(stage["path"], target)
                returned = True
                stage["consumed"] = True
                receipt.update(phase="post_commit", committed=True)
                record, raw = _readback(target)
                if not _same(record, raw, stage["identity"], changed):
                    raise DfmError("pump_write_verification", "Cannot verify publisher-owned changed input bytes", 4)
                security.recheck(target, access)
                receipt.update(target_state="committed_bytes", verification="passed", access_control="preserved_and_verified",
                               rollback={"state": "not_needed", "attempted": False})
            except (Exception, KeyboardInterrupt) as exc:
                failure = exc
                record, raw = _observe(target)
                actually_owned = stage is not None and _same(record, raw, stage["identity"], changed)
                if actually_owned:
                    stage["consumed"] = True
                still_original = record == graph.files[target] and raw == original
                committed = True if returned or actually_owned else False if not attempted or still_original else None
                receipt.update(phase="post_commit" if returned or actually_owned else "commit_uncertain" if attempted and not still_original else "pre_commit",
                               committed=committed, verification="failed",
                               target_state="committed_bytes" if actually_owned else "original_bytes" if still_original else "foreign_or_unknown")
                if committed is True and actually_owned:
                    try:
                        receipt["rollback"], receipt["target_state"] = _rollback(target, original, changed, stage["identity"], mode, owned, access)
                    except (Exception, KeyboardInterrupt) as rollback_exc:
                        after, after_raw = _observe(target)
                        restored = any(_same(after, after_raw, item["identity"], original) for item in owned)
                        for item in owned:
                            if _same(after, after_raw, item["identity"], original):
                                item["consumed"] = True
                        receipt["target_state"] = "restored_original_bytes" if restored else "foreign_or_unknown"
                        receipt["rollback"] = {"state": "restored_original_bytes" if restored else "failed", "attempted": True,
                                               "reason": str(rollback_exc), "metadata_restored": False}
                elif committed is not False:
                    receipt["rollback"] = {"state": "not_safe", "attempted": False,
                                           "reason": "No verified exact publisher-owned proposed target; foreign/unreadable target preserved"}
    except (Exception, KeyboardInterrupt) as exc:
        if failure is None:
            failure = exc
            record, raw = _observe(target)
            receipt["target_state"] = "original_bytes" if record == graph.files[target] and raw == original else "foreign_or_unknown"
            receipt["verification"] = "failed"
    finally:
        receipt["cleanup"] = _cleanup(owned)
    if failure is not None or receipt["cleanup"]["state"] != "complete":
        raise DfmError("pump_publication", "Pump input publication did not complete with verified cleanup", 4,
                       {"cause": getattr(failure, "code", type(failure).__name__) if failure else "cleanup_failed",
                        "message": str(failure) if failure else "Owned stage cleanup failed",
                        "cause_details": getattr(failure, "details", None), "publication": receipt}) from failure
    return receipt
