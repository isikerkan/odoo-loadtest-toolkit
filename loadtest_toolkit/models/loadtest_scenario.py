# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class LoadtestScenario(models.Model):
    """What to play: which test users, how many, which journey mix, how long."""

    _name = "loadtest.scenario"
    _description = "Load Test Scenario"

    name = fields.Char(required=True)
    description = fields.Text()
    batch_id = fields.Many2one("loadtest.batch", required=True, help="Test users and data to play against")
    target_url = fields.Char(
        default=lambda self: self.env["ir.config_parameter"].sudo().get_param("web.base.url"),
        required=True,
        help="Odoo base URL the virtual users hit; point it at another instance to load-test that one",
    )
    user_count = fields.Integer(default=10, required=True, help="Concurrent virtual users")
    spawn_rate = fields.Float(default=2.0, required=True, help="Users started per second")
    duration = fields.Integer(default=300, help="Seconds; 0 = run until stopped")
    worker_count = fields.Integer(default=0, help="Locust worker processes; 0 = single process")
    journey_line_ids = fields.One2many("loadtest.scenario.journey", "scenario_id", string="Journeys")
    run_ids = fields.One2many("loadtest.run", "scenario_id", string="Runs")
    run_count = fields.Integer(compute="_compute_run_count")

    @api.depends("run_ids")
    def _compute_run_count(self):
        for scenario in self:
            scenario.run_count = len(scenario.run_ids)

    @api.constrains("user_count", "spawn_rate", "worker_count")
    def _check_numbers(self):
        for scenario in self:
            if scenario.user_count < 1 or scenario.spawn_rate <= 0 or scenario.worker_count < 0:
                raise UserError("Users must be >= 1, spawn rate > 0 and workers >= 0.")

    def _weights(self):
        self.ensure_one()
        lines = self.journey_line_ids.filtered(lambda l: l.weight > 0)
        if not lines:
            raise UserError("Add at least one journey with a weight > 0.")
        return {line.journey_id.code: line.weight for line in lines}

    def action_new_run(self):
        self.ensure_one()
        run = self.env["loadtest.run"].create({"scenario_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "res_model": "loadtest.run",
            "res_id": run.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_runs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Runs",
            "res_model": "loadtest.run",
            "view_mode": "list,form",
            "domain": [("scenario_id", "=", self.id)],
            "context": {"default_scenario_id": self.id},
        }


class LoadtestScenarioJourney(models.Model):
    _name = "loadtest.scenario.journey"
    _description = "Load Test Scenario Journey Weight"
    _order = "sequence, id"

    scenario_id = fields.Many2one("loadtest.scenario", required=True, ondelete="cascade")
    journey_id = fields.Many2one("loadtest.journey", required=True)
    weight = fields.Integer(default=1, help="Relative share of virtual users running this journey")
    sequence = fields.Integer(default=10)
