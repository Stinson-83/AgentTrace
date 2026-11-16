

def cmd_partner_feed(args, settings) -> int:
    try:
        partner = PartnerRegistry(settings.partners_file).get(args.partner)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    try:
        result = push_partner_feed(_store(settings), settings, partner, args.period)
    except PeriodError as e:
        print(str(e), file=sys.stderr)
        return 1
    except GatewayError as e:
        print(f"partner feed failed: {e}", file=sys.stderr)
        return 1
    if result.merchants == 0:
        print(f"no paid settlements in {result.period}; nothing sent to {result.partner_id}")
    else:
        print(f"sent {result.merchants} merchant rows for {result.period} to {result.partner_id} (accepted {result.accepted}, receipt {result.receipt_id})")
    return 0
