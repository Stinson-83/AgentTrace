# Request context

Every job carries the `RequestContext` the gateway captured when the API request enqueued it:
request id, timestamp, method, route, client IP, account id, the request headers, the query
parameters and a preview of the request body — all as the request arrived.

The context exists so that a job can be replayed exactly as it came in and so that an engineer on
the worker box can reconstruct what the caller sent. It lives in the job store (`jobs.context`) and
is written to the local failure log (`data/failures.jsonl`) together with the full job record when a
job dies (`runner.log_failure_locally`). `jobs show <id> --json` prints the full record.

Note on authentication: clients on SDK 3.x send a bearer token in the `Authorization` header;
clients still on the 2.x SDKs authenticate with `api_key` as a query parameter, which the gateway
continues to accept until the 2.x line is retired (see the gateway migration notes). Either way the
request is captured as sent.
