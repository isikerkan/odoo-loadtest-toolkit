This module turns an Odoo 18 instance into a control plane for
[Locust](https://locust.io) load tests. From the *Load Testing* app you
generate disposable test data, describe what the virtual users should do,
start a run and read the results, without leaving Odoo.

## Two-tier architecture

Locust is **never imported into the Odoo process**: it monkey-patches the
interpreter with gevent, which would corrupt the Odoo worker. Instead
each run:

1. picks a free TCP port on `127.0.0.1`,
2. spawns `python -m locust` as a **detached child process** (its own
   session, stdout/stderr redirected to a log file under the Odoo data
   directory), in web mode with `--autostart` and `--autoquit`,
3. drives that process through **Locust's REST API**
   (`GET /stats/requests` for live figures, `GET /stop` to end the run),
4. reads Locust's **CSV export** as the authoritative final result and
   stores it on the run record.

Distributed mode works the same way: the run spawns one master and *n*
worker processes and the master waits for `--expect-workers`.

## Concepts

| Model | Purpose |
|---|---|
| **Data Batch** (`loadtest.batch`) | Disposable test users (`loadtest_NNN`) plus the partners, products and sale orders they work on. Per-type *Generate* and *Clean Up* actions, dependency aware (orders need users, partners and products; nothing under an order can be cleaned while orders exist). Cleanup also removes what the test users created during runs and archives the users. |
| **Journey** (`loadtest.journey`) | Catalog entry for one Locust user class shipped in `locustfiles/journeys.py` (Browser, Sales Rep, Chatter, Catalog Editor, Presence, Error Lab). The `code` is the class name passed to Locust. |
| **Scenario** (`loadtest.scenario`) | A data batch, a target URL, the load profile (virtual users, spawn rate, duration as value + unit or infinite, worker processes) and a weighted mix of journeys. |
| **Run** (`loadtest.run`) | One execution of a scenario: Start / Stop / Restart / Repeat, live users, requests per second and failures while running, final p50/p95/p99 and per-endpoint table from Locust's CSV, the spawned process list, the tail of the master log, and an optional Sentry link for the exact time window. |

## System sampling

Every poll (a cron every minute, or the *Refresh* button) also stores a
`loadtest.run.sample`: CPU %, RAM % and RAM used, the Odoo process RSS,
CPU core count (via `psutil`, when installed) and the number of active
and total PostgreSQL connections of the current database
(`pg_stat_activity`). The run shows the latest sample live and an
average/maximum summary once finished. The sample describes the host the
Odoo control plane runs on; when the scenario targets a remote instance
it does **not** measure that instance.

## Sentry link

When the server option `loadtest_sentry_org` is set, each run gets an
*Open in Sentry* button that opens the Sentry Traces explorer for the
organisation, filtered on the run's start and end time. The optional
*Error Lab* journey pairs with the separate `sentry_error_lab` module to
produce a known error volume during a run.
