import pytest

from reportkit.column_selector import CATALOGUE, ColumnError, resolve_columns
from reportkit.templates import TEMPLATES, TemplateError, derive, get_template


def test_catalogue_and_templates_consistent():
    for t in TEMPLATES.values():
        assert all(c in CATALOGUE for c in t.columns), t.name
    assert get_template(None).name == "account_review"
    with pytest.raises(TemplateError):
        get_template("nope")


def test_resolve_columns_include_exclude():
    t = get_template("finance_close")
    cols = resolve_columns(t, include=["region"], exclude=["refunds_cents"])
    assert "region" in cols and "refunds_cents" not in cols and cols[0] == "customer_id"
    with pytest.raises(ColumnError):
        resolve_columns(t, include=["made_up"])
    with pytest.raises(ColumnError):
        resolve_columns(t, include=["order_id"])


def test_derive_keeps_base_columns():
    t = derive("finance_close", "finance_close_regional", "regional close", "finance", add=["region"])
    assert t.columns[: len(TEMPLATES["finance_close"].columns)] == TEMPLATES["finance_close"].columns and t.columns[-1] == "region"
    TEMPLATES.pop("finance_close_regional")
