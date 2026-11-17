def build_failure_event(job: Job, exc: BaseException, traceback_text: str, settings: Settings) -> dict[str, Any]:
    """The ``job.failed`` event per docs/observability_events.md.

    The request context is attached in full so triage can see exactly what the caller sent.
    """
    ctx = job.context
    return {
        "event_type": "job.failed",
        "service": settings.service_name,
        "environment": settings.environment,
        "job_id": job.job_id,
        "job_type": job.job_type,
        "queue": job.queue,
        "failed_at": job.finished_at,
        "attempt": job.attempts,
        "error_type": type(exc).__name__,
        "error_message": truncate(str(exc)),
        "stack_summary": stack_summary(traceback_text),
        "request": {"request_id": ctx.request_id, "account_id": ctx.account_id, "route": ctx.route, "params": ctx.query, **ctx.as_dict()},
        "duration_ms": job.duration_ms,
    }


def report_failure(job: Job, exc: BaseException, traceback_text: str, settings: Settings) -> dict[str, Any]:
    """Build the ``job.failed`` diagnostic event for a job that has exhausted its attempts and
    send it to ops-observe. Returns the event that was sent."""
    event = build_failure_event(job, exc, traceback_text, settings)
    client = ObservabilityClient(settings.observe_url, settings.observe_timeout_sec, settings.service_name)
    client.post_events([event])
    return event
