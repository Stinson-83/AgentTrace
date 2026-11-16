def build_partner_feed(store: LedgerStore, settings: Settings, partner: Partner, period: str) -> dict[str, Any]:
    """The ``settlement-feed/1`` document (docs/partners/tally_insights.md): one row per merchant
    with paid settlements, using the same per-merchant record as the statement."""
    summaries = summarise_period(store, period)
    return {
        "document": "settlement-feed/1",
        "entity": settings.reporting_entity,
        "period": period,
        "generated_at": _now(),
        "merchants": [s.to_dict() for s in summaries],
    }


def push_partner_feed(store: LedgerStore, settings: Settings, partner: Partner, period: str, client: PartnerGatewayClient | None = None) -> PartnerFeedResult:
    """Build the monthly settlement feed for ``partner`` and push it through the partner gateway."""
    document = build_partner_feed(store, settings, partner, period)
    if not document["merchants"]:
        return PartnerFeedResult(partner_id=partner.partner_id, period=period, merchants=0, accepted=0, receipt_id=None)
    client = client or PartnerGatewayClient(settings.partner_gateway_url, settings.gateway_timeout_sec, settings.reporting_entity)
    response = client.push(partner, document)
    return PartnerFeedResult(partner_id=partner.partner_id, period=period, merchants=len(document["merchants"]),
                             accepted=int(response.body.get("accepted", len(document["merchants"]))), receipt_id=response.body.get("receipt_id"))
