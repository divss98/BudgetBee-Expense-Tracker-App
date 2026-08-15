"""Local storage and import/export helpers for BudgetBee."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "expenses.json"
SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "settings.json"
CATEGORIES = ["Dining", "Groceries", "Transport", "Shopping", "Utilities", "Entertainment", "Other"]
CATEGORY_ALIASES = {
    "Food & Dining": "Dining",
    "Bills & Utilities": "Utilities",
    "Health": "Other",
}
FIXED_COSTS = {"Rent": 950.00, "Wi-Fi": 45.00, "Mobile bill": 35.00, "Subscriptions": 29.99}


def _starter_expenses() -> list[dict]:
    today = date.today()
    return [
        {"date": str(today - timedelta(days=1)), "category": "Dining", "description": "Lunch at Green Bowl", "amount": 14.50},
        {"date": str(today - timedelta(days=2)), "category": "Transport", "description": "Metro card top-up", "amount": 25.00},
        {"date": str(today - timedelta(days=4)), "category": "Groceries", "description": "Weekly groceries", "amount": 72.30},
        {"date": str(today - timedelta(days=6)), "category": "Entertainment", "description": "Movie night", "amount": 18.00},
        {"date": str(today - timedelta(days=9)), "category": "Utilities", "description": "Internet bill", "amount": 45.00},
        {"date": str(today - timedelta(days=12)), "category": "Dining", "description": "Coffee with a friend", "amount": 6.75},
    ]


def _ensure_data_file() -> None:
    if not DATA_PATH.exists():
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(json.dumps(_starter_expenses(), indent=2), encoding="utf-8")


def get_expenses() -> pd.DataFrame:
    _ensure_data_file()
    try:
        records = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        records = _starter_expenses()
    frame = pd.DataFrame(records, columns=["id", "date", "category", "description", "amount"])
    if frame.empty:
        return frame
    if frame["id"].isna().any():
        frame["id"] = frame["id"].fillna(pd.Series([str(uuid4()) for _ in range(len(frame))]))
        # Add stable IDs to older local data so filtered table edits cannot overwrite hidden rows.
        DATA_PATH.write_text(json.dumps(frame.to_dict("records"), default=str, indent=2), encoding="utf-8")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame["category"] = frame["category"].replace(CATEGORY_ALIASES).where(frame["category"].isin(CATEGORIES), "Other")
    return frame.dropna(subset=["date", "amount"]).sort_values("date", ascending=False).reset_index(drop=True)


def save_expenses(expenses: pd.DataFrame) -> None:
    clean = expenses.copy()
    if "id" not in clean:
        clean["id"] = [str(uuid4()) for _ in range(len(clean))]
    clean["id"] = clean["id"].fillna("").astype(str)
    clean.loc[clean["id"].str.strip() == "", "id"] = [str(uuid4()) for _ in range((clean["id"].str.strip() == "").sum())]
    clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    clean["amount"] = pd.to_numeric(clean["amount"], errors="coerce")
    clean = clean.dropna(subset=["date", "category", "description", "amount"])
    clean = clean[clean["amount"] > 0]
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(clean[["id", "date", "category", "description", "amount"]].to_dict("records"), indent=2), encoding="utf-8")


def add_expense(expense: dict) -> None:
    current = get_expenses()
    save_expenses(pd.concat([current, pd.DataFrame([expense])], ignore_index=True))


def add_expenses(expenses: list[dict]) -> None:
    """Append several parsed expenses in one write operation."""
    if expenses:
        save_expenses(pd.concat([get_expenses(), pd.DataFrame(expenses)], ignore_index=True))


def import_expenses(incoming: pd.DataFrame) -> tuple[int, int]:
    normalised = incoming.copy()
    normalised.columns = [str(column).strip().lower() for column in normalised.columns]
    required = {"date", "category", "description", "amount"}
    if not required.issubset(normalised.columns):
        return 0, len(incoming)
    normalised = normalised[["date", "category", "description", "amount"]]
    normalised["date"] = pd.to_datetime(normalised["date"], errors="coerce")
    normalised["amount"] = pd.to_numeric(normalised["amount"].astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce")
    valid = normalised.dropna(subset=["date", "category", "description", "amount"])
    valid = valid[valid["amount"] > 0]
    if not valid.empty:
        save_expenses(pd.concat([get_expenses(), valid], ignore_index=True))
    return len(valid), len(incoming) - len(valid)


def data_to_csv() -> bytes:
    frame = get_expenses().copy()
    if not frame.empty:
        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    return frame.drop(columns=["id"], errors="ignore").to_csv(index=False).encode("utf-8")


def clear_expenses() -> None:
    save_expenses(pd.DataFrame(columns=["date", "category", "description", "amount"]))


def get_monthly_budget() -> float:
    """Return the persisted monthly budget, using a welcoming default for new users."""
    try:
        settings = _get_settings()
        return float(settings.get("monthly_budget", 2000))
    except (TypeError, ValueError):
        return 2000.0


def save_monthly_budget(amount: float) -> None:
    settings = _get_settings()
    settings["monthly_budget"] = float(amount)
    _save_settings(settings)


def get_default_currency() -> str:
    currency = str(_get_settings().get("default_currency", "USD")).upper()
    return currency if currency in {"USD", "INR", "EUR", "GBP", "JPY"} else "USD"


def save_default_currency(currency: str) -> None:
    settings = _get_settings()
    settings["default_currency"] = currency.upper()
    _save_settings(settings)


def get_fixed_costs() -> dict:
    """Return persisted fixed costs, falling back to the built-in defaults."""
    settings = _get_settings()
    fixed = settings.get("fixed_costs", FIXED_COSTS)
    try:
        return {str(k): float(v) for k, v in fixed.items()}
    except Exception:
        return FIXED_COSTS.copy()


def save_fixed_costs(costs: dict) -> None:
    """Persist a mapping of fixed cost names to numeric amounts."""
    settings = _get_settings()
    settings["fixed_costs"] = {str(k): float(v) for k, v in (costs or {}).items()}
    _save_settings(settings)


def _get_settings() -> dict:
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return settings if isinstance(settings, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
