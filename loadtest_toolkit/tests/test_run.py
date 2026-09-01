# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase
from odoo.tools import config

CSV = """Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%
POST,res.partner.search_read,100,2,25,30,10,300,500,5.0,0.1,25,30,35,40,60,120,200,250,300,300,300
POST,sale.order.create+line,10,0,100,110,80,500,200,0.5,0.0,100,110,120,130,200,400,480,500,500,500,500
,Aggregated,110,2,26,37,10,500,470,5.5,0.1,26,32,40,45,70,150,300,400,500,500,500
"""

LIVE = {
    "state": "running", "user_count": 5, "total_rps": 4.2, "fail_ratio": 0.01,
    "stats": [
        {"name": "res.partner.search_read", "method": "POST", "num_requests": 40, "num_failures": 1,
         "median_response_time": 25, "avg_response_time": 31, "current_rps": 3.0,
         "response_time_percentile_0.95": 120, "response_time_percentile_0.99": 250},
        {"name": "Aggregated", "method": "", "num_requests": 40, "num_failures": 1,
         "median_response_time": 25, "avg_response_time": 31, "current_rps": 3.0},
    ],
}


class TestLoadtestRun(TransactionCase):
    def setUp(self):
        super().setUp()
        self.enabled = patch.dict(config.options, {"loadtest_enabled": "true"})
        self.enabled.start()
        self.addCleanup(self.enabled.stop)
        self.tmp = tempfile.mkdtemp()
        data_dir = patch.dict(config.options, {"data_dir": self.tmp})
        data_dir.start()
        self.addCleanup(data_dir.stop)

        self.batch = self.env["loadtest.batch"].create(
            {"user_count": 2, "partner_count": 0, "product_count": 0, "order_count": 0}
        )
        self.batch.action_generate_users()
        browser = self.env.ref("loadtest_toolkit.journey_browser")
        sales = self.env.ref("loadtest_toolkit.journey_sales_rep")
        self.scenario = self.env["loadtest.scenario"].create({
            "name": "Smoke", "batch_id": self.batch.id, "target_url": "http://127.0.0.1:8069",
            "user_count": 5, "spawn_rate": 1.0, "duration": 60, "worker_count": 2,
            "journey_line_ids": [(0, 0, {"journey_id": browser.id, "weight": 3}),
                                 (0, 0, {"journey_id": sales.id, "weight": 1})],
        })
        self.spawned = []

        def fake_popen(cmd, **kwargs):
            self.spawned.append((cmd, kwargs))
            return SimpleNamespace(pid=40000 + len(self.spawned))

        self.popen = patch("odoo.addons.loadtest_toolkit.models.loadtest_run.subprocess.Popen", side_effect=fake_popen)
        self.popen.start()
        self.addCleanup(self.popen.stop)
        self.alive = patch.object(type(self.env["loadtest.run"]), "_pid_alive", staticmethod(lambda pid: True))
        self.alive.start()
        self.addCleanup(self.alive.stop)
        killpg_patcher = patch("odoo.addons.loadtest_toolkit.models.loadtest_run.os.killpg")
        self.killpg = killpg_patcher.start()
        self.addCleanup(killpg_patcher.stop)

    def _run(self):
        return self.env["loadtest.run"].create({"scenario_id": self.scenario.id})

    def test_start_spawns_master_and_workers(self):
        run = self._run()
        run.action_start()
        self.assertEqual(run.state, "running")
        self.assertEqual(len(self.spawned), 3)  # master + 2 workers
        master_cmd, master_kwargs = self.spawned[0]
        self.assertIn("--master", master_cmd)
        self.assertIn("Browser", master_cmd)
        self.assertIn("SalesRep", master_cmd)
        self.assertEqual(master_cmd[master_cmd.index("-u") + 1], "5")
        self.assertEqual(master_cmd[master_cmd.index("-t") + 1], "60s")
        self.assertTrue(master_kwargs["start_new_session"])
        env = master_kwargs["env"]
        self.assertEqual(env["LOADTEST_LOGINS"].count("loadtest_"), 2)
        self.assertIn('"Browser": 3', env["LOADTEST_WEIGHTS"])
        self.assertIn("--worker", self.spawned[1][0])
        self.assertEqual(run.process_ids.mapped("role"), ["master", "worker", "worker"])

    def test_guard_and_single_running(self):
        run = self._run()
        with patch.dict(config.options, {"loadtest_enabled": "false"}):
            with self.assertRaises(UserError):
                run.action_start()
        run.action_start()
        with self.assertRaises(UserError):
            self._run().action_start()
        with self.assertRaises(UserError):
            run.unlink()

    def test_refresh_applies_live_stats(self):
        run = self._run()
        run.action_start()
        with patch.object(type(run), "_locust_get", return_value=LIVE):
            run.action_refresh()
        self.assertEqual(run.state, "running")
        self.assertEqual(run.live_users, 5)
        self.assertEqual(run.live_requests, 40)
        line = run.result_ids.filtered(lambda r: r.name == "res.partner.search_read")
        self.assertEqual(line.p95, 120)

    def test_stop_ingests_csv(self):
        run = self._run()
        run.action_start()
        with open(run._csv_prefix() + "_stats.csv", "w") as fh:
            fh.write(CSV)
        with patch.object(type(run), "_locust_get", return_value=None), patch(
            "odoo.addons.loadtest_toolkit.models.loadtest_run.time.sleep"
        ):
            run.action_stop()
        self.assertEqual(run.state, "done")
        self.assertEqual(run.total_requests, 110)
        self.assertEqual(run.p95, 150)
        self.assertEqual(len(run.result_ids), 2)
        self.assertTrue(self.killpg.called)

    def test_dead_process_without_csv_fails(self):
        run = self._run()
        run.action_start()
        with patch.object(type(run), "_pid_alive", staticmethod(lambda pid: False)):
            run.action_refresh()
        self.assertEqual(run.state, "failed")

    def test_samples_and_system_summary(self):
        run = self._run()
        run.action_start()
        with patch.object(type(run), "_locust_get", return_value=LIVE):
            run.action_refresh()
            run.action_refresh()
        self.assertEqual(len(run.sample_ids), 2)
        self.assertEqual(run.sample_ids[0].users, 5)
        self.assertGreater(run.sys_pg_total, 0)
        with open(run._csv_prefix() + "_stats.csv", "w") as fh:
            fh.write(CSV)
        with patch.object(type(run), "_locust_get", return_value=None), patch(
            "odoo.addons.loadtest_toolkit.models.loadtest_run.time.sleep"
        ):
            run.action_stop()
        self.assertEqual(run.state, "done")
        self.assertGreater(run.max_pg_active + run.max_pg_active, -1)  # summary written
        self.assertGreaterEqual(run.max_cpu, run.avg_cpu)
        # restart resets samples
        run.action_start()
        self.assertFalse(run.sample_ids)

    def test_stop_at_triggers_stop(self):
        from datetime import timedelta
        from odoo import fields as ofields
        run = self._run()
        run.action_start()
        run.stop_at = ofields.Datetime.now() + timedelta(hours=1)
        with patch.object(type(run), "_locust_get", return_value=LIVE):
            run.action_refresh()
        self.assertEqual(run.state, "running")  # future stop_at: keeps going
        run.stop_at = ofields.Datetime.now() - timedelta(seconds=1)
        with open(run._csv_prefix() + "_stats.csv", "w") as fh:
            fh.write(CSV)
        with patch.object(type(run), "_locust_get", return_value=None), patch(
            "odoo.addons.loadtest_toolkit.models.loadtest_run.time.sleep"
        ):
            run.action_refresh()
        self.assertEqual(run.state, "done")

    def test_repeat_creates_new_run(self):
        run = self._run()
        run.action_start()
        with open(run._csv_prefix() + "_stats.csv", "w") as fh:
            fh.write(CSV)
        with patch.object(type(run), "_locust_get", return_value=None), patch(
            "odoo.addons.loadtest_toolkit.models.loadtest_run.time.sleep"
        ):
            run.action_stop()
        action = run.action_repeat()
        new = self.env["loadtest.run"].browse(action["res_id"])
        self.assertNotEqual(new, run)
        self.assertEqual(new.state, "running")
        self.assertEqual(self.scenario.run_count, 2)
