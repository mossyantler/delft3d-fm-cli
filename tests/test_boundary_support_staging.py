"""B10 staging revalidation/peer ownership through file-only publication."""
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_boundary_support_fixture import HookCLI,PublicCLI
from research.workflows.verification.verify_boundary_support_staging import run_case

INTERFACE="cli"


class BoundarySupportStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        factory=HookCLI if INTERFACE=="hooks" else PublicCLI
        if "boundary support" not in factory().invoke("schema","inspect")["commands"]:
            raise AssertionError("B10 public support not registered; hooks-only stage probe is separate")
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B10-PEER-OWNERSHIP-");self.addCleanup(temp.cleanup);self.root=Path(temp.name)
    def run_case(self,name):return run_case(self.root/name,name,interface=INTERFACE)
    def test_success_reoccupation_after_consumed_temp_path_survives(self):
        r=self.run_case("success_reoccupation")
        self.assertTrue(r["triggered"]);self.assertTrue(r["peer_survived"],r)
        self.assertEqual(r["CLI_exit_code"],0);self.assertTrue(r["target_semantics_correct"]);self.assertTrue(r["original_other_inputs_unchanged"])
    def test_failed_publish_foreign_replacement_is_not_removed(self):
        r=self.run_case("failed_renamed_replacement")
        self.assertTrue(r["triggered"]);self.assertTrue(r["peer_survived"],r);self.assertTrue(r["held_original_survived"])
        self.assertTrue(r["target_unchanged"]);self.assertNotEqual(r["CLI_exit_code"],0);self.assertTrue(r["original_other_inputs_unchanged"])
    def test_failed_publish_same_inode_foreign_bytes_are_not_deleted(self):
        r=self.run_case("failed_same_inode_content")
        self.assertEqual(r["stage_identity"],r["peer_identity"])
        self.assertTrue(r["peer_survived"],r);self.assertTrue(r["target_unchanged"]);self.assertNotEqual(r["CLI_exit_code"],0)
    def test_owned_failed_stage_is_cleaned_without_partial_target(self):
        r=self.run_case("failed_owned_stage")
        self.assertTrue(r["triggered"]);self.assertTrue(r["target_unchanged"]);self.assertEqual(r["remaining_stage_names"],[])
        self.assertNotEqual(r["CLI_exit_code"],0);self.assertTrue(r["original_other_inputs_unchanged"])
    def test_full_request_bytes_rechecked_after_fsync_before_replace(self):
        r=self.run_case("precommit_request_change")
        self.assertTrue(r["triggered"]);self.assertTrue(r["target_unchanged"]);self.assertEqual(r["remaining_stage_names"],[])
        self.assertNotEqual(r["CLI_exit_code"],0);self.assertTrue(r["original_other_inputs_unchanged"])


if __name__=="__main__":unittest.main()
