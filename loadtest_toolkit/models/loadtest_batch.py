# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import random

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config, str2bool

_logger = logging.getLogger(__name__)

CHUNK = 500


class LoadtestBatch(models.Model):
    """A batch of generated load-test data: users plus the records they
    work on. Generation is guarded by the loadtest_enabled server
    option so it can never run on an unprepared database; cleanup
    removes everything the batch created."""

    _name = "loadtest.batch"
    _description = "Load Test Data Batch"
    _order = "id desc"

    name = fields.Char(default="Load Test Batch", required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("generated", "Generated"), ("cleaned", "Cleaned")],
        default="draft",
        required=True,
    )
    user_count = fields.Integer(default=10, help="Test users to create (login loadtest_NNN)")
    partner_count = fields.Integer(default=100)
    product_count = fields.Integer(default=50)
    order_count = fields.Integer(default=200, help="Sale orders, created by random test users")
    password = fields.Char(default="loadtest", help="Password for all test users of this batch")

    user_ids = fields.Many2many("res.users", "loadtest_batch_user_rel", string="Test Users")
    partner_ids = fields.Many2many("res.partner", "loadtest_batch_partner_rel", string="Generated Partners")
    product_ids = fields.Many2many("product.product", "loadtest_batch_product_rel", string="Generated Products")
    order_ids = fields.Many2many("sale.order", "loadtest_batch_order_rel", string="Generated Orders")

    generated_summary = fields.Char(readonly=True)

    # live counts of what the batch owns, for the smart buttons
    generated_user_count = fields.Integer(compute="_compute_generated_counts")
    generated_partner_count = fields.Integer(compute="_compute_generated_counts")
    generated_product_count = fields.Integer(compute="_compute_generated_counts")
    generated_order_count = fields.Integer(compute="_compute_generated_counts")

    @api.depends("user_ids", "partner_ids", "product_ids", "order_ids")
    def _compute_generated_counts(self):
        for batch in self:
            batch.generated_user_count = len(batch.user_ids)
            batch.generated_partner_count = len(batch.partner_ids)
            batch.generated_product_count = len(batch.product_ids)
            batch.generated_order_count = len(batch.order_ids)

    def _action_view(self, model, records, name):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": "list,form",
            "domain": [("id", "in", records.ids)],
            "context": {"active_test": False},
        }

    def action_view_users(self):
        return self._action_view("res.users", self.user_ids, "Test Users")

    def action_view_partners(self):
        return self._action_view("res.partner", self.partner_ids, "Generated Partners")

    def action_view_products(self):
        return self._action_view("product.product", self.product_ids, "Generated Products")

    def action_view_orders(self):
        return self._action_view("sale.order", self.order_ids, "Generated Orders")

    # ------------------------------------------------------------------
    @api.model
    def _check_enabled(self):
        value = config.get("loadtest_enabled", False)
        enabled = str2bool(value, False) if isinstance(value, str) else bool(value)
        if not enabled:
            raise UserError(
                "Load test generation is disabled. Set loadtest_enabled = "
                "true in the Odoo server configuration to allow it on this "
                "instance."
            )

    def _next_user_index(self):
        last = self.env["res.users"].sudo().with_context(active_test=False).search(
            [("login", "=like", "loadtest\\_%")], order="login desc", limit=1
        )
        if not last:
            return 1
        try:
            return int(last.login.rsplit("_", 1)[1]) + 1
        except ValueError:
            return 1

    def _generate_users(self):
        self.ensure_one()
        salesman = self.env.ref("sales_team.group_sale_salesman", raise_if_not_found=False)
        groups = [(4, self.env.ref("base.group_user").id)]
        if salesman:
            groups.append((4, salesman.id))
        start = self._next_user_index()
        values = [
            {
                "name": "Load Test %03d" % (start + i),
                "login": "loadtest_%03d" % (start + i),
                "password": self.password,
                "email": "loadtest_%03d@loadtest.invalid" % (start + i),
                "groups_id": groups,
            }
            for i in range(self.user_count)
        ]
        users = self.env["res.users"].create(values)
        self.user_ids = [(6, 0, users.ids)]
        return users

    def _generate_partners(self):
        self.ensure_one()
        values = [
            {
                "name": f"LT{self.id} {'Company' if i % 4 == 0 else 'Contact'} {i:05d}",
                "is_company": i % 4 == 0,
                "email": f"lt{self.id}.partner{i:05d}@loadtest.invalid",
                "phone": "+49 000 %07d" % i,
            }
            for i in range(self.partner_count)
        ]
        records = self.env["res.partner"]
        for offset in range(0, len(values), CHUNK):
            records |= self.env["res.partner"].create(values[offset : offset + CHUNK])
        self.partner_ids = [(6, 0, records.ids)]
        return records

    def _generate_products(self):
        self.ensure_one()
        values = [
            {
                "name": f"LT{self.id} Product {i:05d}",
                "sale_ok": True,
                "type": "service",
                "list_price": round(random.uniform(5, 500), 2),
                "default_code": f"LT{self.id}-{i:05d}",
            }
            for i in range(self.product_count)
        ]
        records = self.env["product.product"]
        for offset in range(0, len(values), CHUNK):
            records |= self.env["product.product"].create(values[offset : offset + CHUNK])
        self.product_ids = [(6, 0, records.ids)]
        return records

    def _generate_orders(self, users, partners, products):
        self.ensure_one()
        if not (users and partners and products):
            return self.env["sale.order"]
        orders = self.env["sale.order"]
        companies = partners.filtered("is_company") or partners
        for i in range(self.order_count):
            # created by a random test user so the data profile matches
            # what those users later read and write in load runs
            user = users[i % len(users)]
            lines = [
                (
                    0,
                    0,
                    {
                        "product_id": random.choice(products.ids),
                        "product_uom_qty": random.randint(1, 5),
                    },
                )
                for _ in range(random.randint(1, 3))
            ]
            order = (
                self.env["sale.order"]
                .with_user(user)
                .create(
                    {
                        "partner_id": random.choice(companies.ids),
                        "order_line": lines,
                    }
                )
            )
            if i % 3 == 0:
                order.with_user(user).action_confirm()
            orders |= order.sudo()
        self.order_ids = [(6, 0, orders.ids)]
        return orders

    # ------------------------------------------------------------------
    def action_generate(self):
        self._check_enabled()
        for batch in self:
            if batch.state != "draft":
                raise UserError("Batch already generated.")
            users = batch._generate_users()
            partners = batch._generate_partners()
            products = batch._generate_products()
            orders = batch._generate_orders(users, partners, products)
            batch.generated_summary = (
                f"{len(users)} users, {len(partners)} partners, "
                f"{len(products)} products, {len(orders)} orders"
            )
            batch.state = "generated"
            _logger.info("loadtest batch %s generated: %s", batch.id, batch.generated_summary)
        return True

    def action_cleanup(self):
        for batch in self:
            if batch.state != "generated":
                raise UserError("Nothing to clean for this batch.")
            orders = batch.order_ids.sudo().exists()
            if orders:
                orders.filtered(lambda o: o.state not in ("draft", "cancel"))._action_cancel()
                orders.unlink()
            # anything else the test users created during load runs
            stray = (
                self.env["sale.order"]
                .sudo()
                .search([("create_uid", "in", batch.user_ids.ids)])
            )
            if stray:
                stray.filtered(lambda o: o.state not in ("draft", "cancel"))._action_cancel()
                stray.unlink()
            batch.product_ids.sudo().exists().unlink()
            batch.partner_ids.sudo().exists().unlink()
            batch.user_ids.sudo().write({"active": False})
            batch.state = "cleaned"
            _logger.info("loadtest batch %s cleaned", batch.id)
        return True
