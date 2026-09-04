# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.addons.loadtest_toolkit.models.loadtest_batch import LINKED_MODELS
from odoo.addons.queue_job.delay import chain, group
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ACTIVE_JOB_STATES = ("wait_dependencies", "pending", "enqueued", "started")
CLEANUP_ORDER = ("order", "product", "partner")


class LoadtestBatch(models.Model):
    """Generate and clean up a batch in background jobs.

    Generation builds a job graph: one child job per chunk of
    ``job_chunk_size`` records, grouped per kind, partners and products
    in parallel, orders after both, and a finalize job that depends on
    everything. The chunk methods of the base module are idempotent, so a
    failed job can simply be retried. Cleanup runs as a self-rescheduling
    job that deletes one chunk per run until nothing is left."""

    _inherit = "loadtest.batch"

    generation_mode = fields.Selection(
        [("inline", "Inline (in this request)"), ("jobs", "Background jobs")],
        default="jobs",
        required=True,
        help="Inline runs everything in the request that clicks the button; "
        "background jobs split the work into chunks handled by the queue_job "
        "runner, the only option that scales to millions of records.",
    )
    job_chunk_size = fields.Integer(
        default=2000, help="Records created or deleted per job. 1000-5000 is a good range."
    )
    job_channel = fields.Char(
        default="root.loadtest",
        help="queue_job channel for this batch's jobs. Give it capacity in the server "
        "configuration, e.g. channels = root:2,root.loadtest:4",
    )
    job_run = fields.Integer(
        readonly=True,
        copy=False,
        help="Incremented on every enqueue; the job counters below cover the last run only.",
    )
    job_count = fields.Integer(compute="_compute_job_stats")
    job_done_count = fields.Integer(compute="_compute_job_stats")
    job_failed_count = fields.Integer(compute="_compute_job_stats")
    job_active_count = fields.Integer(compute="_compute_job_stats")
    job_progress = fields.Float(compute="_compute_job_stats", help="Done jobs in percent")
    job_state = fields.Selection(
        [("idle", "No jobs"), ("running", "Running"), ("failed", "Failed"), ("done", "Done")],
        compute="_compute_job_stats",
    )

    # ------------------------------------------------------------------
    # job bookkeeping
    def _batch_jobs(self):
        """Jobs of the last enqueue run of this batch."""
        self.ensure_one()
        if not self.job_run:
            return self.env["queue.job"]
        return (
            self.env["queue.job"]
            .sudo()
            .search(
                [("loadtest_batch_id", "=", self.id), ("loadtest_batch_run", "=", self.job_run)]
            )
        )

    def _tag_jobs(self, delayables, run):
        """Stamp the queue.job records created by these delayables with
        the batch and run. Tolerates trapped jobs in tests (no record)."""
        self.ensure_one()
        uuids = []
        for delayable in delayables:
            job = getattr(delayable, "_generated_job", None)
            uuid = getattr(job, "uuid", None)
            if isinstance(uuid, str):
                uuids.append(uuid)
        if uuids:
            self.env["queue.job"].sudo().search([("uuid", "in", uuids)]).write(
                {"loadtest_batch_id": self.id, "loadtest_batch_run": run}
            )

    def _new_run(self):
        self.ensure_one()
        self.job_run = (self.job_run or 0) + 1
        return self.job_run

    @api.depends("job_run")
    def _compute_job_stats(self):
        for batch in self:
            jobs = batch._batch_jobs()
            states = jobs.mapped("state")
            total = len(jobs)
            done = states.count("done")
            failed = states.count("failed")
            active = sum(states.count(s) for s in ACTIVE_JOB_STATES)
            batch.job_count = total
            batch.job_done_count = done
            batch.job_failed_count = failed
            batch.job_active_count = active
            batch.job_progress = (done / total * 100.0) if total else 0.0
            if not total:
                batch.job_state = "idle"
            elif failed:
                batch.job_state = "failed"
            elif active:
                batch.job_state = "running"
            else:
                batch.job_state = "done"

    def _require_no_active_jobs(self):
        for batch in self:
            if batch.job_active_count:
                raise UserError(
                    _("Batch %s still has %s background jobs running or waiting.")
                    % (batch.display_name, batch.job_active_count)
                )

    def action_view_jobs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Jobs: %s") % self.display_name,
            "res_model": "queue.job",
            "view_mode": "list,form",
            "domain": [
                ("loadtest_batch_id", "=", self.id),
                ("loadtest_batch_run", "=", self.job_run),
            ],
            "context": {"search_default_group_by_state": 1},
        }

    def action_requeue_failed_jobs(self):
        for batch in self:
            batch._batch_jobs().filtered(lambda j: j.state == "failed").requeue()
        return True

    def _delayable(self, description):
        self.ensure_one()
        return self.delayable(channel=self.job_channel or None, description=description)

    def _chunk_delayables(self, kind, total):
        """One child delayable per chunk of this kind."""
        self.ensure_one()
        method = getattr(self, f"_generate_{kind}s_chunk")
        size = max(self.job_chunk_size, 1)
        delayables = []
        for start, count in self._chunks(total, size):
            delayable = self._delayable(
                _("Batch %(batch)s: %(kind)ss %(start)s-%(end)s")
                % {"batch": self.id, "kind": kind, "start": start, "end": start + count - 1}
            )
            delayables.append(getattr(delayable, method.__name__)(start, count))
        return delayables

    def _job_finalize(self, kinds):
        """Last job of the graph: log the outcome, nothing else to do -
        the chunks already linked their records to the batch."""
        self.ensure_one()
        _logger.info(
            "loadtest batch %s background generation of %s finished: %s",
            self.id,
            ", ".join(kinds),
            self._summary(),
        )
        return True

    def _enqueue_generation(self, kinds):
        """Build and delay the job graph for the given kinds, in
        dependency order: partners and products in parallel, orders after
        both, then finalize. Users are always created inline first (a
        handful of records, and orders need them)."""
        self.ensure_one()
        self._check_enabled()
        self._require_no_active_jobs()
        stages, delayables = [], []
        first = [
            d
            for kind in ("partner", "product")
            if kind in kinds
            for d in self._chunk_delayables(kind, getattr(self, f"{kind}_count"))
        ]
        if first:
            stages.append(group(*first))
            delayables += first
        if "order" in kinds and self.order_count:
            orders = self._chunk_delayables("order", self.order_count)
            stages.append(group(*orders))
            delayables += orders
        if not stages:
            return False
        finalize = self._delayable(_("Batch %s: finalize") % self.id)._job_finalize(kinds)
        stages.append(finalize)
        delayables.append(finalize)
        chain(*stages).delay()
        self._tag_jobs(delayables, self._new_run())
        return True

    # ------------------------------------------------------------------
    # generation buttons: jobs mode enqueues, inline mode keeps the base behaviour
    def _jobs_mode(self):
        return self.filtered(lambda b: b.generation_mode == "jobs")

    def action_generate_partners(self):
        jobs = self._jobs_mode()
        for batch in jobs:
            if batch._has("partner"):
                raise UserError(_("Partners already generated for this batch."))
            batch._enqueue_generation(["partner"])
        return super(LoadtestBatch, self - jobs).action_generate_partners() if self - jobs else True

    def action_generate_products(self):
        jobs = self._jobs_mode()
        for batch in jobs:
            if batch._has("product"):
                raise UserError(_("Products already generated for this batch."))
            batch._enqueue_generation(["product"])
        return super(LoadtestBatch, self - jobs).action_generate_products() if self - jobs else True

    def action_generate_orders(self):
        jobs = self._jobs_mode()
        for batch in jobs:
            if batch._has("order"):
                raise UserError(_("Orders already generated for this batch."))
            if not (batch.user_ids and batch._has("partner") and batch._has("product")):
                raise UserError(_("Generate users, partners and products before orders."))
            batch._enqueue_generation(["order"])
        return super(LoadtestBatch, self - jobs).action_generate_orders() if self - jobs else True

    def action_generate(self):
        jobs = self._jobs_mode()
        for batch in jobs:
            batch._check_enabled()
            if not batch.user_ids:
                batch._generate_users()
            kinds = [kind for kind in ("partner", "product", "order") if not batch._has(kind)]
            batch._enqueue_generation(kinds)
        return super(LoadtestBatch, self - jobs).action_generate() if self - jobs else True

    # ------------------------------------------------------------------
    # cleanup: one self-rescheduling job deletes a chunk per run
    def _cleanup_chunk(self, kind):
        """Delete up to job_chunk_size records of this kind (generated ones
        first, then strays the test users created). Returns how many."""
        self.ensure_one()
        model = LINKED_MODELS[kind]
        size = max(self.job_chunk_size, 1)
        domains = [self._linked_domain(kind)]
        if self.user_ids:
            domains.append(
                [("create_uid", "in", self.user_ids.ids), ("loadtest_batch_id", "=", False)]
            )
        for domain in domains:
            records = self._linked(kind).search(domain, limit=size)
            if records:
                if model == "sale.order":
                    records.filtered(lambda o: o.state not in ("draft", "cancel"))._action_cancel()
                records.unlink()
                return len(records)
        return 0

    def _job_cleanup(self, kinds, users=False):
        """Delete one chunk of the first kind that still has records and
        reschedule; when everything is gone, archive the users if asked."""
        self.ensure_one()
        for kind in kinds:
            if self._cleanup_chunk(kind):
                follow_up = self._delayable(
                    _("Batch %(batch)s: clean up %(kinds)s") % {"batch": self.id, "kinds": kind}
                )._job_cleanup(kinds, users=users)
                follow_up.delay()
                self._tag_jobs([follow_up], self.job_run)
                return True
        if users:
            self.action_cleanup_users()
        _logger.info("loadtest batch %s background cleanup of %s finished", self.id, kinds)
        return True

    def _enqueue_cleanup(self, kinds, users=False):
        self.ensure_one()
        self._require_no_active_jobs()
        job = self._delayable(
            _("Batch %(batch)s: clean up %(kinds)s") % {"batch": self.id, "kinds": ", ".join(kinds)}
        )._job_cleanup(list(kinds), users=users)
        job.delay()
        self._tag_jobs([job], self._new_run())
        return True

    def action_cleanup_orders(self):
        jobs = self._jobs_mode()
        for batch in jobs:
            batch._enqueue_cleanup(["order"])
        return super(LoadtestBatch, self - jobs).action_cleanup_orders() if self - jobs else True

    def action_cleanup_products(self):
        jobs = self._jobs_mode()
        jobs._require_no_orders("products")
        for batch in jobs:
            batch._enqueue_cleanup(["product"])
        return super(LoadtestBatch, self - jobs).action_cleanup_products() if self - jobs else True

    def action_cleanup_partners(self):
        jobs = self._jobs_mode()
        jobs._require_no_orders("partners")
        for batch in jobs:
            batch._enqueue_cleanup(["partner"])
        return super(LoadtestBatch, self - jobs).action_cleanup_partners() if self - jobs else True

    def action_cleanup(self):
        jobs = self._jobs_mode()
        for batch in jobs:
            batch._enqueue_cleanup(CLEANUP_ORDER, users=True)
        return super(LoadtestBatch, self - jobs).action_cleanup() if self - jobs else True
