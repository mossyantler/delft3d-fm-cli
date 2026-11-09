"""RUNIN-I: ``bc_state`` parses the source-sink ``.bc`` with the ``bc`` comment mode.

Contract ``research/notes/delivery/consumers-run-inputs.md`` R1-R2. A source-sink ``.bc`` whose column-1 ``!``, ``%`` or
``*`` lines come before the first block or before a block's first numeric row must give the same admission result
(``native_preflight``, the input fingerprint path and the staged inputs) as the same file without them. A ``*`` in a
data row and a tab-led ``*`` keep their current refusal. Nothing is launched. Tests marked NEW fail on the base;
controls pass on both.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import runs, source_sink_run_profile as subject
from dfm_cli import windows_job, windows_job_trace_api
from dfm_cli.common import DfmError
from dfm_cli.source_sink_run_inputs import PROFILE

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
from test_comment_consumers import norm, note_bc, without_notes  # noqa: E402

FIXTURES = TESTS / 'source_sink_run_fixtures'


def tree(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


class RunInputsComments(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='run-inputs-comments-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.plain = self.root / 'plain'
        self.noted = self.root / 'noted'
        shutil.copytree(FIXTURES / 'point', self.plain)
        shutil.copytree(FIXTURES / 'point', self.noted)
        self.original = tree(FIXTURES)
        self.enterContext(patch('subprocess.Popen', side_effect=AssertionError('No process launch')))
        self.enterContext(patch.object(runs, 'OwnedJob', side_effect=AssertionError('No real Job')))
        self.enterContext(patch.object(windows_job, 'api', side_effect=AssertionError('No Windows native API')))
        self.enterContext(patch.object(windows_job_trace_api, 'api', side_effect=AssertionError('No trace API')))
        # The comment-free model is qualified first, so every later refusal comes from the comment lines.
        self.plain_result = self.preflight(self.plain)

    def tearDown(self):
        self.assertEqual(tree(FIXTURES), self.original)

    @staticmethod
    def preflight(folder, route='direct'):
        return subject.native_preflight(folder / 'model.mdu', PROFILE, route=route)

    def bc(self, raw=None):
        path = self.noted / 'source.bc'
        if raw is not None:
            path.write_bytes(raw)
        return path

    def insert(self, anchor, line, occurrence=0):
        """Put ``line`` (no end of line) before the ``occurrence``-th whole line equal to ``anchor``."""
        lines = self.bc().read_bytes().splitlines(keepends=True)
        hits = [i for i, text in enumerate(lines) if text.rstrip(b'\r\n') == anchor]
        self.assertGreater(len(hits), occurrence, anchor)
        lines.insert(hits[occurrence], line + b'\r\n')
        self.bc(b''.join(lines))

    def assertSameAdmission(self, route='direct'):
        report, selected = self.preflight(self.noted, route)
        plain_report, plain_selected = self.preflight(self.plain, route)
        self.assertEqual(norm([report, selected], self.noted), norm([plain_report, plain_selected], self.plain))
        # The fingerprint covers the original bytes: it follows the commented file, not a normalized copy.
        digest = hashlib.sha256(self.bc().read_bytes()).hexdigest()
        self.assertIn(digest, {f['sha256'] for f in report['files']})

    def stage(self, folder, suffix):
        kernels = self.root / 'suite/kernels'
        records = {}
        for name in ('bin/dflowfm-cli.exe', 'bin/dimr.exe', 'lib/dflowfm.dll', 'lib/dimr.dll', 'lib/gdal.dll'):
            path = kernels / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(('NONEXECUTABLE TEST FIXTURE ' + name).encode())
            records[name] = {'path': str(path), 'exists': True, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        install = {'kernels': str(kernels), 'binaries': records, 'proj_data': None}
        with patch.object(runs, 'select', return_value=install), \
             patch.object(runs, 'process_identity', return_value={'pid': 1, 'creation_time_100ns': '1'}):
            run = runs.prepare(folder / 'model.mdu', self.root / suffix, 'synthetic-suite', 'direct', 20, False, PROFILE)
            runs.stage(run)
        return run

    def refused(self):
        with self.assertRaises(DfmError) as error:
            self.preflight(self.noted)
        self.assertNotEqual(error.exception.exit_code, 70)

    # ------------------------------------------------------------------ NEW: comment lines are not content

    def test_each_comment_char_before_a_block_and_a_first_row_admits_alike(self):  # NEW
        raw = self.bc().read_bytes()
        for char in (b'!', b'%', b'*'):
            with self.subTest(char=char):
                self.bc(raw)
                self.insert(b'[General]', char + b' cmt-note general')
                self.insert(b'[Forcing]', char + b' cmt-note first block')
                self.insert(b'0 0.1 5', char + b' cmt-note first row')
                self.insert(b'0 0', char + b' cmt-note second block row')
                self.assertSameAdmission()

    def test_mixed_comments_at_every_position_admit_alike_on_both_routes(self):  # NEW
        self.bc(note_bc(self.bc().read_bytes()))
        self.assertEqual(without_notes(self.bc().read_bytes()), (self.plain / 'source.bc').read_bytes())
        self.assertGreater(len(self.bc().read_bytes()), len((self.plain / 'source.bc').read_bytes()))
        for route in ('direct', 'dimr'):
            with self.subTest(route=route):
                self.assertSameAdmission(route)

    def test_comments_stage_and_prelaunch_with_the_original_bytes(self):  # NEW
        self.bc(note_bc(self.bc().read_bytes()))
        run = self.stage(self.noted, 'noted-run')
        plain = self.stage(self.plain, 'plain-run')
        self.assertEqual(subject.pre_launch_hook(run)['state'], 'passed')
        self.assertEqual({f['relative_path'] for f in run.record['inputs']},
                         {f['relative_path'] for f in plain.record['inputs']})
        self.assertEqual(self.bc().read_bytes(), (run.folder / 'model/source.bc').read_bytes())
        self.assertNotEqual((run.folder / 'model/source.bc').read_bytes(), (plain.folder / 'model/source.bc').read_bytes())

    # ------------------------------------------------------------------ controls (pass on the base too)

    def test_no_comment_lines_admit_exactly_as_before(self):  # control
        self.assertSameAdmission()
        self.assertEqual(norm(list(self.preflight(self.noted)), self.noted), norm(list(self.plain_result), self.plain))

    def test_star_in_a_data_row_keeps_its_refusal(self):  # control
        self.insert(b'120 0.1 5', b'* cmt-note data row')
        self.refused()

    def test_tab_led_star_before_a_first_row_keeps_its_refusal(self):  # control
        self.insert(b'0 0.1 5', b'\t* cmt-note tab')
        self.refused()

    def test_unsupported_content_still_refuses_beside_comments(self):  # control
        self.bc(note_bc(self.bc().read_bytes()))
        self.bc(self.bc().read_bytes().replace(b'Function = timeseries', b'Function = harmonic', 1))
        self.refused()


if __name__ == '__main__':
    unittest.main()
