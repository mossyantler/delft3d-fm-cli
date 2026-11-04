"""Independent public eligibility regressions. No product imports or native runs."""
from pathlib import Path
import tempfile
import unittest
from importlib.util import find_spec

from research.workflows.verification.verify_field_edit_eligibility import (
    PublicCLI, TARGET, EDITABLE, blockers_gate, check_state, edit_gate,
    flags_gate, inspect_checked, replace, text_fixture,
)


class FieldEditEligibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dfm-e014-eligibility-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cli = PublicCLI(self.root / 'commands')
        self.mdu = text_fixture(self.root / 'inputs')

    def test_default_schema_needs_no_scientific_imports_or_netcdf(self):
        code, result = self.cli.invoke('schema', 'inspect', no_netcdf=True)
        self.assertEqual(code, 0)
        self.assertIn(TARGET, result['field_edits']['fields'])

    def test_inspection_cannot_bless_malformed_or_missing_mesh_or_candidate(self):
        for missing in (False, True):
            if missing: (self.mdu.parent / 'mesh_net.nc').unlink()
            with self.subTest(missing=missing):
                report = inspect_checked(self.cli, self.mdu)
                for address in EDITABLE: check_state(report, address, 'requires_preview')
                check_state(report, 'future/novel_coefficient', 'unsupported')

    def test_filters_unknown_addresses_invalid_flags_and_no_writes(self):
        result = flags_gate(self.cli, self.mdu)
        self.assertTrue(result['invalid_flags_no_write'])

    def test_law_profile_overrides_duplicates_and_timestep_impossibility_refuse_before_netcdf(self):
        cases = blockers_gate(self.cli, self.mdu, self.root / 'counterexamples')
        self.assertEqual(len(cases), 18)
        self.assertTrue(all(c['all_input_bytes_unchanged'] for c in cases))

    def test_crlf_bom_unicode_offsets_repeated_sections_and_equal_duplicate_rows(self):
        self.mdu.write_bytes(self.mdu.read_bytes() + b'[PHYSICS]\r\n UnifFrictCoef = 0.023 # equal duplicate\r\n')
        report = inspect_checked(self.cli, self.mdu)
        rows = check_state(report, TARGET, 'blocked')
        self.assertEqual([r['occurrence'] for r in rows], [1, 2])
        self.assertEqual([r['value'] for r in rows], ['0.023', '0.023'])
        self.assertLess(rows[0]['byte_start'], rows[1]['byte_start'])

    def test_chezy_sixtyfive_is_not_manning_and_does_not_gain_unit_evidence(self):
        replace(self.mdu, 'physics/uniffricttype', '0')
        replace(self.mdu, TARGET, '65')
        row = check_state(inspect_checked(self.cli, self.mdu), TARGET, 'blocked')[0]
        self.assertIsNone(row['unit_evidence']['unit'])
        self.assertEqual(row['unit_evidence']['friction_law']['law'], 'Chezy')

    @unittest.skipUnless(find_spec('netCDF4') and find_spec('numpy'), 'Connected positive edits require optional run extra')
    def test_actual_connected_preview_apply_hash_units_and_exact_span_preservation(self):
        # The independent portable writer is an input fixture, never an oracle
        # that calls the product mesh/context/eligibility implementation.
        from research.workflows.verification.verify_fields import portable_channel
        template = portable_channel(self.root / 'connected')
        replace(template, 'geometry/bedlevtype', '3')
        outcomes = edit_gate(self.cli, template, self.root / 'edit_cases')
        self.assertEqual(len(outcomes), 4)
        self.assertTrue(all(c['exact_span_only'] for c in outcomes[:3]))


if __name__ == '__main__': unittest.main()
