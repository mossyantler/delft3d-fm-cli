"""Portable public pump-set regressions: stdlib, owned temporary input files only.

Invokes the real CLI parser/dispatcher in-process; never launches an engine.
The opaque mesh tests file-graph binding only, not solver/geometry validity.
"""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

from dfm_cli.cli import main
from _pump_edit_test_support import fixture, manual_edit, snapshot, WindowsAcl


class PumpEditPublicTests(unittest.TestCase):
    def setUp(self):
        # Python 3.12's mkdtemp(mode=0700) gives Windows a custom DACL. Use
        # ordinary inheritance for this publisher's separately bounded profile.
        self.root = Path(tempfile.gettempdir()).resolve()/('dfm-pump-edit-'+uuid.uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(shutil.rmtree, self.root)
        self.mdu, self.target = fixture(self.root/'model')

    def call(self, *request, identifier='pump_A', exit_code=0, error=None):
        out, err = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            for name in ('subprocess.Popen', 'os.system', 'socket.socket.connect', 'socket.socket.bind'):
                stack.enter_context(patch(name, side_effect=AssertionError('No process/network in input edit')))
            if hasattr(os, 'startfile'):
                stack.enter_context(patch('os.startfile', side_effect=AssertionError('No GUI launch')))
            code = main(['pump', 'set', str(self.mdu), '--id', identifier, *request])
        payload = json.loads(out.getvalue())
        self.assertEqual(code, exit_code, (payload, err.getvalue()))
        self.assertEqual(payload['protocol_version'], 2)
        self.assertEqual(payload['ok'], code == 0)
        if error:
            self.assertEqual(payload['error']['code'], error)
        elif code:
            self.assertIsInstance(payload['error']['code'], str)
            self.assertNotIn(payload['error']['code'], ('internal_error', 'io_or_data_error'))
        return payload['result'] if code == 0 else payload['error']

    def refusal(self, *request, **kwargs):
        before = snapshot(self.root)
        result = self.call(*request, **kwargs)
        self.assertEqual(snapshot(self.root), before, 'Refusal changed inputs or left a stage')
        return result

    def preview(self, *request):
        before = snapshot(self.root)
        result = self.call(*request)
        self.assertEqual(snapshot(self.root), before, 'Preview changed inputs or left a stage')
        self.assertIs(result['applied'], False)
        self.assertRegex(result['sha256'], r'^[0-9a-f]{64}$')
        return result['sha256']

    def edit(self, field, literal):
        args = ['--orientation', literal] if field == 'orientation' else ['--capacity-m3-s='+literal]
        before, raw = snapshot(self.root), self.target.read_bytes()
        acl = WindowsAcl().read(self.target) if os.name == 'nt' else None
        expected = manual_edit(raw, field, literal)
        consent = self.preview(*args)
        result = self.call(*args, '--apply', '--expect-sha256', consent)
        self.assertEqual(self.target.read_bytes(), expected)
        after = snapshot(self.root)
        self.assertEqual(set(before), set(after), 'Unclean publication stage/backup')
        target = self.target.relative_to(self.root).as_posix()
        for name in set(before)-{target}:
            self.assertEqual(before[name], after[name], name)
        self.assertEqual(before[target][6:], after[target][6:], 'Mode/owner/group changed')
        if acl is not None:
            self.assertEqual(WindowsAcl().read(self.target), acl)
        self.assertEqual(result['changed'], raw != expected)
        self.assertEqual(result['hydraulic_effect'], 'not_predicted')
        self.assertEqual(result['gui_parity'], 'not_verified')
        if raw == expected:
            self.assertEqual(before, after, 'No-op must preserve the original inode and mtime')

    def test_orientation_one_token_preserves_CRLF_BOM_comments_and_other_files(self):
        self.edit('orientation', 'negative')

    def test_signed_capacity_literals_preserve_every_other_byte(self):
        for index, literal in enumerate(('0', '-1', '+1.000D+0', '0.125')):
            with self.subTest(literal=literal):
                self.mdu, self.target = fixture(self.root/str(index))
                self.edit('capacity', literal)

    def test_exact_noop_keeps_inode_and_numeric_equal_spelling_is_explicit_edit(self):
        self.edit('orientation', 'positive')
        self.edit('capacity', '+1.2500D+0')
        self.edit('capacity', '1.2500')

    def test_consent_is_bound_to_field_literal_and_exact_ID(self):
        consent = self.preview('--orientation', 'negative')
        for args, identifier in ((['--capacity-m3-s=0'], 'pump_A'),
                                 (['--orientation', 'positive'], 'pump_A'),
                                 (['--orientation', 'negative'], 'pump_B')):
            with self.subTest(args=args, identifier=identifier):
                self.refusal(*args, '--apply', '--expect-sha256', consent,
                             identifier=identifier, exit_code=4, error='pump_stale')

    def test_consent_binds_linked_mesh_other_PLI_and_MDU(self):
        for index, name in enumerate(('mesh.nc', 'lines/other.pli', 'model.mdu', 'boundaries.ext')):
            with self.subTest(name=name):
                self.mdu, self.target = fixture(self.root/str(index))
                consent = self.preview('--orientation', 'negative')
                path = self.mdu.parent/name
                path.write_bytes(path.read_bytes()+b'\r\n# changed graph input\r\n')
                self.refusal('--orientation', 'negative', '--apply', '--expect-sha256', consent,
                             exit_code=4, error='pump_stale')

    def test_byte_identical_replacement_with_restored_mtime_invalidates_consent(self):
        consent = self.preview('--orientation', 'negative')
        previous = self.target.stat()
        replacement = self.target.with_name('external-replacement.ini')
        replacement.write_bytes(self.target.read_bytes())
        os.replace(replacement, self.target)
        os.utime(self.target, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.assertNotEqual(previous.st_ino, self.target.stat().st_ino)
        self.refusal('--orientation', 'negative', '--apply', '--expect-sha256', consent,
                     exit_code=4, error='pump_stale')

    def test_malformed_ID_is_usage_and_valid_absent_ID_is_resource_error(self):
        for identifier in ('pump_A\nid=pump_B', '../pump_A', ' pump_A', ''):
            with self.subTest(identifier=identifier):
                self.refusal('--orientation', 'negative', identifier=identifier, exit_code=2, error='pump_id')
        for identifier in ('absent', 'PUMP_A', 'weir_C', 'geometry_selected'):
            with self.subTest(identifier=identifier):
                self.refusal('--orientation', 'negative', identifier=identifier, exit_code=3, error='pump_selection')

    def test_request_shape_and_nonfinite_or_underflow_values_refuse(self):
        for args in ((), ('--orientation','negative','--capacity-m3-s=0'),
                     ('--orientation','east'), ('--capacity-m3-s=NaN',),
                     ('--capacity-m3-s=1e309',), ('--capacity-m3-s=1e-9999',),
                     ('--capacity-m3-s=1e-310',), ('--capacity-m3-s=1 2',),
                     ('--orientation','negative','--unit','m3/s')):
            with self.subTest(args=args):
                self.refusal(*args, exit_code=2)

    def test_apply_requires_valid_exact_preview_hash(self):
        self.refusal('--orientation', 'negative', '--apply', exit_code=2)
        self.refusal('--orientation', 'negative', '--apply', '--expect-sha256', 'invalid', exit_code=2)
        self.refusal('--orientation', 'negative', '--apply', '--expect-sha256', '0'*64,
                     exit_code=4, error='pump_stale')

    def test_missing_duplicate_or_unknown_target_semantics_do_not_default(self):
        raw = self.target.read_bytes()
        variants = (
            raw.replace(b'orientation\t= positive  # selected polarity\r\n', b'', 1),
            raw.replace(b'numStages = 0', b'orientation = positive\r\nnumStages = 0', 1),
            raw.replace(b'numStages = 0', b'unknownControl = 0\r\nnumStages = 0', 1),
            raw.replace(b'numStages = 0', b'numStages = 2', 1),
            raw.replace(b'numReductionLevels = 0', b'numReductionLevels = 2', 1),
            raw.replace(b'capacity = +1.2500D+0', b'capacity = signal.tim', 1))
        for changed in variants:
            with self.subTest(changed=changed):
                self.target.write_bytes(changed)
                self.refusal('--orientation', 'negative', exit_code=3)

    def test_edit_requires_explicit_2D_scope(self):
        raw = self.mdu.read_bytes()
        for changed, error in ((raw.replace(b'Kmx = 0', b'Kmx = 3'), 'pump_edit_scope'),
                               (raw.replace(b'Kmx = 0\r\n', b''), 'observation_missing_setting')):
            with self.subTest(mdu=changed):
                self.mdu.write_bytes(changed)
                self.refusal('--orientation', 'negative', exit_code=3, error=error)

    def test_duplicate_casefold_ID_and_shared_location_refuse(self):
        raw = self.target.read_bytes()
        for changed in (raw.replace(b'id = pump_B', b'id = PUMP_a'),
                        raw.replace(b'locationFile = lines/other.pli', b'locationFile = lines/selected.pli')):
            with self.subTest(structures=changed):
                self.target.write_bytes(changed)
                self.refusal('--orientation', 'negative', exit_code=3)

    def test_StructureFile_output_alias_refuses(self):
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b'HisFile = history.nc', b'HisFile = structures.ini'))
        self.refusal('--orientation', 'negative', exit_code=3, error='pump_edit_alias')

    def acl_capability(self):
        acl = WindowsAcl()
        reason = acl.capability_reason(self.target)
        if reason:
            self.skipTest(reason)
        # Probe only our extra empty file. Permission/OS limitations are precise;
        # unexpected errors are not converted into skipped product regressions.
        probe = self.root/'acl-capability-probe'
        probe.write_bytes(b'')
        try:
            acl.protect_current_user(probe)
        except OSError as exc:
            if exc.winerror in {5, 50, 1314}:
                self.skipTest(f'Fresh-file DACL modification unavailable: WinError {exc.winerror}')
            raise
        finally:
            probe.unlink()
        return acl

    @unittest.skipUnless(os.name == 'nt', 'Actual protected DACL regression requires Windows')
    def test_protected_current_user_DACL_refuses_before_staging(self):
        acl = self.acl_capability()
        before = snapshot(self.root)
        descriptor = acl.protect_current_user(self.target)
        self.assertEqual(snapshot(self.root), before, 'ACL-only fixture mutation changed bytes/mtime/inode')
        # Stage helper is only a must-not-call tripwire; no parser/oracle result is mocked.
        with patch('dfm_cli.pump_edit_security.create_stage', side_effect=AssertionError('Must refuse before staging')) as stage:
            self.refusal('--orientation', 'negative', exit_code=3, error='pump_access_control')
            self.refusal('--orientation', 'negative', '--apply', '--expect-sha256', '0'*64,
                         exit_code=4, error='pump_stale')
        stage.assert_not_called()
        self.assertEqual(acl.read(self.target), descriptor)

    @unittest.skipUnless(os.name == 'nt', 'ACL-only preview invalidation requires Windows')
    def test_ACL_only_change_invalidates_consent_before_staging(self):
        acl = self.acl_capability()
        consent = self.preview('--orientation', 'negative')
        before, descriptor = snapshot(self.root), acl.read(self.target)
        protected = acl.protect_current_user(self.target)
        self.assertNotEqual(descriptor, protected)
        self.assertEqual(snapshot(self.root), before, 'ACL-only fixture mutation changed bytes/mtime/inode')
        with patch('dfm_cli.pump_edit_security.create_stage', side_effect=AssertionError('Must refuse before staging')) as stage:
            self.refusal('--orientation', 'negative', '--apply', '--expect-sha256', consent,
                         exit_code=4, error='pump_stale')
        stage.assert_not_called()
        self.assertEqual(acl.read(self.target), protected)


if __name__ == '__main__':
    unittest.main()
