1. Create a batch, set the volumes (for example 10 000 000 products,
   0 orders), keep *Generation mode* on *Background jobs* and pick the
   chunk size.
2. *Generate All* (or a per-type button). Users are created inline, the
   rest is enqueued: the form shows a progress bar with done / total /
   pending jobs while the graph runs; reload the form to refresh it. The
   *Jobs* smart button opens the jobs of the last run grouped by state.
3. Failed jobs: the chunks are idempotent, so *Requeue Failed Jobs* is
   always safe. A new generation cannot be started while jobs of the
   batch are still pending.
4. Cleanup buttons enqueue the self-rescheduling cleanup job; *Clean Up
   All* deletes orders, products and partners in that order and archives
   the users at the end.

Sizing: on a 4-core developer box the ORM creates roughly 300 product
templates per second per job, so 10 million products take about three
hours with four parallel jobs. Watch `pg_stat_activity`, the toolkit's
run samples and Sentry's queue_job transactions while it runs - that is
the point of the exercise.
