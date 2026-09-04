# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.addons.queue_job.tests.common import trap_jobs
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import config


@tagged("post_install", "-at_install")
class TestBatchJobs(TransactionCase):
    def setUp(self):
        super().setUp()
        self.enabled = patch.dict(config.options, {"loadtest_enabled": "true"})
        self.enabled.start()
        self.addCleanup(self.enabled.stop)
        self.batch = self.env["loadtest.batch"].create(
            {
                "user_count": 2,
                "partner_count": 5,
                "product_count": 7,
                "order_count": 3,
                "generation_mode": "jobs",
                "job_chunk_size": 3,
            }
        )

    def test_generate_all_builds_graph(self):
        with trap_jobs() as trap:
            self.batch.action_generate()
            # users inline; partners 2 chunks + products 3 chunks + orders 1 + finalize
            trap.assert_jobs_count(7)
            trap.assert_jobs_count(2, only=self.batch._generate_partners_chunk)
            trap.assert_jobs_count(3, only=self.batch._generate_products_chunk)
            trap.assert_jobs_count(1, only=self.batch._generate_orders_chunk)
            trap.assert_jobs_count(1, only=self.batch._job_finalize)
            self.assertEqual(len(self.batch.user_ids), 2)
            for job in trap.enqueued_jobs:
                self.assertEqual(job.channel, "root.loadtest")
            trap.perform_enqueued_jobs()
        self.batch.invalidate_recordset()
        self.assertEqual(
            (
                self.batch.generated_partner_count,
                self.batch.generated_product_count,
                self.batch.generated_order_count,
            ),
            (5, 7, 3),
        )

    def test_stored_jobs_are_tagged_and_counted(self):
        # real delay(): the queue.job records exist (the runner never picks
        # them up inside the test transaction), so the counters can be checked
        self.batch.action_generate()
        self.assertEqual(self.batch.job_run, 1)
        jobs = self.batch._batch_jobs()
        self.assertEqual(len(jobs), 7)
        self.assertTrue(all(j.loadtest_batch_id == self.batch for j in jobs))
        self.assertEqual(self.batch.job_count, 7)
        self.assertEqual(self.batch.job_state, "running")
        self.assertEqual(self.batch.job_progress, 0.0)
        action = self.batch.action_view_jobs()
        self.assertIn(("loadtest_batch_run", "=", 1), action["domain"])
        with self.assertRaises(UserError):  # a run is still active
            self.batch.action_generate_products()
        # the finalize job waits for everything else
        finalize = jobs.filtered(lambda j: j.method_name == "_job_finalize")
        self.assertEqual(finalize.state, "wait_dependencies")

    def test_inline_mode_unchanged(self):
        self.batch.generation_mode = "inline"
        with trap_jobs() as trap:
            self.batch.action_generate_products()
            trap.assert_jobs_count(0)
        self.assertEqual(self.batch.generated_product_count, 7)

    def test_cleanup_reschedules_until_empty(self):
        self.batch.generation_mode = "inline"
        self.batch.action_generate()
        self.batch.generation_mode = "jobs"
        with trap_jobs() as trap:
            self.batch.action_cleanup()
            trap.assert_jobs_count(1, only=self.batch._job_cleanup)
            # every run deletes one chunk and enqueues the follow-up, which the
            # trap performs in the next round: orders 3 (1 chunk), products 7
            # (3 chunks), partners 5 (2 chunks), plus one final run that finds
            # nothing left and archives the users
            rounds = 0
            while trap.enqueued_jobs:
                trap.perform_enqueued_jobs()
                rounds += 1
            self.assertEqual(rounds, 7)
        self.batch.invalidate_recordset()
        self.assertEqual(self.batch.state, "draft")
        self.assertTrue(all(not u.active for u in self.batch.user_ids))

    def test_cleanup_respects_order(self):
        self.batch.generation_mode = "inline"
        self.batch.action_generate()
        self.batch.generation_mode = "jobs"
        with self.assertRaises(UserError):
            self.batch.action_cleanup_products()  # orders still there
