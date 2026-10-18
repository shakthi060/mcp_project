"""Tests for the database layer using an isolated temporary SQLite file."""

import pytest

import database


@pytest.fixture
def db_path(tmp_path):
    """A fresh temporary database file for each test."""
    path = tmp_path / "test_expenses.db"
    database.init_db(path)
    return path


def test_add_and_retrieve_expense(db_path):
    record = database.insert_expense(
        amount_paise=25050,
        category="Food",
        description="Lunch at office canteen",
        expense_date="2026-10-01",
        db_path=db_path,
    )
    assert record["id"] >= 1
    assert record["amount_paise"] == 25050
    assert record["amount"] == "₹250.50"
    assert record["category"] == "Food"
    assert record["expense_date"] == "2026-10-01"
    assert record["created_at"]

    fetched = database.get_expense(record["id"], db_path=db_path)
    assert fetched == record


def test_monthly_total_and_empty_month(db_path):
    database.insert_expense(10000, "Food", "Dinner", "2026-01-15", db_path=db_path)
    database.insert_expense(25000, "Travel", "Cab to airport", "2026-01-31", db_path=db_path)
    database.insert_expense(99999, "Food", "Next month", "2026-02-01", db_path=db_path)

    january = database.monthly_summary(2026, 1, db_path=db_path)
    assert january["total_paise"] == 35000
    assert january["expense_count"] == 2

    february = database.monthly_summary(2026, 2, db_path=db_path)
    assert february["total_paise"] == 99999

    empty = database.monthly_summary(2025, 12, db_path=db_path)
    assert empty["total_paise"] == 0
    assert empty["expense_count"] == 0


def test_top_categories_ranking(db_path):
    database.insert_expense(50000, "Food", "Groceries", "2026-03-02", db_path=db_path)
    database.insert_expense(30000, "Food", "Pizza", "2026-03-05", db_path=db_path)
    database.insert_expense(90000, "Travel", "Flight", "2026-03-10", db_path=db_path)
    database.insert_expense(10000, "Stationery", "Notebook", "2026-03-12", db_path=db_path)

    ranked = database.category_summary(2026, 3, limit=5, db_path=db_path)
    assert [r["category"] for r in ranked] == ["Travel", "Food", "Stationery"]
    assert ranked[0]["total_paise"] == 90000
    assert ranked[0]["expense_count"] == 1
    assert ranked[1]["total_paise"] == 80000  # 50000 + 30000
    assert ranked[1]["expense_count"] == 2
    assert ranked[1]["total"] == "₹800.00"


def test_idempotency_key_blocks_duplicate_insert(db_path):
    key = "client-abc-123"
    first = database.insert_expense(
        25000, "Food", "Lunch", "2026-04-01", idempotency_key=key, db_path=db_path
    )
    with pytest.raises(Exception):
        database.insert_expense(
            25000, "Food", "Lunch", "2026-04-01", idempotency_key=key, db_path=db_path
        )
    assert database.find_by_idempotency_key(key, db_path=db_path) == first
    assert len(database.list_expenses(db_path=db_path)) == 1
