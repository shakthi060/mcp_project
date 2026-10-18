# Expense Tracker MCP Server

A small, beginner-friendly **Model Context Protocol (MCP)** server written in Python. It lets an AI application record and analyse personal expenses stored in a local SQLite database.

Built for an MCP internship assignment. It implements **three tools**, **one resource** and **one prompt**, uses only the Python standard library plus the official `mcp` SDK, and ships with automated tests.

---

## Table of contents

1. [What is MCP?](#1-what-is-mcp)
2. [Project overview](#2-project-overview)
3. [Architecture and data flow](#3-architecture-and-data-flow)
4. [Tools, resource and prompt](#4-tools-resource-and-prompt)
5. [Project structure](#5-project-structure)
6. [Prerequisites](#6-prerequisites)
7. [Installation (Windows)](#7-installation-windows)
8. [Running the server](#8-running-the-server)
9. [Testing with MCP Inspector](#9-testing-with-mcp-inspector)
10. [Connecting an AI host (OpenCode)](#10-connecting-an-ai-host-opencode)
11. [Example inputs and outputs](#11-example-inputs-and-outputs)
12. [Running the automated tests](#12-running-the-automated-tests)
13. [Where is data stored?](#13-where-is-data-stored)
14. [Troubleshooting](#14-troubleshooting)
15. [Known limitations](#15-known-limitations)

---

## 1. What is MCP?

MCP (Model Context Protocol) is an open standard that lets an AI application talk to external programs in a structured way. Think of it like a USB port for AI:

- **Host** – the AI application you actually use (for example OpenCode, Claude Desktop, or Cursor). It contains the chat interface and the model.
- **Client** – a small connector *inside* the host. It speaks the MCP protocol to a server. You normally never interact with it directly.
- **Server** – *this project*. A program that exposes capabilities the model can use. It has no chat interface of its own.

The host and server talk over a transport. This project uses **stdio**: the host launches `server.py` as a child process and exchanges JSON-RPC messages over standard input/output. Because of that:

> **Never print normal status text to `stdout`.** `stdout` carries the MCP protocol messages. Use `stderr` for diagnostics.

A server can expose three kinds of capability:

| Kind | What it is | Who starts it |
| --- | --- | --- |
| **Tool** | An action the model can *call* (with arguments) and get a result back. | The model decides to call it. |
| **Resource** | Read-only data the model/host can *read*, like a file or a document. | The host or model reads it; it is not an "action". |
| **Prompt** | A reusable prompt *template* that the host can ask for and show to the user. | The host/user picks it; it is **not** an automatic LLM call. |

## 2. Project overview

The server stores expenses in SQLite and exposes:

- **Tools:** `add_expense`, `monthly_total`, `top_categories`
- **Resource:** `expenses://records` (all records as JSON)
- **Prompt:** `budget-summary` (a monthly spending-review template)

Money is stored as **integer paise** (1 rupee = 100 paise) so rupee amounts are exact and free of floating-point rounding errors. Rupee values are shown as e.g. `₹250.50`.

## 3. Architecture and data flow

```
   ┌──────────────────────────────────────────────┐
   │  AI Host (OpenCode / MCP Inspector)          │
   │   ┌────────────┐        ┌──────────────────┐  │
   │   │  Model     │◀──────▶│  MCP Client      │  │
   │   └────────────┘        └────────┬─────────┘  │
   └──────────────────────────────────┼────────────┘
                                       │  JSON-RPC over stdio
                                       ▼
                        ┌───────────────────────────┐
                        │  server.py  (FastMCP)      │
                        │  - tools / resource /prompt│
                        └──────────────┬────────────┘
                                       │  Python function calls
                                       ▼
                        ┌───────────────────────────┐
                        │  database.py (sqlite3)     │
                        └──────────────┬────────────┘
                                       ▼
                        data/expenses.db  (SQLite file)
```

Flow for a tool call, e.g. "Add ₹250 for lunch":

1. You ask the model in the host.
2. The model decides the `add_expense` tool fits and sends `tools/call`.
3. `server.py` validates the arguments.
4. `database.py` inserts a parameterised SQL row.
5. The saved record is returned to the model, which describes the result to you.

Splitting `server.py` (MCP-facing) from `database.py` (storage) keeps MCP concerns and SQL concerns separate and makes the database layer easy to test on its own.

## 4. Tools, resource and prompt

### Tool `add_expense(amount, category, description, expense_date=None, idempotency_key=None)`

Adds one expense and returns the saved record.

- `amount` – Rupees (₹), positive, at most 2 decimal places. Zero, negatives and non-numbers are rejected.
- `category` – Non-empty text (max 100 chars).
- `description` – Non-empty text (max 500 chars).
- `expense_date` – `YYYY-MM-DD`. **Defaults to today** if omitted.
- `idempotency_key` – Optional unique string. If the same key is sent again (an accidental repeated tool call), the **original** record is returned instead of inserting a duplicate. Omit it for genuinely different purchases that happen to look alike.

### Tool `monthly_total(year, month)`

Returns `total` (₹), `total_paise`, `expense_count` and the `year`/`month`. Returns `₹0.00` and count `0` for an empty month.

### Tool `top_categories(year, month, limit=5)`

Returns categories ranked by total spending, highest first, each with `rank`, `category`, `total`, `total_paise` and `expense_count`. `limit` is 1–50 (default 5).

### Resource `expenses://records`

A JSON document with every record (`id`, `amount`, `amount_paise`, `category`, `description`, `expense_date`, `idempotency_key`, `created_at`). Returns an empty list (`"count": 0`) when there are no records.

**Resources vs tools:** a tool is an *action the model chooses to run*; a resource is *data that can simply be read*. `expenses://records` is read-only and safe to inspect at any time.

### Prompt `budget-summary(year, month)`

A reusable template that instructs the model to (1) call `monthly_total`, (2) call `top_categories`, (3) optionally read the resource, then write a spending summary that **only uses real returned numbers**, highlights supported patterns, and says when data is insufficient. A prompt is a template the host fetches — it does not by itself run the model.

## 5. Project structure

```
MCP_project/
├── server.py            # MCP server: tools, resource, prompt, validation
├── database.py          # SQLite layer (parameterised SQL, paise storage)
├── requirements.txt     # Pinned dependencies
├── README.md            # This file
├── .gitignore
├── data/
│   └── .gitkeep         # Keeps the empty data/ folder in git
└── tests/
    ├── test_database.py # Database-layer tests
    └── test_tools.py    # Tool/validation tests
```

## 6. Prerequisites

- **Windows 10/11** (instructions are Windows-specific; the code is cross-platform).
- **Python 3.10+** (`python --version`).
- **Node.js / npx** — only for MCP Inspector (optional but used in the assignment).
- Git (optional, for pushing to GitHub).

## 7. Installation (Windows)

Open PowerShell in the project folder:

```powershell
# 1. Create a virtual environment (skip if .venv already exists)
python -m venv .venv

# 2. Activate it
.\.venv\Scripts\Activate.ps1
# If PowerShell blocks the script, run this once for the current window:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` pins `mcp>=1.9.0,<2.0.0`. **Do not upgrade to `mcp` 2.x** — this project uses the stable v1 `FastMCP` API (`from mcp.server.fastmcp import FastMCP`), whose import path and behaviour changed in 2.x.

## 8. Running the server

The server speaks stdio and is **meant to be launched by an MCP host**, not run interactively:

```powershell
.\.venv\Scripts\python.exe server.py
```

It will appear to wait silently — that is correct. It is listening for JSON-RPC on stdin. Press `Ctrl+C` to stop it.

## 9. Testing with MCP Inspector

MCP Inspector is a small web UI for talking to any MCP server. **This is a manual step** (it opens a browser and downloads a package via `npx`).

In PowerShell, launch it (use `cmd /c`, because PowerShell may block `npx.ps1`):

```powershell
cmd /c "npx -y @modelcontextprotocol/inspector"
```

In the Inspector UI that opens (usually <http://localhost:6274>):

1. Set **Transport Type** to `STDIO`.
2. **Command:**
   `C:\Users\shakthi\OneDrive\Desktop\MCP_project\.venv\Scripts\python.exe`
3. **Arguments:**
   `C:\Users\shakthi\OneDrive\Desktop\MCP_project\server.py`
4. Click **Connect**.

Then verify:

- **Tools → List Tools** shows `add_expense`, `monthly_total`, `top_categories`.
- **Tools → call `add_expense`** with, for example:
  ```json
  { "amount": 250, "category": "Food", "description": "Lunch at office canteen", "expense_date": "2026-10-18" }
  ```
  A single successful `tools/call` request is demonstrated here.
- **tools/call `monthly_total`** `{ "year": 2026, "month": 10 }` → total for that month.
- **tools/call `top_categories`** `{ "year": 2026, "month": 10 }` → ranked categories.
- **Resources → Read `expenses://records`** returns the JSON records.
- **Prompts → List Prompts** shows `budget-summary`; select it and provide `year`/`month` to **Get Prompt**.

## 10. Connecting an AI host (OpenCode)

OpenCode is MCP-compatible. Its config lives at `~/.config/opencode/opencode.jsonc`
(on Windows: `C:\Users\shakthi\.config\opencode\opencode.jsonc`). This project was
connected using the block below, **merged into** the existing config (its `$schema`
and any other keys are preserved):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "expense-tracker": {
      "type": "local",
      "command": [
        "C:\\Users\\shakthi\\OneDrive\\Desktop\\MCP_project\\.venv\\Scripts\\python.exe",
        "C:\\Users\\shakthi\\OneDrive\\Desktop\\MCP_project\\server.py"
      ],
      "enabled": true
    }
  }
}
```

Notes:

- `command` is an **array**: the interpreter first, then the server script.
- Use **absolute** paths, with doubled backslashes in JSON.
- This entry is kept in the **global** config (not committed to the repo) because the paths are specific to this machine.

After saving the config, **quit and restart OpenCode** — config is only read at startup.

Then ask natural-language questions, for example:

1. "Add an expense of ₹250 for lunch today."
2. "How much did I spend in October 2026?"
3. "Which categories account for my highest spending this month?"

The model should choose the matching tool. **Verify it actually did** by reading the database (see §13) or by watching for the tool call in the host UI.

> If a host cannot call tools in your setup (some terminals/web builds do not surface MCP tool calling), use the MCP Inspector (§9) to prove the server works — the server behaviour is identical. The Inspector and any MCP host speak the same protocol.

## 11. Example inputs and outputs

`add_expense`:

```json
{ "amount": 250.50, "category": "Food", "description": "Lunch at office canteen", "expense_date": "2026-10-05" }
```

```json
{
  "status": "created",
  "expense": {
    "id": 1,
    "amount_paise": 25050,
    "amount": "₹250.50",
    "category": "Food",
    "description": "Lunch at office canteen",
    "expense_date": "2026-10-05",
    "idempotency_key": null,
    "created_at": "2026-10-18T07:28:29+00:00"
  }
}
```

`monthly_total` `{ "year": 2026, "month": 10 }`:

```json
{ "year": 2026, "month": 10, "total": "₹1450.00", "total_paise": 145000, "expense_count": 3, "note": "" }
```

`top_categories` `{ "year": 2026, "month": 10, "limit": 5 }`:

```json
[
  { "rank": 1, "category": "Travel", "total": "₹900.00", "total_paise": 90000, "expense_count": 1 },
  { "rank": 2, "category": "Food",   "total": "₹550.00", "total_paise": 55000, "expense_count": 2 }
]
```

Invalid input is returned as a helpful **tool error**, never a crash:

```
Error executing tool monthly_total: month must be between 1 and 12, got 13
```

## 12. Running the automated tests

Tests use an isolated **temporary** SQLite database, so they never touch your real data.

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Expected (all pass):

```
9 passed
```

Coverage includes: adding/retrieving an expense, monthly totals, category ranking,
invalid-input rejection, empty-month behaviour and idempotency de-duplication.

## 13. Where is data stored?

- Default: `MCP_project\data\expenses.db` (created automatically on first run).
- Override with an environment variable, e.g.:
  ```powershell
  $env:EXPENSE_DB_PATH = "C:\temp\my_expenses.db"
  ```
- The database file is **git-ignored** (`*.db`, `data/*.db`). Never commit real expense data.

Quick look inside the database (optional):

```powershell
.\.venv\Scripts\python.exe -c "import database; print(database.list_expenses())"
```

## 14. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'mcp'` | Activate the venv and `pip install -r requirements.txt`. |
| `ImportError: cannot import name 'FastMCP'` / `mcp.server.fastmcp` errors | You have `mcp` 2.x. Run `pip install "mcp>=1.9.0,<2.0.0"`. |
| PowerShell: scripts disabled | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for the window. |
| `npx` not recognized / blocked | Use `cmd /c "npx -y @modelcontextprotocol/inspector"`; install Node.js if missing. |
| Server "hangs" when run directly | Normal — it waits for stdio messages. Launch it from a host or the Inspector. |
| Tool errors about month/year | Use `year` 2000–2100 and `month` 1–12. |
| Editor shows Python lint noise | Point VS Code at `.venv` (`Ctrl+Shift+P` → "Python: Select Interpreter"). |

## 15. Known limitations

- **Single currency (INR).** Amounts are assumed to be rupees.
- **No delete/edit tools.** The assignment does not require them; records are append-only.
- **Idempotency is opt-in.** Duplicate protection only applies when the caller supplies an `idempotency_key`.
- **`add_expense` does not reject future dates** — any valid `YYYY-MM-DD` is accepted.
- **stdio transport only.** No HTTP/SSE server is included.
- **Concurrency.** SQLite is fine for one local user; heavy concurrent writes are out of scope.
- **Host tool-calling depends on the host.** If your AI host does not expose MCP tool calling, use MCP Inspector — the protocol behaviour is the same.
