"""Expense Tracker MCP Server (stdio transport).

Tools:   add_expense, monthly_total, top_categories
Resource: expenses://records
Prompt:   budget-summary

Stdout is reserved for the MCP protocol; never print status messages there.
"""

import sqlite3
from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

import database

mcp = FastMCP(
    "expense-tracker",
    instructions=(
        "Personal expense tracker backed by SQLite. Use add_expense to record "
        "spending, monthly_total to sum a month's spending, and top_categories "
        "to rank categories. Amounts are Indian Rupees. Read the "
        "expenses://records resource for the raw JSON record list."
    ),
)

# Resource limits (documented in the README).
MAX_AMOUNT_RUPEES = 10_000_000
MAX_CATEGORY_LEN = 100
MAX_DESCRIPTION_LEN = 500
MAX_IDEMPOTENCY_KEY_LEN = 200
MAX_TOP_LIMIT = 50
MIN_YEAR = 2000
MAX_YEAR = 2100


def _validate_money(amount: Any) -> int:
    """Return whole paise for a rupee amount, or raise ValueError."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValueError("amount must be a number, e.g. 250.50")
    if amount != amount or amount in (float("inf"), float("-inf")):
        raise ValueError("amount must be a finite number")
    if amount <= 0:
        raise ValueError("amount must be greater than zero (rejects 0 and negatives)")
    if amount > MAX_AMOUNT_RUPEES:
        raise ValueError(f"amount must not exceed ₹{MAX_AMOUNT_RUPEES:,}")
    paise = round(amount * 100)
    if abs(amount * 100 - paise) > 1e-6:
        raise ValueError(
            "amount has more than two decimal places; use paise precision "
            "like 250.50"
        )
    return paise


def _validate_text(value: Any, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty or blank")
    if len(cleaned) > max_len:
        raise ValueError(f"{field} must be {max_len} characters or fewer")
    return cleaned


def _validate_date(expense_date: str | None) -> str:
    """Validate an ISO YYYY-MM-DD date; default to today when omitted."""
    if expense_date is None or expense_date == "":
        return date.today().isoformat()
    if not isinstance(expense_date, str):
        raise ValueError("expense_date must be text in YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(expense_date.strip())
    except ValueError:
        raise ValueError(
            f"expense_date '{expense_date}' is not a valid date; "
            "use YYYY-MM-DD, for example 2026-10-18"
        ) from None
    return parsed.isoformat()


def _validate_year_month(year: Any, month: Any) -> tuple[int, int]:
    if isinstance(year, bool) or not isinstance(year, int):
        raise ValueError("year must be a whole number, e.g. 2026")
    if isinstance(month, bool) or not isinstance(month, int):
        raise ValueError("month must be a whole number from 1 to 12")
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")
    if not 1 <= month <= 12:
        raise ValueError(f"month must be between 1 and 12, got {month}")
    return year, month


@mcp.tool()
def add_expense(
    amount: float,
    category: str,
    description: str,
    expense_date: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Add an expense to the tracker and return the saved record.

    Args:
        amount: Price in Indian Rupees, positive with at most 2 decimals,
            e.g. 250.50. Zero and negative values are rejected.
        category: Non-empty spending category, e.g. "Food", "Transport".
        description: Non-empty short note, e.g. "Lunch at office canteen".
        expense_date: Optional date in YYYY-MM-DD format. Defaults to today.
        idempotency_key: Optional unique string. If the same key is sent again
            (accidental repeated tool call), the original record is returned
            instead of inserting a duplicate. Omit it for genuinely new
            purchases that happen to look alike.
    """
    amount_paise = _validate_money(amount)
    clean_category = _validate_text(category, "category", MAX_CATEGORY_LEN)
    clean_description = _validate_text(description, "description", MAX_DESCRIPTION_LEN)
    clean_date = _validate_date(expense_date)

    clean_key: str | None = None
    if idempotency_key is not None:
        clean_key = _validate_text(
            idempotency_key, "idempotency_key", MAX_IDEMPOTENCY_KEY_LEN
        )
        existing = database.find_by_idempotency_key(clean_key)
        if existing is not None:
            return {
                "status": "duplicate_ignored",
                "message": (
                    "An expense with this idempotency_key already exists; "
                    "returning the original record without inserting a copy."
                ),
                "expense": existing,
            }

    try:
        record = database.insert_expense(
            amount_paise=amount_paise,
            category=clean_category,
            description=clean_description,
            expense_date=clean_date,
            idempotency_key=clean_key,
        )
    except sqlite3.IntegrityError:
        # Race: the key was inserted between our check and the INSERT.
        if clean_key:
            existing = database.find_by_idempotency_key(clean_key)
            if existing is not None:
                return {
                    "status": "duplicate_ignored",
                    "message": "Duplicate idempotency_key; returning original record.",
                    "expense": existing,
                }
        raise ValueError(
            "Could not save the expense: it conflicts with an existing record."
        ) from None

    return {"status": "created", "expense": record}


