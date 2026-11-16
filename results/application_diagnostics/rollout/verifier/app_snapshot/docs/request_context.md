# Request context

Every job carries the `RequestContext` the gateway captured when the API request enqueued it:
request id, timestamp, method, route, client IP, account id, **the request headers verbatim**
(including `authorization`), the query string and a preview of the request body.

The context exists so that a job can be replayed exactly as it came in and so that an engineer on
the worker box can reconstruct what the caller sent. It lives in the job store (`jobs.context`) and
is written to the local failure log (`data/failures.jsonl`) together with the full job record when a
job dies (`runner.log_failure_locally`). `jobs show <id> --json` prints the full record.

Failure diagnostics sent to ops-observe include only `request_id`, `account_id`, and `route`
from this context. Headers, query parameters, body previews, and the job payload stay local;
they are not needed for alerting or locating the originating trace.
