"""B04 peer-owned paths/data must survive directory-publication cleanup races."""
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_boundary_export_staging import run_case


class ExportStagingOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B04-PEER-OWNERSHIP-");self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def test_publish_success_must_not_delete_reoccupation_of_old_stage_path(self):
        result=run_case(self.root/"success","success_reoccupation")
        self.assertTrue(result["triggered"])
        self.assertTrue(result["peer_survived"],result)
        self.assertTrue(result["published_complete"],result)
        self.assertEqual(result["CLI_exit_code"],0,result)
        self.assertTrue(result["original_inputs_unchanged"])

    def test_failed_publish_must_not_delete_foreign_replacement_after_original_stage_renamed(self):
        result=run_case(self.root/"replacement","failed_renamed_replacement")
        self.assertTrue(result["triggered"])
        self.assertTrue(result["peer_survived"],result)
        self.assertTrue(result["held_original_stage_survived"],result)
        self.assertFalse(result["destination_exists"])
        self.assertNotEqual(result["CLI_exit_code"],0)
        self.assertTrue(result["original_inputs_unchanged"])

    def test_failed_publish_preserves_foreign_extra_file_even_inside_original_stage(self):
        for nested in (False,True):
            with self.subTest(nested=nested):
                result=run_case(self.root/("extra-nested" if nested else "extra"),"failed_foreign_extra_file",nested=nested)
                self.assertTrue(result["triggered"])
                self.assertTrue(result["peer_survived"],result)
                self.assertFalse(result["destination_exists"])
                self.assertNotEqual(result["CLI_exit_code"],0)
                self.assertTrue(result["original_inputs_unchanged"])


if __name__=="__main__":unittest.main()
