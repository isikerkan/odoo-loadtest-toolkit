# odoo-loadtest-toolkit

Standalone Odoo 18 module (`loadtest_toolkit`): generate load-test
users and the data they work on, directly from the Odoo UI, with a
guarded one-click cleanup.

Companion to [odoo-loadtest](https://github.com/sverkanisik/odoo-loadtest)
(the external Locust driver): this module provisions exactly what the
Locust tier-2 scenario expects — internal users `loadtest_NNN` with a
shared password, plus partners/products/sale orders for them to read
and write.

## Features

- **Batch model** (`Load Testing` menu, admins only): configure how
  many test users, partners, products and sale orders to generate
- Users get sales rights and the login pattern `loadtest_NNN`
  (numbering continues across batches, so Locust configs stay valid)
- Sale orders are created *by* the test users (random assignment,
  1-3 order lines, a third confirmed) so ownership and activity
  distribution look like real usage
- **Cleanup**: deletes everything the batch generated **plus** any
  stray records the test users created during load runs (tracked via
  `create_uid`), then archives the users
- **Guardrail**: generation refuses unless the server config contains
  `loadtest_enabled = true` — a batch record accidentally created on
  production cannot generate anything

## Install

Clone into an addons path, install `loadtest_toolkit` (depends on
`sale`). Add to `odoo.conf`:

```
loadtest_enabled = true
```

## Usage

1. Load Testing → create a batch, set the volumes and password
2. *Generate Data* — summary lands on the batch record
3. Run your load scenario (e.g. odoo-loadtest tier 2) against the
   generated users
4. *Clean Up* — removes generated + stray data, archives the users

## Tests

`--test-tags /loadtest_toolkit` — covers the guard, the full
generate/cleanup round trip, and cross-batch login uniqueness.
