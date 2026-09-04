# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class QueueJob(models.Model):
    """Tag jobs with the batch and the enqueue run they belong to, so a
    batch can report progress over exactly the jobs it created last."""

    _inherit = "queue.job"

    loadtest_batch_id = fields.Many2one(
        "loadtest.batch", string="Load Test Batch", index=True, ondelete="set null"
    )
    loadtest_batch_run = fields.Integer(string="Load Test Batch Run", index=True)
