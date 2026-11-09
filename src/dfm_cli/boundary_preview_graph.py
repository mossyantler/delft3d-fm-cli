"""Bounded, read-only new-EXT graph; reuse the preservation parsers."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from .boundary import _blocks, _header, _pli, _identity
from .common import DfmError, inside
from .model import parse

LIMITS = {"file_bytes": 8 * 1024**2, "total_bytes": 32 * 1024**2,
          "files": 64, "tokens": 200000, "lines": 60000, "blocks": 1024,
          "supports": 2048, "requested_times": 2048, "sample_cells": 100000,
          "harmonic_component_visits": 1000000, "prepared_row_visits": 100000,
          "receipt_estimated_bytes": 8 * 1024**2,
          "row_limit": 64, "token_bytes": 256, "line_bytes": 4096}


def fail(code, message, **details):
    raise DfmError(code, message, 2 if code == 'usage' else 3, details=details or None)


def plain(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            fail('aliased_input', 'Symlinks and reparse points are unsupported', path=str(part))
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail('aliased_input', 'Expected an ordinary singly linked input file', path=str(path))
    return path


class Inputs:
    def __init__(self):
        self.files = {}
        self.total = self.tokens = self.lines = 0

    def read(self, path):
        path = plain(path)
        if path in self.files:
            return self.files[path]['raw']
        if len(self.files) >= LIMITS['files']:
            fail('preview_budget', 'Too many boundary input files')
        with path.open('rb') as stream:
            before = _identity(os.fstat(stream.fileno()))
            if before[2] > LIMITS['file_bytes'] or self.total + before[2] > LIMITS['total_bytes']:
                fail('preview_budget', 'Boundary input byte budget exceeded', path=str(path))
            chunks, count = [], 0
            while chunk := stream.read(min(65536, LIMITS['file_bytes'] - count + 1)):
                count += len(chunk)
                if count > LIMITS['file_bytes'] or self.total + count > LIMITS['total_bytes']:
                    fail('preview_budget', 'Boundary input grew beyond byte budget', path=str(path))
                chunks.append(chunk)
            raw = b''.join(chunks)
            after = _identity(os.fstat(stream.fileno()))
        if before != after or before != _identity(path.stat()):
            fail('stale_input', 'Input changed during read', path=str(path))
        # Check BEFORE allocating parser rows/tokens. Total budgets cover all files.
        for line in raw.splitlines():
            self.lines += 1
            if len(line) > LIMITS['line_bytes'] or self.lines > LIMITS['lines']:
                fail('preview_budget', 'Boundary text line budget exceeded', path=str(path))
            for token in re.finditer(rb'\S+', line):
                self.tokens += 1
                if token.end() - token.start() > LIMITS['token_bytes'] or self.tokens > LIMITS['tokens']:
                    fail('preview_budget', 'Boundary token budget exceeded', path=str(path))
        self.total += len(raw)
        self.files[path] = {'raw': raw, 'identity': before, 'sha256': hashlib.sha256(raw).hexdigest()}
        return raw

    def recheck(self):
        for path, item in self.files.items():
            plain(path)
            if _identity(path.stat()) != item['identity']:
                fail('stale_input', 'Input identity changed during preview', path=str(path))
            digest, count = hashlib.sha256(), 0
            with path.open('rb') as stream:
                if _identity(os.fstat(stream.fileno())) != item['identity']:
                    fail('stale_input', 'Opened input identity changed', path=str(path))
                while chunk := stream.read(65536):
                    count += len(chunk)
                    if count > len(item['raw']):
                        fail('stale_input', 'Input grew during preview', path=str(path))
                    digest.update(chunk)
                if _identity(os.fstat(stream.fileno())) != item['identity']:
                    fail('stale_input', 'Opened input changed during recheck', path=str(path))
            if digest.hexdigest() != item['sha256'] or _identity(path.stat()) != item['identity']:
                fail('stale_input', 'Input bytes changed during preview', path=str(path))

    def inventory(self):
        return [{'path': str(path), 'sha256': item['sha256'], 'bytes': len(item['raw'])}
                for path, item in sorted(self.files.items())]


def columns(block, path):
    result = []
    for field in block.fields:
        if field.key == 'quantity':
            if result and result[-1]['unit'] is None:
                fail('invalid_columns', 'Quantity has no corresponding Unit', path=str(path), line=field.line)
            result.append({'ordinal': len(result) + 1, 'quantity': field.value,
                           'unit': None, 'quantity_line': field.line})
        elif field.key == 'unit':
            if not result or result[-1]['unit'] is not None:
                fail('invalid_columns', 'Unit must follow its corresponding Quantity', path=str(path), line=field.line)
            result[-1].update(unit=field.value, unit_line=field.line)
    if any(col['unit'] is None for col in result):
        fail('invalid_columns', 'Quantity has no corresponding Unit', path=str(path))
    return result


def physical_quantities(cols):
    result = set()
    for col in cols:
        q = col['quantity'].casefold()
        if q in {'time', 'harmonic component', 'astronomic component', 'astronomic component name'}:
            continue
        result.add(re.sub(r' (amplitude|phase)$', '', q))
    return sorted(result)


class Graph:
    def __init__(self, mdu):
        self.inputs = Inputs()
        self.mdu = plain(mdu)
        self.root = self.mdu.parent
        self.entries = parse(self.inputs.read(self.mdu))
        self.mode = self.setting('general/pathsrelativetoparent', '0')
        if self.mode not in {'0', '1'}:
            fail('unsupported_path_mode', 'PathsRelativeToParent must be 0 or 1')
        if self.setting('external forcing/extforcefile', ''):
            fail('unsupported_ext', 'Legacy EXT interpretation is outside the input preview profile')
        ext_name = self.setting('external forcing/extforcefilenew', '')
        if not ext_name:
            fail('missing_reference', 'Explicit ExtForceFileNew is required')
        if self.setting('geometry/kmx', '0') != '0':
            fail('unsupported_boundary', 'This preview profile supports 2D boundary inputs only')
        self.references, self.excluded, self.boundaries, self.authored = [], [], [], []
        self.bc_files = {}
        ext = self.reference(self.mdu, ext_name, 'extforcefilenew')
        blocks = self.parse_blocks(ext, "ini")
        _header(blocks, ext, 'extforce', {'2.01', '2.02'})
        total_supports = 0
        seen = set()
        boundary_labels = {}
        for ordinal, block in enumerate(blocks[1:], 1):
            source = {'path': str(ext), 'line': block.line, 'block_ordinal': ordinal}
            if block.kind != 'boundary':
                self.excluded.append({'kind': block.kind, 'source': source,
                                      'metadata': self.metadata(block), 'reason': 'not_a_boundary_input'})
                continue
            if block.rows:
                fail('unsupported_ext', 'Rows in EXT Boundary block', **source)
            for key in {field.key for field in block.fields}:
                block.get(key, ext)
            q = block.get('quantity', ext).casefold()
            location = self.reference(ext, block.get('locationfile', ext), 'locationfile')
            forcing = self.reference(ext, block.get('forcingfile', ext), 'forcingfile')
            label, points = _pli(self.inputs.files[location]['raw'], location)
            total_supports += len(points)
            if total_supports > LIMITS['supports']:
                fail('preview_budget', 'Too many PLI supports')
            folded_label = label.casefold()
            if folded_label in boundary_labels and boundary_labels[folded_label] != label:
                fail('ambiguous_boundary_identity', 'PLI line labels differ only by case',
                     boundary=label, existing_boundary=boundary_labels[folded_label])
            boundary_labels[folded_label] = label
            identity = (folded_label, q)
            if identity in seen:
                fail('ambiguous_boundary', 'Repeated PLI label and quantity binding', boundary=label, quantity=q)
            seen.add(identity)
            unknown = [field.key for field in block.fields
                       if field.key not in {'quantity', 'locationfile', 'forcingfile', 'operand'}]
            self.boundaries.append({'id': label, 'quantity': q, 'source': source,
                'location_file': str(location), 'forcing_file': str(forcing), 'points': points,
                'operand': block.get('operand', ext, 'O'), 'unknown_metadata': unknown,
                'metadata': self.metadata(block)})
            if forcing not in self.bc_files:
                self.bc_files[forcing] = self.parse_bc(forcing)
        if not self.boundaries:
            fail('missing_boundary', 'No 2D new-EXT Boundary bindings found')
        self.authored = [signal for items in self.bc_files.values() for signal in items]

    @staticmethod
    def metadata(block):
        return [{'key': field.key, 'value': field.value, 'line': field.line} for field in block.fields]

    def setting(self, key, default=None):
        values = [entry.value for entry in self.entries if entry.address == key]
        if len(values) > 1:
            fail('ambiguous_setting', 'Repeated model clock/path setting', setting=key)
        if values:
            return values[0]
        if default is not None:
            return default
        fail('missing_setting', 'Explicit model setting required', setting=key)

    def reference(self, parent, value, key):
        base = parent.parent if self.mode == '1' else self.root
        target = inside(base, value, root=self.root)
        lexical = base / value.replace('\\', '/')
        plain(lexical)
        self.inputs.read(target)
        self.references.append({'from': str(parent), 'setting': key, 'value': value, 'path': str(target)})
        return target

    def parse_blocks(self, path, comments):
        blocks = _blocks(self.inputs.files[path]['raw'], path, comments=comments)
        if len(blocks) > LIMITS['blocks']:
            fail('preview_budget', 'Too many input blocks', path=str(path))
        return blocks

    def parse_bc(self, path):
        blocks = self.parse_blocks(path, "bc")
        _header(blocks, path, 'boundconds', {'1.01'})
        raw = self.inputs.files[path]['raw']
        lines = raw.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        result = []
        for ordinal, block in enumerate(blocks[1:], 1):
            if block.kind != 'forcing':
                self.excluded.append({'kind': block.kind, 'source': {'path': str(path), 'line': block.line},
                                      'metadata': self.metadata(block), 'reason': 'unknown_bc_section'})
                continue
            cols = columns(block, path)
            start = offsets[block.line - 1]
            end = offsets[blocks[ordinal + 1].line - 1] if ordinal + 1 < len(blocks) else len(raw)
            digest = hashlib.sha256()
            for row in block.rows:
                digest.update(lines[row.line - 1])
            result.append({'block': block, 'name': block.get('name', path),
                'function': block.get('function', path).casefold(), 'columns': cols,
                'quantities': physical_quantities(cols),
                'raw_lines': lines, 'rows_sha256': digest.hexdigest(),
                'source': {'path': str(path), 'line': block.line, 'block_ordinal': ordinal,
                           'byte_start': start, 'byte_end': end,
                           'block_sha256': hashlib.sha256(raw[start:end]).hexdigest()}})
        # Preserve recognized correction groups; never select/sum duplicate bases.
        groups = {}
        for signal in result:
            for q in signal['quantities']:
                groups.setdefault((signal['name'].casefold(), q), []).append(signal)
        for key, group in groups.items():
            bases = [s for s in group if not s['function'].endswith('-correction')]
            corrections = [s['function'] for s in group if s['function'].endswith('-correction')]
            if len(bases) > 1 or len(set(corrections)) != len(corrections):
                fail('ambiguous_boundary_signal', 'Multiple forcing blocks for one exact support/quantity; not GUI datasets',
                     path=str(path), support=key[0], quantity=key[1])
        return result
