import os
import unittest
from unittest.mock import patch

from worker.scheduler import build_scheduler_plan


class SchedulerPlanTests(unittest.TestCase):
    def test_auto_plan_targets_twelve_slots_and_two_leases_per_slot_for_benchmark_set(self):
        with patch.dict(os.environ, {}, clear=False):
            plan = build_scheduler_plan(240)

        self.assertEqual(plan.mode, "auto")
        self.assertEqual(plan.slot_count, 12)
        self.assertEqual(plan.lease_size, 10)
        self.assertEqual(plan.lease_count, 24)
        self.assertEqual(plan.segments_per_slot, 20.0)
        self.assertEqual(plan.leases_per_slot, 2.0)

    def test_auto_plan_caps_slot_count_and_scales_lease_size_for_longer_sets(self):
        with patch.dict(os.environ, {}, clear=False):
            plan = build_scheduler_plan(480)

        self.assertEqual(plan.slot_count, 12)
        self.assertEqual(plan.lease_size, 20)
        self.assertEqual(plan.lease_count, 24)
        self.assertEqual(plan.leases_per_slot, 2.0)

    def test_manual_plan_preserves_explicit_benchmark_values(self):
        with patch.dict(
            os.environ,
            {
                "RECOGNITION_SLOT_COUNT_REQUESTED": "12",
                "LEASE_SIZE_REQUESTED": "15",
            },
            clear=False,
        ):
            plan = build_scheduler_plan(240)

        self.assertEqual(plan.mode, "manual")
        self.assertEqual(plan.slot_count, 12)
        self.assertEqual(plan.lease_size, 15)
        self.assertEqual(plan.lease_count, 16)
        self.assertEqual(plan.leases_per_slot, 1.33)

    def test_auto_slot_count_does_not_exceed_available_leases_when_only_lease_size_is_manual(self):
        with patch.dict(
            os.environ,
            {
                "LEASE_SIZE_REQUESTED": "24",
            },
            clear=False,
        ):
            plan = build_scheduler_plan(240)

        self.assertEqual(plan.mode, "hybrid")
        self.assertEqual(plan.lease_size, 24)
        self.assertEqual(plan.lease_count, 10)
        self.assertEqual(plan.slot_count, 10)


if __name__ == "__main__":
    unittest.main()
