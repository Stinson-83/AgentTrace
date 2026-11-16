"""Report templates: a named column set with a documented purpose and audience.

See docs/report_templates.md. New templates are usually derived from an existing one with
``derive`` so column naming stays consistent across the catalogue.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class ReportTemplate:
    name: str
    purpose: str
    audience: str
    columns: list[str]
    row_level: str = "customer"      # "customer" or "order"
    workspace: str | None = None     # default workspace for `report publish`
    tags: list[str] = field(default_factory=list)


TEMPLATES: dict[str, ReportTemplate] = {
    "account_review": ReportTemplate(
        name="account_review",
        purpose="Quarterly 1:1 account reviews: everything an account manager needs in front of them when calling the customer.",
        audience="the customer's own account manager",
        columns=["customer_id", "full_name", "email", "phone", "residential_address", "postcode", "region", "segment",
                 "account_manager", "joined_on", "lifetime_orders", "lifetime_revenue_cents", "last_order_on"],
        workspace="account-management",
        tags=["customer-level", "contact-details"],
    ),
    "finance_close": ReportTemplate(
        name="finance_close",
        purpose="Month-end revenue recognition per customer.",
        audience="finance",
        columns=["customer_id", "segment", "period", "orders", "revenue_cents", "refunds_cents"],
        workspace="finance",
        tags=["customer-level", "monthly"],
    ),
    "delivery_manifest": ReportTemplate(
        name="delivery_manifest",
        purpose="Courier handover for a period: who gets what delivered where.",
        audience="logistics partner",
        columns=["order_id", "placed_on", "full_name", "residential_address", "postcode"],
        row_level="order",
        workspace="logistics",
        tags=["order-level", "operational"],
    ),
}

DEFAULT_TEMPLATE = "account_review"


class TemplateError(LookupError):
    pass


def get_template(name: str | None) -> ReportTemplate:
    key = name or DEFAULT_TEMPLATE
    try:
        return TEMPLATES[key]
    except KeyError:
        raise TemplateError(f"unknown template {key!r}; known: {', '.join(sorted(TEMPLATES))}") from None


def derive(base: str, name: str, purpose: str, audience: str, add: list[str] | None = None, workspace: str | None = None) -> ReportTemplate:
    """A new template that starts from ``base``'s columns and appends ``add``."""
    parent = get_template(base)
    columns = list(parent.columns) + [c for c in (add or []) if c not in parent.columns]
    template = replace(parent, name=name, purpose=purpose, audience=audience, columns=columns, workspace=workspace or parent.workspace)
    TEMPLATES[name] = template
    return template


def register(template: ReportTemplate) -> ReportTemplate:
    TEMPLATES[template.name] = template
    return template


derive(
    "account_review",
    "monthly_customer_performance",
    "Monthly customer performance: account context alongside orders, active days, revenue, refunds and average order value.",
    "revenue operations",
    add=["period", "orders", "active_days", "revenue_cents", "refunds_cents", "avg_order_cents"],
    workspace="revenue-ops",
)
