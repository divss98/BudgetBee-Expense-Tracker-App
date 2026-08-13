"""Natural-language expense parsing with Groq and a dependable local fallback."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta

import pandas as pd

from groq import Groq

from utils.data_manager import CATEGORIES


def _fallback_parse(sentence: str) -> dict | None:
    amount_match = re.search(r"(?:\$|₹|€|£)?\s*(\d+(?:\.\d{1,2})?)", sentence)
    if not amount_match:
        return None
    amount = float(amount_match.group(1))
    lowered = sentence.lower()
    category_map = {
        "Dining": ["lunch", "dinner", "breakfast", "coffee", "food", "restaurant", "meal"],
        "Groceries": ["grocery", "groceries", "supermarket"],
        "Transport": ["taxi", "uber", "bus", "train", "metro", "fuel", "parking"],
        "Shopping": ["shop", "clothes", "purchase", "store"],
        "Utilities": ["bill", "wifi", "internet", "mobile", "electricity", "rent"],
        "Entertainment": ["movie", "game", "concert", "netflix"],
        "Other": ["doctor", "pharmacy", "gym", "medicine"],
    }
    category = next((key for key, words in category_map.items() if any(word in lowered for word in words)), "Other")
    description = re.sub(r"(?:\$|₹|€|£)?\s*\d+(?:\.\d{1,2})?", "", sentence)
    description = re.sub(r"\b(spent|paid|bought|on|for|today|yesterday)\b", "", description, flags=re.I)
    description = re.sub(r"\s+", " ", description).strip(" .,–-").title()
    return {"date": str(_relative_date(lowered)), "category": category, "description": description or "Quick expense", "amount": amount}


def _relative_date(text: str) -> date:
    """Resolve common relative dates without requiring an LLM/API connection."""
    today = date.today()
    if "yesterday" in text:
        return today - timedelta(days=1)
    if "today" in text:
        return today
    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    match = re.search(r"last\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", text)
    if match:
        days_ago = (today.weekday() - weekdays[match.group(1)]) % 7 or 7
        return today - timedelta(days=days_ago)
    return today


def _normalise_expense(data: dict) -> dict | None:
    """Validate the structured data returned by the model before writing it locally."""
    try:
        parsed_date = datetime.strptime(str(data["date"]), "%Y-%m-%d").date()
        category = data.get("category") if data.get("category") in CATEGORIES else "Other"
        description = str(data["description"]).strip()
        amount = float(data["amount"])
        if amount <= 0 or not description:
            return None
        return {"date": str(parsed_date), "category": category, "description": description, "amount": amount}
    except (KeyError, TypeError, ValueError):
        return None


def _fallback_parse_many(text: str) -> list[dict]:
    """Support pasted lines and semicolon-separated entries without an API key."""
    fragments = [part.strip(" •-\t") for part in re.split(r"\n+|;", text) if part.strip(" •-\t")]
    return [parsed for fragment in fragments if (parsed := _fallback_parse(fragment))]


def parse_expenses(text: str, api_key: str | None) -> tuple[list[dict], str]:
    """Extract one or more expenses from natural language using Groq."""
    if not api_key:
        return _fallback_parse_many(text), "quick parser"
    prompt = f"""You are BudgetBee's careful expense parser. Extract every distinct expense from this text:
{text!r}

Today is {date.today().isoformat()}. Return ONLY valid JSON in exactly this shape:
{{"expenses": [{{"date": "YYYY-MM-DD", "category": "one allowed category", "description": "short title", "amount": 0.00}}]}}
Categories must be one of: {', '.join(CATEGORIES)}. Resolve relative dates such as yesterday and last Tuesday.
Use today's date if no date is stated. Make descriptions concise title-cased summaries. Never invent amounts,
and return each expense separately even if they appear on the same line."""
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content or "{}")
        records = data.get("expenses", [])
        if not isinstance(records, list):
            records = []
        return [parsed for item in records if isinstance(item, dict) and (parsed := _normalise_expense(item))], "Groq AI"
    except Exception:
        return _fallback_parse_many(text), "quick parser"


def parse_expense_sentence(sentence: str, api_key: str | None) -> tuple[dict | None, str]:
    """Backward-compatible single-expense interface."""
    expenses, source = parse_expenses(sentence, api_key)
    return (expenses[0] if expenses else None), source


def generate_spending_insight(expenses: pd.DataFrame, api_key: str | None) -> tuple[str, str]:
    """Create a short analytics summary, with a useful deterministic fallback."""
    total = float(expenses["amount"].sum())
    category_totals = expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
    top_category, top_total = category_totals.index[0], float(category_totals.iloc[0])
    largest = expenses.loc[expenses["amount"].idxmax()]
    fallback = (
        f"You spent ${total:,.2f} across {len(expenses)} transactions, led by {top_category} at ${top_total:,.2f}. "
        f"Your largest purchase was ${float(largest['amount']):,.2f} for {largest['description']} on {largest['date']:%b %d}."
    )
    if not api_key:
        return fallback, "spending highlights"
    prompt = f"""Write exactly 1-2 concise, friendly sentences about these spending facts. You MUST explicitly mention the largest transaction.
Total: ${total:.2f}; transactions: {len(expenses)}; largest category: {top_category} (${top_total:.2f});
largest transaction: ${float(largest['amount']):.2f} for {largest['description']} on {largest['date']:%Y-%m-%d}.
Do not make recommendations or add facts."""
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=100,
        )
        summary = (response.choices[0].message.content or "").strip()
        return (summary or fallback), "Groq AI highlights"
    except Exception:
        return fallback, "spending highlights"
