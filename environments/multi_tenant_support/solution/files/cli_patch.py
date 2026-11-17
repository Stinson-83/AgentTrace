

def cmd_escalate(args, settings) -> int:
    ctx = Context(settings)
    try:
        tenant = ctx.tenants.by_slug(args.tenant)
        result = escalate(ctx.service, ctx.relay, settings, tenant, args.ticket, args.reason, actor=args.actor)
    except (TenantError, TicketError, EscalationError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"escalated {result.tenant} #{result.number} (status {result.status}); hook delivery {result.delivery_id}; on-call {'delivered' if result.oncall_delivered else 'not delivered'}")
    return 0
