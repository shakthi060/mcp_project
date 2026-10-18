"""SQLite persistence layer for the Expense Tracker MCP server.

Money is stored as integer minor units (paise) so that rupee amounts such as
₹250.50 are exact and never suffer from floating-point rounding errors.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "expenses.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_paise    INTEGER NOT NULL CHECK (amount_paise > 0),
    category        TEXT    NOT NULL CHECK (length(trim(category)) > 0),
    description     TEXT    NOT NULL CHECK (length(trim(description)) > 0),
    expense_date    TEXT    NOT NULL,
    idempotency_key TEXT,
    created_at      TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_expenses_idempotency
    ON expenses (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (expense_date);
"""


def get_db_path() -> Path:
    """Resolve the database path: EXPENSE_DB_PATH env var, else data/expenses.db."""
    override = os.environ.get("EXPENSE_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_connection(db_path: Path | None = None):
    """Open a connection, committing on success and rolling back on error."""
    path = Path(db_path) if db_path is not None else get_db_path()
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Create tables/indexes if they do not exist. Safe to call repeatedly."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "amount_paise": row["amount_paise"],
        "amount": f"₹{row['amount_paise'] / 100:.2f}",
        "category": row["category"],
        "description": row["description"],
        "expense_date": row["expense_date"],
        "idempotency_key": row["idempotency_key"],
        "created_at": row["created_at"],
    }


def find_by_idempotency_key(key: str, db_path: Path | None = None) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM expenses WHERE idempotency_key = ?", (key,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def insert_expense(
    amount_paise: int,
    category: str,
    description: str,
    expense_date: str,
    idempotency_key: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """Insert one expense and return the stored record as a dictionary.

    Raises sqlite3.IntegrityError if the idempotency_key already exists,
    which callers use to detect accidental repeated tool calls.
    """
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO expenses
                (amount_paise, category, description, expense_date,
                 idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (amount_paise, category, description, expense_date,
             idempotency_key, created_at),
        )
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _row_to_dict(row)


def get_expense(expense_id: int, db_path: Path | None = None) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_expenses(db_path: Path | None = None) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM expenses ORDER BY expense_date DESC, id DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _month_range(year: int, month: int) -> tuple[str, str]:
    """Inclusive [start, end) date strings for a calendar month."""
    if month == 12:
        start = f"{year:04d}-12-01"
        end = f"{year + 1:04d}-01-01"
    else:
        start = f"{year:04d}-{month:02d}-01"
        end = f"{year:04d}-{month + 1:02d}-01"
    return start, end


def monthly_summary(year: int, month: int, db_path: Path | None = None) -> dict:
    """Return total_paise and expense_count for one calendar month."""
    start, end = _month_range(year, month)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0) AS total_paise,
                   COUNT(*)                        AS expense_count
            FROM expenses
            WHERE expense_date >= ? AND expense_date < ?
            """,
            (start, end),
        ).fetchone()
    return {
        "year": year,
        "month": month,
        "total_paise": row["total_paise"],
        "expense_count": row["expense_count"],
    }


def category_summary(
    year: int, month: int, limit: int, db_path: Path | None = None
) -> list[dict]:
    """Rank categories for a month by total spending, highest first."""
    start, end = _month_range(year, month)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT category,
                   SUM(amount_paise) AS total_paise,
                   COUNT(*)          AS expense_count
            FROM expenses
            WHERE expense_date >= ? AND expense_date < ?
            GROUP BY category
            ORDER BY total_paise DESC, category ASC
            LIMIT ?
            """,
            (start, end, limit),
        ).fetchall()
    return [
        {
            "category": r["category"],
            "total_paise": r["total_paise"],
            "total": f"₹{r['total_paise'] / 100:.2f}",
            "expense_count": r["expense_count"],
        }
        for r in rows
    ]
