# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""Load test runs: Odoo is the control plane, Locust the engine.

A run spawns Locust as a detached child process (never imported into
Odoo - it monkey-patches with gevent) in web mode with --autostart, then
drives it through its REST API: live stats while running, /stop to end
it. Final numbers come from Locust's CSV export.
"""

import csv
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time

import requests

try:
    import psutil
except ImportError:
    psutil = None

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config

_logger = logging.getLogger(__name__)

RUNNING_STATES = ("running",)


class LoadtestRun(models.Model):
    _name = "loadtest.run"
    _description = "Load Test Run"
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    scenario_id = fields.Many2one("loadtest.scenario", required=True, ondelete="cascade")
    batch_id = fields.Many2one(related="scenario_id.batch_id")
    state = fields.Selection(
        [("draft", "Draft"), ("running", "Running"), ("done", "Done"), ("failed", "Failed")],
        default="draft",
        required=True,
    )
    started_at = fields.Datetime(readonly=True)
    ended_at = fields.Datetime(readonly=True)
    port = fields.Integer(readonly=True)
    run_dir = fields.Char(readonly=True)
    process_ids = fields.One2many("loadtest.run.process", "run_id", readonly=True)

    # live (polled from Locust while running)
    live_state = fields.Char(readonly=True)
    live_users = fields.Integer(readonly=True)
    live_rps = fields.Float(readonly=True, digits=(12, 1))
    live_fail_ratio = fields.Float(readonly=True, digits=(6, 4))
    live_requests = fields.Integer(readonly=True)
    live_failures = fields.Integer(readonly=True)

    # final summary (Locust CSV "Aggregated" row)
    total_requests = fields.Integer(readonly=True)
    total_failures = fields.Integer(readonly=True)
    failure_ratio = fields.Float(readonly=True, digits=(6, 4))
    rps_avg = fields.Float(readonly=True, digits=(12, 1))
    p50 = fields.Float(readonly=True, string="p50 (ms)")
    p95 = fields.Float(readonly=True, string="p95 (ms)")
    p99 = fields.Float(readonly=True, string="p99 (ms)")
    result_ids = fields.One2many("loadtest.run.result", "run_id", readonly=True)
    sample_ids = fields.One2many("loadtest.run.sample", "run_id", readonly=True)

    # latest system sample (live view)
    sys_cpu = fields.Float(readonly=True, string="CPU %")
    sys_mem = fields.Float(readonly=True, string="RAM %")
    sys_rss_mb = fields.Float(readonly=True, string="Odoo RSS (MB)")
    sys_pg_active = fields.Integer(readonly=True, string="PG active")
    sys_pg_total = fields.Integer(readonly=True, string="PG connections")

    # system summary over the whole run
    avg_cpu = fields.Float(readonly=True, string="Avg CPU %")
    max_cpu = fields.Float(readonly=True, string="Max CPU %")
    avg_mem = fields.Float(readonly=True, string="Avg RAM %")
    max_mem = fields.Float(readonly=True, string="Max RAM %")
    avg_rss_mb = fields.Float(readonly=True, string="Avg RSS (MB)")
    max_rss_mb = fields.Float(readonly=True, string="Max RSS (MB)")
    avg_pg_active = fields.Float(readonly=True, string="Avg PG active")
    max_pg_active = fields.Integer(readonly=True, string="Max PG active")
    log_excerpt = fields.Text(readonly=True)
    notes = fields.Text()
    sentry_url = fields.Char(compute="_compute_sentry_url")

    # ------------------------------------------------------------------
    @api.depends("scenario_id", "scenario_id.run_ids")
    def _compute_name(self):
        for run in self:
            if not run.scenario_id:
                run.name = "Run"
                continue
            siblings = run.scenario_id.run_ids.filtered(lambda r: r.id and run.id and r.id <= run.id)
            run.name = f"{run.scenario_id.name} #{len(siblings) or 1}"

    @api.depends("started_at", "ended_at")
    def _compute_sentry_url(self):
        org = config.get("loadtest_sentry_org")
        for run in self:
            if org and run.started_at:
                end = run.ended_at or fields.Datetime.now()
                run.sentry_url = (
                    f"https://{org}.sentry.io/explore/traces/"
                    f"?start={run.started_at.isoformat()}Z&end={end.isoformat()}Z"
                )
            else:
                run.sentry_url = False

    # ------------------------------------------------------------------
    # process plumbing
    @staticmethod
    def _free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    def _pid_alive(pid):
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _locustfile(self):
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locustfiles", "journeys.py")

    def _csv_prefix(self):
        self.ensure_one()
        return os.path.join(self.run_dir, "stats")

    def _child_env(self):
        self.ensure_one()
        batch = self.scenario_id.batch_id
        env = dict(os.environ)
        env.update(
            ODOO_DB=self.env.cr.dbname,
            LOADTEST_LOGINS=",".join(batch.user_ids.mapped("login")),
            LOADTEST_PASSWORD=batch.password or "",
            LOADTEST_WEIGHTS=json.dumps(self.scenario_id._weights()),
        )
        return env

    def _base_command(self):
        self.ensure_one()
        scenario = self.scenario_id
        return [
            sys.executable, "-m", "locust",
            "-f", self._locustfile(),
            *scenario._weights().keys(),
            "--host", scenario.target_url,
        ]

    def _master_command(self):
        self.ensure_one()
        scenario = self.scenario_id
        cmd = self._base_command() + [
            "--web-host", "127.0.0.1", "--web-port", str(self.port),
            "--autostart", "--autoquit", "10",
            "-u", str(scenario.user_count), "-r", str(scenario.spawn_rate),
            "--csv", self._csv_prefix(),
        ]
        if scenario.duration:
            cmd += ["-t", f"{scenario.duration}s"]
        if scenario.worker_count:
            cmd += ["--master", "--expect-workers", str(scenario.worker_count)]
        return cmd

    def _spawn(self, cmd, logname):
        self.ensure_one()
        with open(os.path.join(self.run_dir, logname), "ab") as log:
            proc = subprocess.Popen(
                cmd, cwd=self.run_dir, env=self._child_env(),
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        return proc.pid

    # ------------------------------------------------------------------
    # actions
    def action_start(self):
        for run in self:
            scenario = run.scenario_id
            scenario.batch_id._check_enabled()
            if run.state in RUNNING_STATES:
                raise UserError("This run is already running.")
            if not scenario.batch_id.user_ids:
                raise UserError("The batch has no test users - generate them first.")
            other = self.search([("scenario_id", "=", scenario.id), ("state", "in", RUNNING_STATES), ("id", "!=", run.id)], limit=1)
            if other:
                raise UserError(f"{other.name} is still running for this scenario.")

            run_dir = os.path.join(config["data_dir"], "loadtest", f"run_{run.id}")
            os.makedirs(run_dir, exist_ok=True)
            run.write({
                "port": self._free_port(), "run_dir": run_dir,
                "state": "running", "started_at": fields.Datetime.now(), "ended_at": False,
                "live_state": "starting", "live_users": 0, "live_rps": 0, "live_fail_ratio": 0,
                "live_requests": 0, "live_failures": 0,
                "total_requests": 0, "total_failures": 0, "failure_ratio": 0, "rps_avg": 0,
                "p50": 0, "p95": 0, "p99": 0, "log_excerpt": False,
                "result_ids": [(5, 0, 0)], "process_ids": [(5, 0, 0)], "sample_ids": [(5, 0, 0)],
                "sys_cpu": 0, "sys_mem": 0, "sys_rss_mb": 0, "sys_pg_active": 0, "sys_pg_total": 0,
                "avg_cpu": 0, "max_cpu": 0, "avg_mem": 0, "max_mem": 0,
                "avg_rss_mb": 0, "max_rss_mb": 0, "avg_pg_active": 0, "max_pg_active": 0,
            })
            processes = [(0, 0, {"role": "master", "pid": run._spawn(run._master_command(), "master.log")})]
            for i in range(scenario.worker_count):
                worker_cmd = run._base_command() + ["--worker", "--master-host", "127.0.0.1"]
                processes.append((0, 0, {"role": "worker", "pid": run._spawn(worker_cmd, f"worker_{i + 1}.log")}))
            run.write({"process_ids": processes})
            _logger.info("loadtest run %s started on port %s", run.id, run.port)
        return True

    def _locust_get(self, path, timeout=3):
        self.ensure_one()
        try:
            response = requests.get(f"http://127.0.0.1:{self.port}{path}", timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            return None

    def _system_snapshot(self):
        """CPU/RAM/RSS of this host and PG connections of this database.
        Samples the machine Odoo runs on - when target_url points at a
        remote instance, these numbers describe the local host only."""
        snapshot = {}
        if psutil is not None:
            snapshot["cpu"] = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            snapshot["mem"] = memory.percent
            snapshot["rss_mb"] = psutil.Process().memory_info().rss / (1024 * 1024)
        self.env.cr.execute(
            """SELECT count(*) FILTER (WHERE state = 'active'), count(*)
               FROM pg_stat_activity WHERE datname = current_database()"""
        )
        active, total = self.env.cr.fetchone()
        snapshot["pg_active"], snapshot["pg_total"] = active or 0, total or 0
        return snapshot

    def _take_sample(self, stats):
        self.ensure_one()
        snap = self._system_snapshot()
        total = next((s for s in (stats or {}).get("stats", []) if s.get("name") == "Aggregated"), {})
        self.env["loadtest.run.sample"].create({
            "run_id": self.id,
            "cpu": snap.get("cpu", 0.0), "mem": snap.get("mem", 0.0),
            "rss_mb": snap.get("rss_mb", 0.0),
            "pg_active": snap["pg_active"], "pg_total": snap["pg_total"],
            "users": (stats or {}).get("user_count", 0),
            "rps": (stats or {}).get("total_rps", 0.0),
            "fail_ratio": (stats or {}).get("fail_ratio", 0.0),
            "requests": total.get("num_requests", 0),
        })
        self.write({
            "sys_cpu": snap.get("cpu", 0.0), "sys_mem": snap.get("mem", 0.0),
            "sys_rss_mb": snap.get("rss_mb", 0.0),
            "sys_pg_active": snap["pg_active"], "sys_pg_total": snap["pg_total"],
        })

    def _summarize_samples(self):
        self.ensure_one()
        samples = self.sample_ids
        if not samples:
            return {}
        count = len(samples)
        return {
            "avg_cpu": sum(samples.mapped("cpu")) / count, "max_cpu": max(samples.mapped("cpu")),
            "avg_mem": sum(samples.mapped("mem")) / count, "max_mem": max(samples.mapped("mem")),
            "avg_rss_mb": sum(samples.mapped("rss_mb")) / count, "max_rss_mb": max(samples.mapped("rss_mb")),
            "avg_pg_active": sum(samples.mapped("pg_active")) / count,
            "max_pg_active": max(samples.mapped("pg_active")),
        }

    def action_refresh(self):
        for run in self.filtered(lambda r: r.state in RUNNING_STATES):
            master = run.process_ids.filtered(lambda p: p.role == "master")[:1]
            alive = self._pid_alive(master.pid)
            stats = run._locust_get("/stats/requests") if alive else None
            try:
                run._take_sample(stats)
            except Exception:
                _logger.debug("loadtest sample failed", exc_info=True)
            if stats:
                run._apply_live_stats(stats)
            if not alive or (stats and stats.get("state") in ("stopped", "missing")):
                run._finalize()
        return True

    def _apply_live_stats(self, stats):
        self.ensure_one()
        entries = [s for s in stats.get("stats", []) if s.get("name") != "Aggregated"]
        total = next((s for s in stats.get("stats", []) if s.get("name") == "Aggregated"), {})
        self.write({
            "live_state": stats.get("state"),
            "live_users": stats.get("user_count", 0),
            "live_rps": stats.get("total_rps", 0.0),
            "live_fail_ratio": stats.get("fail_ratio", 0.0),
            "live_requests": total.get("num_requests", 0),
            "live_failures": total.get("num_failures", 0),
            "result_ids": [(5, 0, 0)] + [(0, 0, self._result_values_from_live(s)) for s in entries],
        })

    @staticmethod
    def _percentile(entry, fraction):
        for key, value in entry.items():
            if key.startswith("response_time_percentile") and key.endswith(str(fraction)):
                return value or 0.0
        return 0.0

    def _result_values_from_live(self, entry):
        return {
            "name": entry.get("name"), "method": entry.get("method") or "",
            "requests": entry.get("num_requests", 0), "failures": entry.get("num_failures", 0),
            "median": entry.get("median_response_time") or 0.0, "avg": entry.get("avg_response_time") or 0.0,
            "p95": self._percentile(entry, "0.95"), "p99": self._percentile(entry, "0.99"),
            "rps": entry.get("current_rps") or 0.0,
        }

    def _ingest_csv(self):
        """Locust's CSV export is the authoritative final result."""
        self.ensure_one()
        path = self._csv_prefix() + "_stats.csv"
        if not os.path.exists(path):
            return False
        lines, summary = [], {}
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                values = {
                    "name": row["Name"], "method": row.get("Type") or "",
                    "requests": int(float(row["Request Count"] or 0)), "failures": int(float(row["Failure Count"] or 0)),
                    "median": float(row.get("Median Response Time") or 0), "avg": float(row.get("Average Response Time") or 0),
                    "p95": float(row.get("95%") or 0), "p99": float(row.get("99%") or 0),
                    "rps": float(row.get("Requests/s") or 0),
                }
                if row["Name"] == "Aggregated":
                    summary = {
                        "total_requests": values["requests"], "total_failures": values["failures"],
                        "failure_ratio": (values["failures"] / values["requests"]) if values["requests"] else 0.0,
                        "rps_avg": values["rps"], "p50": values["median"], "p95": values["p95"], "p99": values["p99"],
                    }
                else:
                    lines.append((0, 0, values))
        self.write(dict(summary, result_ids=[(5, 0, 0)] + lines))
        return bool(lines)

    def _terminate_processes(self):
        self.ensure_one()
        for proc in self.process_ids:
            if self._pid_alive(proc.pid):
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass

    def _finalize(self):
        self.ensure_one()
        self._terminate_processes()
        has_results = self._ingest_csv()
        excerpt = ""
        log_path = os.path.join(self.run_dir or "", "master.log")
        if self.run_dir and os.path.exists(log_path):
            with open(log_path, errors="replace") as fh:
                excerpt = "".join(fh.readlines()[-40:])
        self.write(dict(self._summarize_samples(),
            **{
            "state": "done" if has_results else "failed",
            "ended_at": fields.Datetime.now(),
            "live_state": "stopped",
            "log_excerpt": excerpt,
        }))
        _logger.info("loadtest run %s finished: %s", self.id, self.state)

    def action_stop(self):
        for run in self.filtered(lambda r: r.state in RUNNING_STATES):
            run._locust_get("/stop")
            time.sleep(2)  # let Locust flush its CSV
            run._finalize()
        return True

    def action_restart(self):
        self.action_stop()
        return self.action_start()

    def action_repeat(self):
        self.ensure_one()
        new = self.create({"scenario_id": self.scenario_id.id, "notes": self.notes})
        new.action_start()
        return {"type": "ir.actions.act_window", "res_model": "loadtest.run", "res_id": new.id, "view_mode": "form"}

    def action_open_sentry(self):
        self.ensure_one()
        if not self.sentry_url:
            raise UserError("Set loadtest_sentry_org in the server configuration to link runs to Sentry.")
        return {"type": "ir.actions.act_url", "url": self.sentry_url, "target": "new"}

    @api.ondelete(at_uninstall=False)
    def _unlink_except_running(self):
        if any(run.state in RUNNING_STATES for run in self):
            raise UserError("Stop the run before deleting it.")

    @api.model
    def _cron_poll(self):
        self.search([("state", "in", RUNNING_STATES)]).action_refresh()


