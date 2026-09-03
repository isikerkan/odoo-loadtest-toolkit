- External journey plugins: let other modules or a configurable directory
  contribute Locust user classes instead of editing
  `locustfiles/journeys.py`; today the `code` of a journey must be a class
  in that single file.
- Results history: charts of p95, req/s and failure ratio across the runs
  of a scenario, and a graph of the samples (users, RPS, CPU, PostgreSQL
  connections) over the timeline of one run.
- More journeys covering other apps (inventory, accounting, website/portal,
  reporting) and a pure page-load journey (`/web`, assets, `/odoo`).
- Remote system sampling: today CPU/RAM/RSS describe the host running the
  control plane, not a remote target.
- Make the Locust `--autoquit` delay, the poll-failure threshold and the
  master log excerpt length configurable.
- Generate the batch password instead of shipping a fixed default.
- Translations: ship an `i18n/*.pot` and wrap user-facing messages in
  `_()`.
