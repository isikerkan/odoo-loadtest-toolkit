# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class LoadtestJourney(models.Model):
    """Catalog entry for a Locust user class shipped in locustfiles/journeys.py."""

    _name = "loadtest.journey"
    _description = "Load Test Journey"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Locust user class name in journeys.py")
    description = fields.Text()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [("code_unique", "unique(code)", "Journey code must be unique.")]
