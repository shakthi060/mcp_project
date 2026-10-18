"""Tests for the MCP server tools, using an isolated temporary database."""

import pytest

import database
import server


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point the server at a fresh temporary database for every test."""
    db_file = tmp_path / "tool_test.db"
    monkeypatch.setenv("EXPENSE_DB_PATH", str(db_file))
    database.init_db()
    return db_file


def test_add_expense_tool_returns_saved_record():
    result = server.add_expense(
        amount=250.50,
        category="Food",
        description="Lunch at office canteen",
        expense_date="2026-10-05",
    )
    assert result["status"] == "created"
    expense = result["expense"]
    assert expense["amount_paise"] == 25050
    assert expense["amount"] == "₹250.50"
    assert expense["category"] == "Food"
    assert expense["expense_date"] == "2026-10-05"

    assert server.monthly_total(year=2026, month=10)["total_paise"] == 25050


def test_add_expense_rejects_invalid_input():
    with pytest.raises(ValueError, match="greater than zero"):
        server.add_expense(amount=0, category="Food", description="Bad")
    with pytest.raises(ValueError, match="greater than zero"):
        server.add_expense(amount=-10, category="Food", description="Bad")
    with pytest.raises(ValueError, match="category must not be empty"):
        server.add_expense(amount=100, category="   ", description="Bad")
    with pytest.raises(ValueError, match="description must not be empty"):
        server.add_expense(amount=100, category="Food", description="")
    with pytest.raises(ValueError, match="not a valid date"):
        server.add_expense(
            amount=100, category="Food", description="Bad", expense_date="18-10-2026"
        )
    with pytest.raises(ValueError, match="more than two decimal places"):
        server.add_expense(amount=10.999, category="Food", description="Bad")


def test_monthly_total_and_top_categories():
    server.add_expense(amount=500, category="Food", description="Groceries",
                       expense_date="2026-09-02")
    server.add_expense(amount=300, category="Food", description="Pizza",
                       expense_date="2026-09-05")
    server.add_expense(amount=900, category="Travel", description="Flight",
                       expense_date="2026-09-10")

    total = server.monthly_total(year=2026, month=9)
    assert total["total"] == "₹1700.00"
    assert total["total_paise"] == 170000
    assert total["expense_count"] == 3

    ranked = server.top_categories(year=2026, month=9, limit=5)
    assert ranked[0]["category"] == "Travel"
    assert ranked[1]["category"] == "Food"
    assert ranked[1]["expense_count"] == 2
    assert ranked[1]["total"] == "₹800.00"


def test_empty_month_and_invalid_arguments():
    empty = server.monthly_total(year=2024, month=7)
    assert empty["total"] == "₹0.00"
    assert empty["expense_count"] == 0
    assert server.top_categories(year=2024, month=7) == []

    with pytest.raises(ValueError, match="month must be between 1 and 12"):
        server.monthly_total(year=2026, month=13)
    with pytest.raises(ValueError, match="year must be between"):
        server.monthly_total(year=1999, month=1)
    with pytest.raises(ValueError, match="limit must be between"):
        server.top_categories(year=2026, month=1, limit=0)
    with pytest.raises(ValueError, match="limit must be between"):
        server.top_categories(year=2026, month=1, limit=999)


def test_repeated_idempotency_key_does_not_duplicate():
    first = server.add_expense(amount=250, category="Food", description="Lunch",
                               expense_date="2026-10-05", idempotency_key="k-1")
    second = server.add_expense(amount=250, category="Food", description="Lunch",
                                expense_date="2026-10-05", idempotency_key="k-1")
    assert second["status"] == "duplicate_ignored"
    assert second["expense"]["id"] == first["expense"]["id"]
    assert server.monthly_total(year=2026, month=10)["expense_count"] == 1
