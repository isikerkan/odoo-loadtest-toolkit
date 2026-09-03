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
