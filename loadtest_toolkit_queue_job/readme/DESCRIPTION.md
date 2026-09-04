Glue between the Load Test Toolkit and OCA `queue_job`: data batches are
generated and cleaned up by background jobs instead of inside the
request that clicks the button. That is the only way to build batches of
millions of records (the explicit use case: ten million products to see
how Sentry APM reports long-running and badly indexed SQL).

Installed automatically when both `loadtest_toolkit` and `queue_job` are
present; without `queue_job` the toolkit keeps its inline generation and
nothing here exists.

How it works:

- Every generation kind is split into chunks of *Records per job*
  (default 2000). The toolkit's chunk methods are idempotent, so a job
  can be retried without duplicates.
- The chunks form a job graph: partners and products run in parallel,
  orders wait for both, a *finalize* job waits for everything.
- Cleanup is a self-rescheduling job: each run deletes one chunk of the
  first kind that still has records, then enqueues itself again until
  nothing is left, and finally archives the test users.
- Jobs run on the `root.loadtest` channel so their concurrency is set in
  the server configuration, independent from the rest of the queue.