class LoadtestRunProcess(models.Model):
    _name = "loadtest.run.process"
    _description = "Load Test Run Process"

    run_id = fields.Many2one("loadtest.run", required=True, ondelete="cascade")
    role = fields.Selection([("master", "Master"), ("worker", "Worker")], required=True)
    pid = fields.Integer(required=True)
    alive = fields.Boolean(compute="_compute_alive")

    def _compute_alive(self):
        for proc in self:
            proc.alive = LoadtestRun._pid_alive(proc.pid)


class LoadtestRunResult(models.Model):
    _name = "loadtest.run.result"
    _description = "Load Test Run Result Line"
    _order = "requests desc, id"

    run_id = fields.Many2one("loadtest.run", required=True, ondelete="cascade")
    name = fields.Char(required=True)
    method = fields.Char()
    requests = fields.Integer()
    failures = fields.Integer()
    median = fields.Float(string="Median (ms)")
    avg = fields.Float(string="Avg (ms)")
    p95 = fields.Float(string="p95 (ms)")
    p99 = fields.Float(string="p99 (ms)")
    rps = fields.Float(string="req/s", digits=(12, 2))


class LoadtestRunSample(models.Model):
    """One point on the run timeline: system + Locust state together."""

    _name = "loadtest.run.sample"
    _description = "Load Test Run Sample"
    _order = "id"

    run_id = fields.Many2one("loadtest.run", required=True, ondelete="cascade")
    sampled_at = fields.Datetime(default=fields.Datetime.now, required=True)
    cpu = fields.Float(string="CPU %")
    mem = fields.Float(string="RAM %")
    rss_mb = fields.Float(string="Odoo RSS (MB)")
    pg_active = fields.Integer(string="PG active")
    pg_total = fields.Integer(string="PG connections")
    users = fields.Integer()
    rps = fields.Float(digits=(12, 1))
    fail_ratio = fields.Float(digits=(6, 4))
    requests = fields.Integer()
