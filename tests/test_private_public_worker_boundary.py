"""The ordinary public workflow must never load private recordings."""
import asyncio
import io
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from unittest.mock import patch
from worker.jobs import process_set

class PublicWorkerBoundaryTests(unittest.TestCase):
    def test_load_filters_private_run_and_submission(self):
        with patch.object(process_set, "fetch_one", return_value=None) as fetch:
            with self.assertRaises(RuntimeError):
                process_set._load_run("synthetic-private-id")
            sql, params = fetch.call_args.args
            self.assertIn("r.publication_visibility = 'public'", sql)
            self.assertIn("s.visibility = 'public'", sql)
            self.assertEqual(params, ("synthetic-private-id",))

    def test_all_public_entrypoints_reject_before_side_effects_or_private_logs(self):
        for phase in ("bootstrap", "recognize", "publish", "finalize", "run"):
            with self.subTest(phase=phase), ExitStack() as stack:
                stack.enter_context(patch.object(process_set, "fetch_one", return_value=None))
                side_effects = [stack.enter_context(patch.object(process_set, name)) for name in (
                    "claim_workflow_run", "insert_worker_event", "mark_run_stage", "mark_set_run",
                    "update_set_run_metadata", "upsert_segment_hit", "initialize_set_run_leases",
                    "_publish_set_run_payload", "post_callback", "finalize_submission_from_runs",
                )]
                output = io.StringIO()
                stack.enter_context(redirect_stdout(output))
                stack.enter_context(redirect_stderr(output))
                with self.assertRaisesRegex(RuntimeError, "was not found"):
                    if phase == "finalize":
                        process_set.finalize_phase("synthetic-private-id", bootstrap_result="failure", recognize_result="skipped", publish_result="skipped")
                    else:
                        fn = getattr(process_set, f"{phase}_phase")
                        kwargs = {"slot_index": 0} if phase == "recognize" else {}
                        asyncio.run(fn("synthetic-private-id", **kwargs))
                for effect in side_effects:
                    effect.assert_not_called()
                self.assertNotIn("PRIVATE_SOURCE_SENTINEL", output.getvalue())
                self.assertEqual(output.getvalue(), "")

if __name__ == "__main__":
    unittest.main()
