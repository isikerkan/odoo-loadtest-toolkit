All menus are under the *Load Testing* app (administrators only).

## 1. Generate a data batch

*Load Testing > Data Batches > New*.

- Set the volumes: *Test users* (default 10), *Partners* (100), *Products*
  (50), *Orders* (200) and the shared *Password* (default `loadtest`;
  editable until users exist).
- *Generate All* creates everything still missing in dependency order:
  users (`loadtest_NNN`, `Load Test NNN`, e-mail `@loadtest.invalid`, with
  Internal User + Salesman + Sales Manager rights), partners (every fourth
  one a company), service products (`LT<batch> Product NNNNN`) and sale
  orders created *as* the test users, one in three confirmed.
- The per-type *Generate Users / Partners / Products / Orders* buttons do
  one step at a time; orders require the other three first.
- Smart buttons open the generated records; the state badge shows *Empty*,
  *Partially Generated* or *Generated*.

User indexes continue across batches (`loadtest_011`, ...) and are
computed numerically, so logins never collide.

## 2. Pick journeys

*Configuration > Journeys* lists the Locust user classes from
`locustfiles/journeys.py`:

| Journey | Code | What the virtual user does |
|---|---|---|
| Browser | `Browser` | Read-only: partner/product/order `search_read` lists, a random partner form, product `name_search`. |
| Sales Rep | `SalesRep` | Browses orders and partners; creates a sale order with one line, confirms it and posts a chatter message. |
| Chatter | `Chatter` | Posts internal notes on company partners, reads `mail.message` threads of orders, opens partner forms. |
| Catalog Editor | `CatalogEditor` | Creates partners and product templates (needs Sales Manager rights, which the batch grants), browses products. |
| Presence | `Presence` | Behaves like an idle open browser tab: opens the bus websocket (`/websocket`), subscribes, sends `update_presence` heartbeats every 20-40 s, drains notifications, occasionally reads the inbox. Requires `websocket-client`. Each connection pins one server thread in threaded mode. |
| Error Lab | `ErrorLab` | Calls the `sentry_error_lab` endpoints (`/boom`, `/sql`, `/slow`, `/http_boom`) so Sentry receives a known error volume. Deliberate errors count as success; HTTP 404 (module missing), *Forbidden* (lab not enabled) or an unexpected result count as failures. Requires the separate `sentry_error_lab` module on the target. |

All journeys log in with a real session (`/web/session/authenticate`)
and use `/web/dataset/call_kw`, the same payloads the web client sends.
An authentication failure aborts that virtual user with an error.

## 3. Create a scenario

*Load Testing > Scenarios > New*.

- *Batch*: the data batch whose users will log in.
- *Target URL*: defaults to `web.base.url`; point it at another instance
  serving the same database to load-test that one.
- *Load Profile*: concurrent virtual users (>= 1), spawn rate per second
  (> 0), *Duration* as a value plus unit (*Seconds*, *Minutes*, *Hours*,
  *Days*) or *Infinite*, and *Locust worker processes* (0 = single
  process).
- *Journey Mix*: one line per journey with an integer *Weight*; lines with
  weight 0 are ignored, at least one line must be > 0.

Finite durations are passed to Locust as `-t <seconds>s`; infinite runs
end via *Stop* or the run's *Stop At* time.

## 4. Start a run

*New Run* on the scenario (or *Runs > New*), then *Start*. The module
checks `loadtest_enabled`, that the batch has users and that no other
run of the same scenario is running, then spawns Locust.

While *Running* the form shows:

- *Live*: Locust state, current users, requests/s, requests, failures and
  failure ratio.
- *System (live)*: CPU %, cores, RAM %, RAM used (GB), Odoo RSS (MB),
  active and total PostgreSQL connections of this database.
- *Results per Endpoint*: the live per-request table (median, average,
  p95, p99, req/s), replaced by the CSV figures when the run ends.
- *Samples*: one row per poll combining Locust and system figures.
- *Processes*: master and worker PIDs with an *Alive* flag.
- *Port*: the local port of the Locust web UI (`http://127.0.0.1:<port>`)
  if you want to look at Locust's own charts.

A cron (*Load Testing: poll running runs*) refreshes every minute;
*Refresh* does it on demand. *Stop At* can be set or changed on a running
run; the poll stops the run once the time has passed (up to a minute of
slack).

## 5. Stop, restart, repeat

- *Stop*: asks Locust to stop, waits two seconds for the CSV flush,
  terminates the process group, ingests the CSV and stores the last 40
  lines of `master.log`. The run ends *Done* when the CSV had per-endpoint
  rows, otherwise *Failed*.
- *Restart*: stop then start again on the same record; results, samples
  and processes are reset.
- *Repeat*: creates a fresh run of the same scenario (notes copied) and
  starts it; use it for before/after comparisons.
- A run also ends by itself when the duration elapses (Locust exits
  after `--autoquit 10`), when the master process dies (the run turns
  *Failed*, results are salvaged if a CSV exists), or after three
  consecutive polls without an answer from Locust.
- Running runs cannot be deleted.

## 6. Distributed workers

Set *Locust worker processes* > 0 on the scenario. The run spawns the
master with `--master --expect-workers N` and N workers with
`--worker --master-host 127.0.0.1`, each with its own `worker_N.log`.
Workers run on the same host as Odoo; use them when a single Locust
process cannot generate enough load (Locust is CPU bound per process).

## 7. Reading results

- *Summary*: total requests, failures, failure ratio, average req/s and
  p50/p95/p99 of the *Aggregated* row of Locust's `stats_stats.csv`.
- *System Summary*: average/maximum CPU, RAM %, RAM used, RSS and active
  PostgreSQL connections over all samples.
- *Results per Endpoint*: one line per request name (e.g.
  `res.partner.search_read`, `sale.order.create+line`,
  `websocket.presence`).
- *Open in Sentry* (when `loadtest_sentry_org` is set) opens the trace
  explorer for the run's time window.
- Raw artefacts stay in `<data_dir>/loadtest/run_<id>/`.

A threaded development server measures that setup, not Odoo capacity;
target an instance running with `workers > 0` for capacity numbers.

## 8. Cleanup

On the data batch, *Clean Up All* runs in dependency order: cancels and
deletes the generated orders **and every sale order created by the test
users during runs**, deletes generated and run-time products and partners,
deletes the test users' chatter messages and archives the users. The
per-type *Clean Up ...* buttons do one step each; orders must go first.

## Safety notes

- **Never point a scenario at a production database.** Journeys create
  orders, partners, products and chatter messages as the test users, and
  cleanup deletes everything those users created. Use a clone
  (`scripts/clone_db.sh`) or a dedicated instance.
- Test users share the batch *Password* (default `loadtest`). Change it
  before generating users and keep load-test instances off the public
  internet; the users have Sales Manager rights.
- `loadtest_enabled` must be explicitly set to `true` in the server
  configuration of the instance that runs the control plane; leave it
  unset everywhere else.
- A wrong batch password triggers Odoo's per-IP login cooldown for all
  virtual users (see *Configure*).
