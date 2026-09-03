# odoo-loadtest-toolkit

Standalone Odoo 18 module (`loadtest_toolkit`): generate load-test data,
define scenarios, and **run Locust from inside Odoo** — start, stop,
restart, repeat — with live stats and per-endpoint results stored on
the run.

Odoo is the control plane, Locust is the engine. Locust is never
imported into the Odoo process (it monkey-patches with gevent); each
run spawns it as a detached child process in web mode and drives it
through its REST API. Optional Locust workers (distributed mode) are
spawned the same way.

## Concepts

| Model | Purpose |
|-------|---------|
| Data Batch | test users (`loadtest_NNN`) + partners/products/orders they work on; per-type Generate / Clean Up, dependency-aware |
| Journey | catalog of Locust user classes shipped in `locustfiles/journeys.py`: Browser, Sales Rep, Chatter, Catalog Editor, Presence (bus websocket), Error Lab (sentry_error_lab endpoints) |
| Scenario | batch + target URL + virtual users, spawn rate, duration, worker count + weighted journey mix |
| Run | one execution: Start / Stop / Restart / Repeat, live users/rps/failures while running, final p50/p95/p99 and per-endpoint table from Locust's CSV, process list, log excerpt, optional Sentry link for the exact time window |

A cron polls running runs every minute; the Refresh button does it on
demand. Runs end when their duration elapses (`--autoquit`), when
stopped, or when the process dies (→ `failed`, results salvaged if any).

## Install

- `pip install locust` into the Odoo venv (declared as external
  dependency; only executed, never imported by Odoo)
- install `loadtest_toolkit` (depends on `sale`)
- odoo.conf:

```
loadtest_enabled = true          ; required guard for data generation
loadtest_sentry_org = my-org     ; optional: "Open in Sentry" button on runs
```

Test users need Sales Manager rights for the Catalog Editor journey;
the batch grants them.

## Usage

Optional: load-test a clone instead of the real database -
`./scripts/clone_db.sh odoo_18_local odoo_18_loadtest` (terminates connections,
copies via TEMPLATE, disables mail servers on the clone), then point the
scenario's target at an instance serving the clone.


1. Load Testing → Data Batches → generate users (and data)
2. Scenarios → new scenario: pick the batch, users/spawn rate/duration,
   journey mix (weights), optionally workers
3. New Run → Start. Watch Live; Stop or wait. Summary + endpoint table
   land on the run. Repeat for a comparison run after tuning.
4. Data Batches → Clean Up All when finished (also removes what the
   users created during runs)

## Notes

- Run artifacts (Locust log + CSV) live under `<data_dir>/loadtest/run_<id>/`
- Locust's web UI is bound to 127.0.0.1 on a per-run port (shown on the run)
- Wrong batch password → Odoo's login cooldown blocks further logins
  for a few minutes, even with the corrected password. The counter is
  **per source IP** (`res.users._assert_can_auth`), and all Locust
  users share one IP — a single bad-password run poisons every
  subsequent login and floods the logs/Sentry with "Too many login
  failures". On load-test instances raise the threshold:
  `base.login_cooldown_after = 50` (system parameter; `0` disables)
- A threaded dev server measures that setup, not Odoo capacity; point
  `target_url` at a `workers > 0` instance for capacity numbers

## Tests

`--test-tags /loadtest_toolkit` — batch generate/cleanup and dependency
rules, run start (spawn command, env, workers), guard, live stats,
CSV ingestion, failure detection, repeat.
