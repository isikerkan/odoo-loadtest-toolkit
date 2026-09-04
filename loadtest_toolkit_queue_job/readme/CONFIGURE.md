Give the channel capacity in the `[queue_job]` section of the Odoo
configuration, otherwise the jobs wait forever:

```ini
[queue_job]
channels = root:2,root.loadtest:4
```

`root.loadtest:4` runs four generation or cleanup jobs at a time. Each
one is one PostgreSQL transaction of *Records per job* creates; four
parallel jobs of 2000 products each is a sensible default on a
developer machine. The load-test guard of the toolkit
(`loadtest_enabled = true`) applies to the jobs as well.

Per batch:

| Field | Description | Default |
|-------|-------------|---------|
| Generation mode | *Background jobs* enqueues, *Inline* keeps the toolkit's request-time generation | Background jobs |
| Records per job | chunk size of every generation and cleanup job | 2000 |
| Job channel | queue_job channel the batch's jobs run on | `root.loadtest` |
