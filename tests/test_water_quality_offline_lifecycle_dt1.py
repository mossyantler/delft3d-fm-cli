"""Prospective dt1 sampling must precede a real lifecycle trigger."""
import copy
import unittest
from research.workflows.verification.verify_water_quality_offline_lifecycle_dt1_replay import sample_gate


class Dt1SamplingTests(unittest.TestCase):
    def samples(self):
        return [{"monotonic_ns": n, "target": {"state": "live"}, "control": {"state": "live"}}
                for n in (0, 100_000_000, 200_000_000)]

    def test_three_real_live_samples_over_point_two_seconds(self):
        self.assertTrue(sample_gate(self.samples()))

    def test_two_samples_do_not_satisfy_gate(self):
        self.assertFalse(sample_gate(self.samples()[::2]))

    def test_three_fast_samples_do_not_satisfy_gate(self):
        samples = self.samples(); samples[-1]["monotonic_ns"] -= 1
        self.assertFalse(sample_gate(samples))

    def test_peer_or_target_exit_rejects_overlap(self):
        for role in ("target", "control"):
            samples = copy.deepcopy(self.samples()); samples[1][role]["state"] = "exited"
            self.assertFalse(sample_gate(samples))


if __name__ == "__main__":
    unittest.main()
