## 18.0.5.0.2

- Run charts shrink with the page again: the canvas no longer holds its
  column open when the browser zooms in or the window gets narrower, so
  the block resizes instead of overflowing sideways.

## 18.0.5.0.1

- Run charts size with the page: the aside grows into the width the
  sheet leaves over, panel heights follow the viewport height, and below
  the sheet the panels arrange in one to three columns by available width.

## 18.0.5.0.0

- Generated partners, products and orders point back at their batch with
  an indexed `loadtest_batch_id` (many2one) instead of relation tables;
  counts use `search_count`, cleanup runs in chunks. Migration moves the
  existing links.
- Generation is chunk-capable and idempotent:
  `_generate_<kind>_chunk(start, size)` creates the records of an index
  range and skips the ones that already exist (deterministic keys
  `LT<batch>-P…`, `LT<batch>-…`, `LT<batch>-O…`), ready for background
  jobs.
- Products are generated as templates (one variant each); orders sample
  a bounded pool of partners and variants.

## 18.0.4.3.0

- Timeline charts on the run form (Chart.js from Odoo's bundle): users
  and current requests/s, p50/p95 with the failure ratio, CPU/RAM and
  PostgreSQL connections, drawn from the poll samples.

## 18.0.4.2.0

- Samples store Locust's current requests/s, p50/p95 of the last seconds
  and the failure count.
- *Samples* smart button on the run: Odoo graph view over time, list and
  search views.
- Tests run `post_install` and no longer assume an empty database.

## 18.0.4.1.0

- Presence journey: one Odoo bus websocket per virtual user with
  subscribe, presence heartbeats and notification draining; sends the
  `Origin` header on the handshake.
- Error Lab journey for the `sentry_error_lab` endpoints.
- `scripts/clone_db.sh` to clone a database for load testing.
- CI: ruff lint and format check, compile and XML validation.

## 18.0.4.0.0

- Zombie-aware process liveness and poll-failure fallback so runs no
  longer stay *Running* forever.
- RAM used in GB and CPU core count in samples and summaries.

## 18.0.3.3.0

- Scenario duration as value + unit (seconds/minutes/hours/days/infinite);
  migration converts stored seconds.
- Prime the psutil CPU baseline at import.

## 18.0.3.2.0

- *Stop At*: scheduled stop for open-ended runs, checked by the poll cron.

## 18.0.3.1.0

- System samples per run: live view and average/maximum summary.

## 18.0.3.0.0

- Scenarios and Locust runs driven from Odoo: detached Locust process,
  REST polling, CSV ingestion, distributed workers, Sentry link.
- Numeric next-user index (`loadtest_999` / `loadtest_1000`).

## 18.0.2.1.0

- Per-type generate and clean-up actions in the batch form header.

## 18.0.2.0.1

- Use the app icon in the app switcher.

## 18.0.2.0.0

- Per-type generate and clean-up actions.

## 18.0.1.3.0

- Test users get Sales Manager rights.

## 18.0.1.2.0

- Cleanup sweeps the records test users created during runs.

## 18.0.1.1.0

- Smart buttons and tabs for generated data.

## 18.0.1.0.0

- Initial release: load-test data batches with guarded generation and
  cleanup.
