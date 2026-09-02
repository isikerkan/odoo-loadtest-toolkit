"""Locust user classes for loadtest_toolkit.

Spawned by the loadtest.run model as a separate process (never imported
by Odoo). Configuration arrives through environment variables:

- ODOO_DB            database to authenticate against
- LOADTEST_LOGINS    comma-separated logins of the batch's test users
- LOADTEST_PASSWORD  their shared password
- LOADTEST_WEIGHTS   JSON {"ClassName": weight} chosen in the scenario
"""

import itertools
import json
import os
import random

from locust import HttpUser, between, task

ODOO_DB = os.environ.get("ODOO_DB", "")
LOGINS = [x for x in os.environ.get("LOADTEST_LOGINS", "").split(",") if x]
PASSWORD = os.environ.get("LOADTEST_PASSWORD", "loadtest")
WEIGHTS = json.loads(os.environ.get("LOADTEST_WEIGHTS") or "{}")

_login_cycle = itertools.cycle(LOGINS or ["loadtest_001"])


class OdooWebUser(HttpUser):
    """Session-authenticated Odoo user: real cookie login, then the same
    /web/dataset/call_kw payloads the web client sends."""

    abstract = True
    wait_time = between(1, 4)

    def on_start(self):
        self.login = next(_login_cycle)
        response = self.client.post(
            "/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"db": ODOO_DB, "login": self.login, "password": PASSWORD},
            },
            name="session.authenticate",
        )
        payload = response.json()
        if not (payload.get("result") or {}).get("uid"):
            error = (payload.get("error") or {}).get("data", {}).get("message", "")
            raise RuntimeError(f"authentication failed for {self.login}: {error or payload}"[:300])

    def on_stop(self):
        self.client.post(
            "/web/session/destroy",
            json={"jsonrpc": "2.0", "method": "call", "params": {}},
            name="session.destroy",
        )

    def call_kw(self, model, method, args=None, kwargs=None, name=None):
        response = self.client.post(
            "/web/dataset/call_kw",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": model,
                    "method": method,
                    "args": args or [],
                    "kwargs": kwargs or {},
                },
            },
            name=name or f"{model}.{method}",
        )
        payload = response.json()
        if payload.get("error"):
            message = payload["error"].get("data", {}).get("message", "rpc error")
            raise RuntimeError(f"{model}.{method}: {message[:120]}")
        return payload.get("result")

    # shared building blocks -------------------------------------------
    def browse_partners(self):
        self.call_kw(
            "res.partner",
            "search_read",
            kwargs={
                "domain": [["is_company", "=", True]],
                "fields": ["name", "email", "phone", "country_id"],
                "limit": 40,
            },
        )

    def browse_products(self):
        self.call_kw(
            "product.template",
            "search_read",
            kwargs={
                "domain": [],
                "fields": ["name", "list_price", "default_code"],
                "limit": 40,
                "offset": random.choice([0, 40]),
            },
        )

    def browse_orders(self):
        self.call_kw(
            "sale.order",
            "search_read",
            kwargs={
                "domain": [],
                "fields": ["name", "partner_id", "amount_total", "state"],
                "limit": 40,
                "order": "id desc",
            },
        )

    def read_partner_form(self):
        ids = self.call_kw("res.partner", "search", args=[[]], kwargs={"limit": 80})
        if ids:
            self.call_kw(
                "res.partner",
                "read",
                args=[[random.choice(ids)]],
                kwargs={"fields": ["name", "email", "child_ids", "category_id"]},
            )


class Browser(OdooWebUser):
    """Read-only user: lists, forms, searches."""

    weight = WEIGHTS.get("Browser", 3)

    @task(5)
    def partners(self):
        self.browse_partners()

    @task(4)
    def products(self):
        self.browse_products()

    @task(3)
    def orders(self):
        self.browse_orders()

    @task(2)
    def partner_form(self):
        self.read_partner_form()

    @task(2)
    def product_search(self):
        self.call_kw(
            "product.product",
            "name_search",
            kwargs={"name": random.choice(["LT", "Locust", "Prod", "0"]), "limit": 8},
        )


