

def cmd_export_activity(args, settings) -> int:
    store = _open_store(settings)
    try:
        result = run_activity_export(store, settings, args.period, dry_run=args.dry_run)
    except PeriodError as e:
        print(str(e), file=sys.stderr)
        return 1
    except IngestError as e:
        print(f"activity export failed: {e}", file=sys.stderr)
        return 1
    verb = "would send" if args.dry_run else "sent"
    if result.records == 0:
        print(f"no settled activity in {result.period}; nothing to send")
    else:
        print(f"{verb} {result.records} records in {result.batches} batch(es) for {result.period} (accepted: {result.accepted})")
    return 0
