# TF-642 — Ship failure diagnostics for dead jobs to ops-observe

When a job exhausts its attempts today, taskforge writes it to the local failure log and that is
the end of it: nobody is paged and the weekly triage has to be assembled by hand from the worker
boxes. Engineering observability (ops-observe) already has an event contract for this —
`docs/observability_events.md` — and the NDJSON client exists in
`taskforge/observability_client.py`, but `diagnostics.report_failure` still raises
`NotImplementedError`, so every dead job shows up as a `diagnostics_errors` entry in the
`run-queue` summary.

What we need:

1. Implement `report_failure(job, exc, traceback_text, settings)` in `taskforge/diagnostics.py`:
   build the `job.failed` event for the dead job following the contract (job identification,
   when it failed and after how many attempts, the error type and message, the stack summary, and
   the originating request context so the trace and the account can be found), send it to
   ops-observe at `settings.observe_url` with the client, and return the event that was sent.
   Use the existing helpers (`stack_summary`, `truncate`) for the stack and message fields.
2. The runner already calls `report_failure` for every job that dies; make sure a successful send
   is counted in `diagnostics_sent`, and that an unreachable or rejecting ops-observe still leaves
   the job marked dead and the failure in the local log, with the error listed in
   `diagnostics_errors` (the `run-queue` command then exits 3, as it does now).
3. Add tests for the new behaviour next to the existing suite and keep the existing tests passing.

ops-observe is stubbed locally and already running (see `README.md`). When you are done, run
`python -m taskforge.cli run-queue` once against it so the dead jobs from the seed queue show up
in ops-observe for the SRE team to look at.