class SalesRep(OdooWebUser):
    """Creates and confirms sale orders and discusses them."""

    weight = WEIGHTS.get("SalesRep", 2)

    @task(3)
    def orders(self):
        self.browse_orders()

    @task(2)
    def partners(self):
        self.browse_partners()

    @task(1)
    def create_and_confirm_order(self):
        partner_ids = self.call_kw(
            "res.partner", "search", args=[[["is_company", "=", True]]], kwargs={"limit": 20}
        )
        products = self.call_kw(
            "product.product",
            "search_read",
            kwargs={"domain": [["sale_ok", "=", True]], "fields": ["id"], "limit": 10},
        )
        if not partner_ids or not products:
            return
        order_id = self.call_kw(
            "sale.order",
            "create",
            args=[
                {
                    "partner_id": random.choice(partner_ids),
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "product_id": random.choice(products)["id"],
                                "product_uom_qty": random.randint(1, 5),
                            },
                        )
                    ],
                }
            ],
            name="sale.order.create+line",
        )
        self.call_kw("sale.order", "action_confirm", args=[[order_id]], name="sale.order.confirm")
        self.call_kw(
            "sale.order",
            "message_post",
            args=[[order_id]],
            kwargs={
                "body": "<p>Confirmed during load test, please prepare delivery.</p>",
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
            },
            name="sale.order.message_post",
        )


class Chatter(OdooWebUser):
    """Posts notes on accounts and reads chatter threads."""

    weight = WEIGHTS.get("Chatter", 1)

    @task(3)
    def post_note(self):
        ids = self.call_kw(
            "res.partner", "search", args=[[["is_company", "=", True]]], kwargs={"limit": 50}
        )
        if not ids:
            return
        self.call_kw(
            "res.partner",
            "message_post",
            args=[[random.choice(ids)]],
            kwargs={
                "body": (
                    f"<p>Load test note {random.randint(1, 10**6)}: "
                    "following up on this account.</p>"
                ),
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_note",
            },
            name="res.partner.message_post",
        )

    @task(2)
    def read_thread(self):
        ids = self.call_kw("sale.order", "search", args=[[]], kwargs={"limit": 30})
        if ids:
            self.call_kw(
                "mail.message",
                "search_read",
                kwargs={
                    "domain": [["model", "=", "sale.order"], ["res_id", "=", random.choice(ids)]],
                    "fields": ["author_id", "body", "date"],
                    "limit": 20,
                },
            )

    @task(1)
    def partner_form(self):
        self.read_partner_form()


class CatalogEditor(OdooWebUser):
    """Creates partners and products (needs Sales Manager rights)."""

    weight = WEIGHTS.get("CatalogEditor", 1)

    @task(2)
    def create_partner(self):
        n = random.randint(1, 10**6)
        partner_id = self.call_kw(
            "res.partner",
            "create",
            args=[
                {
                    "name": f"Locust Contact {n}",
                    "email": f"locust.contact.{n}@loadtest.invalid",
                    "phone": f"+49 000 {n:07d}",
                    "is_company": n % 5 == 0,
                }
            ],
        )
        self.call_kw(
            "res.partner",
            "read",
            args=[[partner_id]],
            kwargs={"fields": ["name", "email", "phone"]},
            name="res.partner.read(after create)",
        )

    @task(2)
    def create_product(self):
        n = random.randint(1, 10**6)
        self.call_kw(
            "product.template",
            "create",
            args=[
                {
                    "name": f"Locust Product {n}",
                    "sale_ok": True,
                    "type": "service",
                    "list_price": round(random.uniform(5, 500), 2),
                }
            ],
        )

    @task(3)
    def products(self):
        self.browse_products()
