## Python dependencies

The module is used from the Odoo process **and** from the Locust child
process it spawns, so all packages must be installed in the same Python
environment (virtualenv) that runs Odoo:

| Package | Imported by | Purpose |
|---|---|---|
| `locust` | the spawned child process only (`python -m locust`) | load generator; never imported inside Odoo |
| `requests` | `models/loadtest_run.py` | polling Locust's REST API on `127.0.0.1` |
| `websocket-client` (`import websocket`) | `locustfiles/journeys.py` | the *Presence* journey; optional, the journey fails at start when missing |
| `psutil` | `models/loadtest_run.py` | CPU/RAM/RSS sampling; optional, samples fall back to PostgreSQL counters only |

```sh
/path/to/odoo-venv/bin/pip install locust requests websocket-client psutil
```

Locust is launched as `sys.executable -m locust`, i.e. with the very
interpreter that runs Odoo. It does not need to be on `PATH`; it needs
to be importable by that interpreter.

## Odoo module

1. Put `loadtest_toolkit` in an addons path.
2. Install it (it depends on `sale`; the *Load Testing* app appears in the
   app switcher for administrators, `base.group_system`).
3. Add `loadtest_enabled = true` to the server configuration (see
   *Configure*). Without it data generation and run start are refused.

## Network and filesystem

- Each run binds Locust's web UI/REST API to `127.0.0.1` on a **random free
  port** chosen at start (shown in the *Port* field of the run). Workers
  connect to the master on `127.0.0.1` as well. Nothing listens on a public
  interface.
- Run artefacts (`master.log`, `worker_N.log`, `stats_*.csv`) live in
  `<data_dir>/loadtest/run_<id>/`. The Odoo system user needs write access
  to `data_dir` (it already has it for the filestore).
- The virtual users hit the scenario's *Target URL* over HTTP(S) and, for
  the *Presence* journey, `ws(s)://<target>/websocket`. The target must
  serve the same database the batch users live in.

## Optional helper

`scripts/clone_db.sh <source> <clone>` (repository root, not part of the
addon) copies a database with `CREATE DATABASE ... TEMPLATE` after
terminating open connections and deactivates every outgoing mail server
on the clone, so a load test can run against a copy of real data.
