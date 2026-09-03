# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import config


# post_install: the batch creates sale orders, and modules that extend
# sale.order with NOT NULL columns (sale_stock) may load after this one
@tagged("post_install", "-at_install")
class TestLoadtestBatch(TransactionCase):
    def _batch(self, **overrides):
        values = {"user_count": 2, "partner_count": 6, "product_count": 3, "order_count": 4}
        values.update(overrides)
        return self.env["loadtest.batch"].create(values)

    def _enabled(self):
        return patch.dict(config.options, {"loadtest_enabled": "true"})

    def test_guard_blocks_generation(self):
        batch = self._batch()
        with patch.dict(config.options, {"loadtest_enabled": "false"}):
            with self.assertRaises(UserError):
                batch.action_generate()
            with self.assertRaises(UserError):
                batch.action_generate_users()

    def test_generate_all_and_cleanup_all(self):
        batch = self._batch()
        with self._enabled():
            batch.action_generate()
        self.assertEqual(batch.state, "generated")
        self.assertEqual(
            (
                len(batch.user_ids),
                len(batch.partner_ids),
                len(batch.product_ids),
                len(batch.order_ids),
            ),
            (2, 6, 3, 4),
        )
        self.assertTrue(all(o.create_uid in batch.user_ids for o in batch.order_ids))
        self.assertTrue(all(p.loadtest_batch_id == batch for p in batch.product_ids))
        self.assertEqual(batch.generated_product_count, 3)
        partner_ids, order_ids, users = batch.partner_ids.ids, batch.order_ids.ids, batch.user_ids
        batch.action_cleanup()
        self.assertEqual(batch.state, "draft")
        self.assertFalse(self.env["sale.order"].browse(order_ids).exists())
        self.assertFalse(self.env["res.partner"].browse(partner_ids).exists())
        self.assertTrue(all(not u.active for u in users))

    def test_per_type_generation_and_order(self):
        batch = self._batch()
        with self._enabled():
            batch.action_generate_users()
            self.assertEqual(batch.state, "partial")
            # orders need users + partners + products first
            with self.assertRaises(UserError):
                batch.action_generate_orders()
            batch.action_generate_partners()
            batch.action_generate_products()
            batch.action_generate_orders()
            self.assertEqual(batch.state, "generated")
            # no double generation
            with self.assertRaises(UserError):
                batch.action_generate_products()

    def test_cleanup_dependency_order(self):
        batch = self._batch()
        with self._enabled():
            batch.action_generate()
        with self.assertRaises(UserError):
            batch.action_cleanup_partners()  # orders still reference them
        batch.action_cleanup_orders()
        self.assertFalse(batch.order_ids)
        batch.action_cleanup_partners()
        self.assertFalse(batch.partner_ids)
        self.assertEqual(batch.state, "partial")

    def test_user_index_numeric_not_lexicographic(self):
        # "loadtest_999" sorts after "loadtest_1000" as a string; the next
        # index must still be numeric. Pick the digit-length boundary above
        # whatever already exists so the test also passes on a database
        # that has load-test users.
        current = self.env["loadtest.batch"]._next_user_index()
        boundary = 10 ** len(str(current)) - 1  # 999, 9999, ...
        self.env["res.users"].create(
            [
                {"name": "LT low", "login": f"loadtest_{boundary}", "active": False},
                {"name": "LT high", "login": f"loadtest_{boundary + 1}", "active": False},
            ]
        )
        batch = self._batch(partner_count=0, product_count=0, order_count=0, user_count=1)
        with self._enabled():
            batch.action_generate_users()
        self.assertEqual(batch.user_ids.login, f"loadtest_{boundary + 2}")

    def test_user_index_continues(self):
        with self._enabled():
            first = self._batch(partner_count=0, product_count=0, order_count=0)
            first.action_generate_users()
            second = self._batch(partner_count=0, product_count=0, order_count=0)
            second.action_generate_users()
        logins = (first.user_ids | second.user_ids).mapped("login")
        self.assertEqual(len(logins), len(set(logins)))

    def test_chunks_are_idempotent(self):
        batch = self._batch(product_count=7)
        with self._enabled():
            first = batch._generate_products_chunk(0, 4)
            again = batch._generate_products_chunk(0, 4)  # retry: nothing new
            rest = batch._generate_products_chunk(4, 3)
        self.assertEqual((len(first), len(again), len(rest)), (4, 0, 3))
        self.assertEqual(batch.generated_product_count, 7)
        self.assertEqual(sorted(batch.product_ids.mapped("default_code"))[0], batch._key("", 0))
        self.assertEqual(batch._chunks(7, 3), [(0, 3), (3, 3), (6, 1)])

    def test_cleanup_removes_strays_in_chunks(self):
        batch = self._batch(order_count=0)
        with self._enabled():
            batch.action_generate()
        user = batch.user_ids[0]
        stray = self.env["res.partner"].with_user(user).create({"name": "made during a run"})
        with patch("odoo.addons.loadtest_toolkit.models.loadtest_batch.CHUNK", 2):
            batch.action_cleanup_partners()
        self.assertFalse(stray.exists())
        self.assertEqual(batch.generated_partner_count, 0)
