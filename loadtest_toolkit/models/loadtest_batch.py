# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import random

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config, str2bool

_logger = logging.getLogger(__name__)

CHUNK = 500  # records per ORM create() inside one generation chunk
LINKED_MODELS = {
    "partner": "res.partner",
    "product": "product.template",
    "order": "sale.order",
}


class LoadtestBatch(models.Model):
    """A batch of generated load-test data: users plus the records they
    work on. Generation is guarded by the loadtest_enabled server
    option so it can never run on an unprepared database; cleanup
    removes everything the batch created.

    Generation is chunk-capable: ``_generate_<kind>_chunk(start, size)``
    creates the records with indexes ``start .. start + size - 1`` and is
    idempotent (indexes that already exist are skipped), so chunks can be
    retried or handed to background jobs. Generated records point back at
    the batch through ``loadtest_batch_id`` (see loadtest.linked.mixin)
    instead of a relation table, which keeps counting and cleanup cheap at
    millions of records."""

    _name = "loadtest.batch"
    _description = "Load Test Data Batch"
    _order = "id desc"

    name = fields.Char(default="Load Test Batch", required=True)
    state = fields.Selection(
        [("draft", "Empty"), ("partial", "Partially Generated"), ("generated", "Generated")],
        compute="_compute_state",
    )
    user_count = fields.Integer(default=10, help="Test users to create (login loadtest_NNN)")
    partner_count = fields.Integer(default=100)
    product_count = fields.Integer(default=50)
    order_count = fields.Integer(default=200, help="Sale orders, created by random test users")
    password = fields.Char(default="loadtest", help="Password for all test users of this batch")

    user_ids = fields.Many2many("res.users", "loadtest_batch_user_rel", string="Test Users")
    partner_ids = fields.One2many(
        "res.partner", "loadtest_batch_id", string="Generated Partners", readonly=True
    )
    product_ids = fields.One2many(
        "product.template", "loadtest_batch_id", string="Generated Products", readonly=True
    )
    order_ids = fields.One2many(
        "sale.order", "loadtest_batch_id", string="Generated Orders", readonly=True
    )

    # live counts of what the batch owns, for the smart buttons; computed
    # with search_count so a batch never loads millions of ids
    generated_user_count = fields.Integer(compute="_compute_generated_counts")
    generated_partner_count = fields.Integer(compute="_compute_generated_counts")
    generated_product_count = fields.Integer(compute="_compute_generated_counts")
    generated_order_count = fields.Integer(compute="_compute_generated_counts")

    def _linked(self, kind):
        """Empty recordset of the linked model, sudo, archived included."""
        return self.env[LINKED_MODELS[kind]].sudo().with_context(active_test=False)

    def _linked_domain(self, kind):
        self.ensure_one()
        return [("loadtest_batch_id", "=", self.id)]

    def _count(self, kind):
        self.ensure_one()
        return self._linked(kind).search_count(self._linked_domain(kind))

    def _has(self, kind):
        return bool(self._count(kind))

    @api.depends("user_ids", "partner_ids", "product_ids", "order_ids")
    def _compute_generated_counts(self):
        for batch in self:
            batch.generated_user_count = len(batch.user_ids)
            batch.generated_partner_count = batch._count("partner")
            batch.generated_product_count = batch._count("product")
            batch.generated_order_count = batch._count("order")

    @api.depends(
        "generated_user_count",
        "generated_partner_count",
        "generated_product_count",
        "generated_order_count",
    )
    def _compute_state(self):
        for batch in self:
            present = [
                bool(batch.generated_user_count),
                bool(batch.generated_partner_count),
                bool(batch.generated_product_count),
                bool(batch.generated_order_count),
            ]
            batch.state = "generated" if all(present) else ("partial" if any(present) else "draft")

    def _action_view(self, model, domain, name):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": "list,form",
            "domain": domain,
            "context": {"active_test": False},
        }

    def action_view_users(self):
        return self._action_view("res.users", [("id", "in", self.user_ids.ids)], "Test Users")

    def action_view_partners(self):
        return self._action_view(
            "res.partner", self._linked_domain("partner"), "Generated Partners"
        )

    def action_view_products(self):
        return self._action_view(
            "product.template", self._linked_domain("product"), "Generated Products"
        )

    def action_view_orders(self):
        return self._action_view("sale.order", self._linked_domain("order"), "Generated Orders")

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
        # numeric max, not "order login desc": lexicographically
        # loadtest_999 > loadtest_1000, which produced duplicate logins
        users = (
            self.env["res.users"]
            .sudo()
            .with_context(active_test=False)
            .search([("login", "=like", "loadtest\\_%")])
        )
        indexes = []
        for login in users.mapped("login"):
            try:
                indexes.append(int(login.rsplit("_", 1)[1]))
            except ValueError:
                continue
        return max(indexes, default=0) + 1

    def _generate_users(self):
        self.ensure_one()
        groups = [(4, self.env.ref("base.group_user").id)]
        # sales manager: needed to create products and confirm any order,
        # i.e. the full journey a load scenario drives
        for xmlid in ("sales_team.group_sale_salesman", "sales_team.group_sale_manager"):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups.append((4, group.id))
        start = self._next_user_index()
        values = [
            {
                "name": f"Load Test {start + i:03d}",
                "login": f"loadtest_{start + i:03d}",
                "password": self.password,
                "email": f"loadtest_{start + i:03d}@loadtest.invalid",
                "groups_id": groups,
            }
            for i in range(self.user_count)
        ]
        users = self.env["res.users"].create(values)
        self.user_ids = [(6, 0, users.ids)]
        return users

    # ------------------------------------------------------------------
    # chunk-capable generation: deterministic keys per index, idempotent
    def _key(self, prefix, index):
        self.ensure_one()
        return f"LT{self.id}-{prefix}{index:08d}"

    def _missing_indexes(self, kind, key_field, prefix, start, size):
        """Indexes in [start, start + size) that have no record yet."""
        keys = {self._key(prefix, i): i for i in range(start, start + size)}
        existing = self._linked(kind).search_read(
            [*self._linked_domain(kind), (key_field, "in", list(keys))], [key_field]
        )
        for record in existing:
            keys.pop(record[key_field], None)
        return sorted(keys.values())

    def _create_chunked(self, model, values):
        records = self.env[model]
        for offset in range(0, len(values), CHUNK):
            records |= self.env[model].create(values[offset : offset + CHUNK])
        return records

    def _generate_partners_chunk(self, start, size):
        """Generate the partners with indexes start .. start + size - 1."""
        self.ensure_one()
        values = [
            {
                "name": f"LT{self.id} {'Company' if i % 4 == 0 else 'Contact'} {i:08d}",
                "is_company": i % 4 == 0,
                "ref": self._key("P", i),
                "email": f"lt{self.id}.partner{i:08d}@loadtest.invalid",
                "phone": f"+41 00 {i % 10_000_000:07d}",
                "loadtest_batch_id": self.id,
            }
            for i in self._missing_indexes("partner", "ref", "P", start, size)
        ]
        return self._create_chunked("res.partner", values)

    def _generate_products_chunk(self, start, size):
        """Generate the products with indexes start .. start + size - 1."""
        self.ensure_one()
        values = [
            {
                "name": f"LT{self.id} Product {i:08d}",
                "sale_ok": True,
                "type": "service",
                # deterministic per index so retries reproduce the same data
                "list_price": round(random.Random(i).uniform(5, 500), 2),
                "default_code": self._key("", i),
                "loadtest_batch_id": self.id,
            }
            for i in self._missing_indexes("product", "default_code", "", start, size)
        ]
        return self._create_chunked("product.template", values)

    def _order_pools(self, size=1000):
        """Sample of users, partners and product variants for orders: a
        bounded pool, never the full (possibly huge) generated sets."""
        self.ensure_one()
        partners = self._linked("partner").search(
            [*self._linked_domain("partner"), ("is_company", "=", True)], limit=size
        ) or self._linked("partner").search(self._linked_domain("partner"), limit=size)
        variants = (
            self.env["product.product"]
            .sudo()
            .search([("product_tmpl_id.loadtest_batch_id", "=", self.id)], limit=size)
        )
        return self.user_ids, partners, variants

    def _generate_orders_chunk(self, start, size):
        """Generate the sale orders with indexes start .. start + size - 1,
        each created by a test user so the data profile matches what
        those users later read and write in load runs."""
        self.ensure_one()
        users, partners, variants = self._order_pools()
        if not (users and partners and variants):
            return self.env["sale.order"]
        orders = self.env["sale.order"]
        for i in self._missing_indexes("order", "client_order_ref", "O", start, size):
            rng = random.Random(i)
            user = users[i % len(users)]
            lines = [
                (
                    0,
                    0,
                    {"product_id": rng.choice(variants.ids), "product_uom_qty": rng.randint(1, 5)},
                )
                for _ in range(rng.randint(1, 3))
            ]
            order = (
                self.env["sale.order"]
                .with_user(user)
                .create(
                    {
                        "partner_id": rng.choice(partners.ids),
                        "client_order_ref": self._key("O", i),
                        "order_line": lines,
                        "loadtest_batch_id": self.id,
                    }
                )
            )
            if i % 3 == 0:
                order.with_user(user).action_confirm()
            orders |= order.sudo()
        return orders

    def _chunks(self, total, size=CHUNK):
        return [(start, min(size, total - start)) for start in range(0, total, size)]

    def _generate_partners(self):
        self.ensure_one()
        records = self.env["res.partner"]
        for start, size in self._chunks(self.partner_count):
            records |= self._generate_partners_chunk(start, size)
        return records

    def _generate_products(self):
        self.ensure_one()
        records = self.env["product.template"]
        for start, size in self._chunks(self.product_count):
            records |= self._generate_products_chunk(start, size)
        return records

    def _generate_orders(self):
        self.ensure_one()
        records = self.env["sale.order"]
        for start, size in self._chunks(self.order_count, 100):
            records |= self._generate_orders_chunk(start, size)
        return records

    # ------------------------------------------------------------------
    # per-type generation
    def action_generate_users(self):
        self._check_enabled()
        for batch in self:
            if batch.user_ids:
                raise UserError("Users already generated for this batch.")
            batch._generate_users()
        return True

    def action_generate_partners(self):
        self._check_enabled()
        for batch in self:
            if batch._has("partner"):
                raise UserError("Partners already generated for this batch.")
            batch._generate_partners()
        return True

    def action_generate_products(self):
        self._check_enabled()
        for batch in self:
            if batch._has("product"):
                raise UserError("Products already generated for this batch.")
            batch._generate_products()
        return True

    def action_generate_orders(self):
        self._check_enabled()
        for batch in self:
            if batch._has("order"):
                raise UserError("Orders already generated for this batch.")
            if not (batch.user_ids and batch._has("partner") and batch._has("product")):
                raise UserError("Generate users, partners and products before orders.")
            batch._generate_orders()
        return True

    def action_generate(self):
        """Generate everything that is still missing, in dependency order."""
        self._check_enabled()
        for batch in self:
            if not batch.user_ids:
                batch._generate_users()
            if not batch._has("partner"):
                batch._generate_partners()
            if not batch._has("product"):
                batch._generate_products()
            if not batch._has("order"):
                batch._generate_orders()
            _logger.info("loadtest batch %s generated: %s", batch.id, batch._summary())
        return True

    def _summary(self):
        self.ensure_one()
        return (
            f"{len(self.user_ids)} users, {self._count('partner')} partners, "
            f"{self._count('product')} products, {self._count('order')} orders"
        )

    # ------------------------------------------------------------------
    # per-type cleanup (orders first: they reference partners/products),
    # in chunks so a batch of millions never builds one giant recordset
    def _unlink_chunked(self, model, domain, size=CHUNK):
        """Delete everything matching domain, size records at a time.
        Sale orders are cancelled first, Odoo refuses to delete confirmed
        ones. Returns the number of records deleted."""
        records_model = self.env[model].sudo().with_context(active_test=False)
        deleted = 0
        while True:
            records = records_model.search(domain, limit=size)
            if not records:
                return deleted
            if model == "sale.order":
                records.filtered(lambda o: o.state not in ("draft", "cancel"))._action_cancel()
            records.unlink()
            deleted += len(records)

    def _cleanup_kind(self, kind):
        """Delete what the batch generated of this kind plus the strays its
        test users created during load runs."""
        self.ensure_one()
        model = LINKED_MODELS[kind]
        deleted = self._unlink_chunked(model, self._linked_domain(kind))
        if self.user_ids:
            deleted += self._unlink_chunked(
                model,
                [("create_uid", "in", self.user_ids.ids), ("loadtest_batch_id", "=", False)],
            )
        return deleted

    def action_cleanup_orders(self):
        for batch in self:
            batch._cleanup_kind("order")
        return True

    def _require_no_orders(self, what):
        for batch in self:
            if batch._has("order"):
                raise UserError(f"Clean up the orders before the {what}.")

    def action_cleanup_products(self):
        self._require_no_orders("products")
        for batch in self:
            batch._cleanup_kind("product")
        return True

    def action_cleanup_partners(self):
        self._require_no_orders("partners")
        for batch in self:
            batch._cleanup_kind("partner")
        return True

    def action_cleanup_users(self):
        self._require_no_orders("users")
        for batch in self:
            stray_messages = (
                self.env["mail.message"].sudo().search([("create_uid", "in", batch.user_ids.ids)])
            )
            stray_messages.unlink()
            batch.user_ids.sudo().write({"active": False})
            batch.user_ids = [(5, 0, 0)]
        return True

    def action_cleanup(self):
        """Remove everything the batch owns, in dependency order."""
        for batch in self:
            batch.action_cleanup_orders()
            batch.action_cleanup_products()
            batch.action_cleanup_partners()
            batch.action_cleanup_users()
            _logger.info("loadtest batch %s cleaned", batch.id)
        return True