@mcp.tool()
def monthly_total(year: int, month: int) -> dict:
    """Calculate total spending for one calendar month.

    Args:
        year: Calendar year, e.g. 2026 (between 2000 and 2100).
        month: Month number from 1 (January) to 12 (December).
    """
    year, month = _validate_year_month(year, month)
    summary = database.monthly_summary(year, month)
    total_rupees = summary["total_paise"] / 100
    return {
        "year": summary["year"],
        "month": summary["month"],
        "total": f"₹{total_rupees:.2f}",
        "total_paise": summary["total_paise"],
        "expense_count": summary["expense_count"],
        "note": (
            "No expenses recorded for this month."
            if summary["expense_count"] == 0
            else ""
        ),
    }


@mcp.tool()
def top_categories(year: int, month: int, limit: int = 5) -> list[dict]:
    """Rank spending categories for one month, highest total first.

    Args:
        year: Calendar year, e.g. 2026 (between 2000 and 2100).
        month: Month number from 1 (January) to 12 (December).
        limit: Maximum categories to return (1 to 50). Default 5.
    """
    year, month = _validate_year_month(year, month)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be a whole number, e.g. 5")
    if not 1 <= limit <= MAX_TOP_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_TOP_LIMIT}, got {limit}")

    ranked = database.category_summary(year, month, limit)
    return [
        {
            "rank": i + 1,
            "category": item["category"],
            "total": item["total"],
            "total_paise": item["total_paise"],
            "expense_count": item["expense_count"],
        }
        for i, item in enumerate(ranked)
    ]


@mcp.resource("expenses://records")
def expense_records() -> str:
    """All expense records as a JSON document (id, amount, category,
    description, expense_date, created_at). Empty list when no records exist."""
    import json

    records = database.list_expenses()
    document = {
        "currency": "INR",
        "storage": "amounts are integer paise; 'amount' is the rupee display string",
        "count": len(records),
        "expenses": records,
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


@mcp.prompt(name="budget-summary", description="Summarize spending and budget observations for a given month using the expense tracker data.")
def budget_summary(year: int, month: int) -> str:
    """Guide the AI to summarize a month's spending from real tracker data.

    Args:
        year: Calendar year of the period to analyze.
        month: Month number (1-12) of the period to analyze.
    """
    month_name = date(year, month, 1).strftime("%B %Y") if 1 <= month <= 12 else f"{month}/{year}"
    return (
        f"You are reviewing personal expenses for {month_name} using the "
        "expense-tracker MCP server.\n\n"
        "Steps to follow:\n"
        "1. Call the monthly_total tool with this year and month to get the "
        "total amount spent and the number of expenses.\n"
        "2. Call the top_categories tool with the same year and month to rank "
        "categories by spending.\n"
        "3. Optionally read the expenses://records resource if individual "
        "records are needed for patterns.\n\n"
        "Then produce a budget summary that:\n"
        f"- States the total spent in {month_name} and how many expenses there were.\n"
        "- Lists the highest-spending categories with their totals and share of "
        "the month where possible.\n"
        "- Highlights notable spending patterns that are actually supported by "
        "the returned data (for example, one category dominating the month).\n"
        "- Suggests practical, generic budget observations without inventing "
        "facts, income figures, or goals that are not in the data.\n"
        "- Explicitly says when data is insufficient (for example, if the month "
        "has zero or very few expenses) instead of guessing.\n\n"
        "Rules: Use only numbers returned by the tools or resource. Never make "
        "up amounts, categories, or dates. Present money in Indian Rupees (₹)."
    )


if __name__ == "__main__":
    database.init_db()
    mcp.run(transport="stdio")
