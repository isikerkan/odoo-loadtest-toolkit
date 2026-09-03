## Server configuration (odoo.conf)

The module reads these keys from the Odoo server configuration
(`odoo.tools.config`), not from system parameters:

| Key | Default | Description |
|---|---|---|
| `loadtest_enabled` | `false` | Safety guard. Must be `true` for *Generate* actions on data batches and for starting a run. Any other value (or absence) makes those actions raise an error, so the module can sit installed on an unprepared database without being able to create data. |
| `loadtest_sentry_org` | unset | Sentry organisation slug. When set, runs compute a `sentry_url` pointing at `https://<org>.sentry.io/explore/traces/?start=...&end=...` for the run's time window and show an *Open in Sentry* button. |
| `data_dir` | Odoo default | Standard Odoo option; run artefacts are written to `<data_dir>/loadtest/run_<id>/`. |

Example:

```ini
[options]
loadtest_enabled = true
loadtest_sentry_org = my-org
```

## Environment variables read by the Locust process

`locustfiles/journeys.py` is configured through environment variables.
The run sets all but the last one automatically when it spawns Locust;
they are documented so the locustfile can also be launched by hand.

| Variable | Set by the run to | Default in the locustfile | Description |
|---|---|---|---|
| `ODOO_DB` | the current database name | `""` | Database passed to `/web/session/authenticate`. |
| `LOADTEST_LOGINS` | comma-separated logins of the batch's test users | empty, falls back to `loadtest_001` | Virtual users cycle through these logins. |
| `LOADTEST_PASSWORD` | the batch's *Password* field | `loadtest` | Shared password of the test users. |
| `LOADTEST_WEIGHTS` | JSON `{"ClassName": weight}` from the scenario's journey mix | `{}` (class defaults: Browser 3, SalesRep 2, Chatter 1, CatalogEditor 1, Presence 2, ErrorLab 1) | Relative share of virtual users per journey. Only classes with weight > 0 are passed on the command line. |
| `LOADTEST_WS_VERSION` | not set (inherited from the Odoo process environment) | `18.0-7` | `version` query parameter of the bus websocket handshake used by the *Presence* journey. Adjust if the target runs a different bus protocol version. |

The child process inherits the full environment of the Odoo process, so
`LOADTEST_WS_VERSION` (or proxy variables) can be set on the Odoo service.

## Journey catalog

*Load Testing > Configuration > Journeys* lists the available Locust user
classes. `code` must match a class name in `locustfiles/journeys.py`.
Entries can be archived to hide them from the scenario mix; the records
are shipped as `noupdate` data, so local edits survive module updates.

## Login cooldown on the target

All virtual users share one source IP. After a run with a wrong batch
password Odoo's per-IP login throttling (`res.users._assert_can_auth`)
blocks every further login for several minutes. On load-test instances
raise the threshold with the system parameter
`base.login_cooldown_after = 50` (`0` disables it).
