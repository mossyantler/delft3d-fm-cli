"""Native reference tokens and ordinary contained files, without ambient lookup.

Only geometry/frictfile is a semicolon list here: pinned HYDROLIB-core
48993b1c hydrolib/core/dflowfm/mdu/models.py:2150-2152 declares that delimiter;
FM unstruc_model.f90:838 reads the corresponding 1D roughness file collection.
Other keys retain their single-path meaning.
"""
import os
from pathlib import Path, PureWindowsPath

from .common import sha
from .coupling_common import fail


def tokens(address, value, fm):
    parts=value.split(';') if fm and address=='geometry/frictfile' else [value]
    parts=[p.strip() for p in parts]
    if not parts or any(not p for p in parts):
        fail('coupling_input_missing','Empty native reference/list element',address)
    if len({p.replace('\\','/').casefold() for p in parts})!=len(parts):
        fail('ambiguous_coupling_input','Duplicate native reference/list element',address)
    return parts


def ordinary(root, parent, value):
    """Check lexical containment and every reparse point before resolving."""
    root=Path(root).resolve(strict=True)
    win=PureWindowsPath(value)
    if win.drive or win.root or '\x00' in value or ':' in value:
        fail('unsafe_coupling_path','Native file must be a relative contained path',value)
    candidate=Path(os.path.abspath(Path(parent)/value.replace('\\','/')))
    if not candidate.is_relative_to(root):fail('unsafe_coupling_path','Native input escapes case',value)
    for p in (candidate,*candidate.parents):
        if p.is_symlink() or p.is_junction():fail('unsafe_coupling_path','Linked native input or directory is unsupported',value)
        if p==root:break
    if not candidate.is_file():fail('coupling_input_missing','Required native input is missing',value)
    resolved=candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):fail('unsafe_coupling_path','Resolved native input escapes case',value)
    return resolved


def fingerprint(root, path, component, setting):
    return {'component':component,'setting':setting,'path':path.relative_to(Path(root).resolve()).as_posix(),
            'sha256':sha(path),'bytes':path.stat().st_size}
