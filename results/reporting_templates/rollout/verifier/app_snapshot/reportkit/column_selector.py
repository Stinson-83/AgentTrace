"""Column catalogue and template column resolution."""
from __future__ import annotations

from dataclasses import dataclass

from .templates import ReportTemplate


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    source: str        # profile | period-metric | lifetime-metric | order
    description: str
    implemented: bool = True


CATALOGUE: dict[str, ColumnSpec] = {c.name: c for c in [
    ColumnSpec("customer_id", "profile", "Customer identifier"),
    ColumnSpec("full_name", "profile", "Customer name"),
    ColumnSpec("email", "profile", "Contact e-mail"),
    ColumnSpec("phone", "profile", "Contact phone"),
    ColumnSpec("date_of_birth", "profile", "Date of birth"),
    ColumnSpec("residential_address", "profile", "Delivery / residential address"),
    ColumnSpec("postcode", "profile", "Postcode"),
    ColumnSpec("region", "profile", "Sales region"),
    ColumnSpec("segment", "profile", "Subscription segment (plus / standard / trial)"),
    ColumnSpec("account_manager", "profile", "Owning account manager"),
    ColumnSpec("joined_on", "profile", "Join date"),
    ColumnSpec("period", "period-metric", "Reporting period YYYY-MM"),
    ColumnSpec("orders", "period-metric", "Fulfilled orders in the period"),
    ColumnSpec("revenue_cents", "period-metric", "Sum of fulfilled order totals in the period"),
    ColumnSpec("refunds_cents", "period-metric", "Sum of refunded order totals in the period"),
    ColumnSpec("active_days", "period-metric", "Distinct days with a fulfilled order in the period"),
    ColumnSpec("avg_order_cents", "period-metric", "revenue_cents / orders (0 when no orders)"),
    ColumnSpec("lifetime_orders", "lifetime-metric", "Fulfilled orders ever"),
    ColumnSpec("lifetime_revenue_cents", "lifetime-metric", "Sum of fulfilled order totals ever"),
    ColumnSpec("last_order_on", "lifetime-metric", "Date of the last fulfilled order"),
    ColumnSpec("order_id", "order", "Order identifier"),
    ColumnSpec("placed_on", "order", "Order date"),
]}


class ColumnError(ValueError):
    pass


def resolve_columns(template: ReportTemplate, include: list[str] | None = None, exclude: list[str] | None = None) -> list[str]:
    """Final column list for a run: template columns plus ``include`` minus ``exclude``, validated."""
    columns = [c for c in template.columns if c not in set(exclude or [])]
    for c in include or []:
        if c not in columns:
            columns.append(c)
    unknown = [c for c in columns if c not in CATALOGUE]
    if unknown:
        raise ColumnError(f"unknown column(s): {', '.join(unknown)}")
    if template.row_level == "customer" and any(CATALOGUE[c].source == "order" for c in columns):
        raise ColumnError("order-level columns cannot be used in a customer-level template")
    return columns


def columns_by_source(columns: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in columns:
        out.setdefault(CATALOGUE[c].source, []).append(c)
    return out
