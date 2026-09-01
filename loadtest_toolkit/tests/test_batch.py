# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase
from odoo.tools import config


class TestLoadtestBatch(TransactionCase):
    def _batch(self, **overrides):
        values = {
            "user_count": 2,
            "partner_count": 6,
            "product_count": 3,
            "order_count": 4,
        }
        values.update(overrides)
        return self.env["loadtest.batch"].create(values)

    def test_guard_blocks_generation(self):
        batch = self._batch()
        with patch.dict(config.options, {"loadtest_enabled": "false"}):
            with self.assertRaises(UserError):
                batch.action_generate()

    def test_generate_and_cleanup(self):
        batch = self._batch()
        with patch.dict(config.options, {"loadtest_enabled": "true"}):
            batch.action_generate()
        self.assertEqual(batch.state, "generated")
        self.assertEqual(len(batch.user_ids), 2)
        self.assertEqual(len(batch.partner_ids), 6)
        self.assertEqual(len(batch.product_ids), 3)
        self.assertEqual(len(batch.order_ids), 4)
        self.assertTrue(
            all(u.login.startswith("loadtest_") for u in batch.user_ids)
        )
        # orders created by the test users themselves
        self.assertTrue(
            all(o.create_uid in batch.user_ids for o in batch.order_ids)
        )

        partner_ids = batch.partner_ids.ids
        order_ids = batch.order_ids.ids
        batch.action_cleanup()
        self.assertEqual(batch.state, "cleaned")
        self.assertFalse(self.env["sale.order"].browse(order_ids).exists())
        self.assertFalse(self.env["res.partner"].browse(partner_ids).exists())
        self.assertTrue(all(not u.active for u in batch.user_ids))

    def test_user_index_continues(self):
        with patch.dict(config.options, {"loadtest_enabled": "true"}):
            first = self._batch(partner_count=0, product_count=0, order_count=0)
            first.action_generate()
            second = self._batch(partner_count=0, product_count=0, order_count=0)
            second.action_generate()
        logins = (first.user_ids | second.user_ids).mapped("login")
        self.assertEqual(len(logins), len(set(logins)))
