"""Natural-language expense parsing with Groq and a dependable local fallback."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta

import pandas as pd

from groq import Groq

from utils.currency import CURRENCIES, convert_amount, format_currency
from utils.data_manager import CATEGORIES


def _fallback_parse(sentence: str, default_currency: str) -> dict | None:
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
    return {
        "date": str(_relative_date(lowered)),
        "category": category,
        "description": description or "Quick expense",
        "amount": amount,
        "currency": _detect_currency(sentence, default_currency),
    }


def _detect_currency(text: str, default_currency: str) -> str:
    lowered = text.lower()
    symbols = {"₹": "INR", "€": "EUR", "£": "GBP", "¥": "JPY", "$": "USD"}
    for symbol, currency in symbols.items():
        if symbol in text:
            return currency
    names = {"usd": "USD", "dollar": "USD", "inr": "INR", "rupee": "INR", "eur": "EUR", "euro": "EUR", "gbp": "GBP", "pound": "GBP", "jpy": "JPY", "yen": "JPY"}
    return next((currency for name, currency in names.items() if name in lowered), default_currency.upper())


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


def _normalise_expense(data: dict, default_currency: str) -> dict | None:
    """Validate the structured data returned by the model before writing it locally."""
    try:
        parsed_date = datetime.strptime(str(data["date"]), "%Y-%m-%d").date()
        category = data.get("category") if data.get("category") in CATEGORIES else "Other"
        description = str(data["description"]).strip()
        amount = float(data["amount"])
        if amount <= 0 or not description:
            return None
        source_currency = str(data.get("currency", default_currency)).upper()
        if source_currency not in CURRENCIES:
            source_currency = default_currency.upper()
        converted_amount, _ = convert_amount(amount, source_currency, default_currency)
        return {"date": str(parsed_date), "category": category, "description": description, "amount": converted_amount}
    except (KeyError, TypeError, ValueError):
        return None


def _fallback_parse_many(text: str, default_currency: str) -> list[dict]:
    """Support pasted lines and semicolon-separated entries without an API key."""
    fragments = [part.strip(" •-\t") for part in re.split(r"\n+|;", text) if part.strip(" •-\t")]
    parsed_records = [parsed for fragment in fragments if (parsed := _fallback_parse(fragment, default_currency))]
    return [normalised for record in parsed_records if (normalised := _normalise_expense(record, default_currency))]


def parse_expenses(text: str, api_key: str | None, default_currency: str = "USD") -> tuple[list[dict], str]:
    """Extract one or more expenses from natural language using Groq."""
    if not api_key:
        return _fallback_parse_many(text, default_currency), "quick parser"
    prompt = f"""You are BudgetBee's careful expense parser. Extract every distinct expense from this text:
{text!r}

Today is {date.today().isoformat()}. Return ONLY valid JSON in exactly this shape:
{{"expenses": [{{"date": "YYYY-MM-DD", "category": "one allowed category", "description": "short title", "amount": 0.00, "currency": "ISO code"}}]}}
Categories must be one of: {', '.join(CATEGORIES)}. Resolve relative dates such as yesterday and last Tuesday.
Use today's date if no date is stated. Make descriptions concise title-cased summaries. Never invent amounts,
and return each expense separately even if they appear on the same line. The dashboard's default currency is {default_currency.upper()}.
Set currency to the ISO code explicitly stated in the text (USD, INR, EUR, GBP, or JPY); if no currency is stated, use {default_currency.upper()}."""
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
        return [parsed for item in records if isinstance(item, dict) and (parsed := _normalise_expense(item, default_currency))], "Groq AI"
    except Exception:
        return _fallback_parse_many(text, default_currency), "quick parser"


def parse_expense_sentence(sentence: str, api_key: str | None, default_currency: str = "USD") -> tuple[dict | None, str]:
    """Backward-compatible single-expense interface."""
    expenses, source = parse_expenses(sentence, api_key, default_currency)
    return (expenses[0] if expenses else None), source


def generate_spending_insight(expenses: pd.DataFrame, api_key: str | None, currency: str = "USD") -> tuple[str, str]:
    """Create a short analytics summary, with a useful deterministic fallback."""
    total = float(expenses["amount"].sum())
    category_totals = expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
    top_category, top_total = category_totals.index[0], float(category_totals.iloc[0])
    largest = expenses.loc[expenses["amount"].idxmax()]
    fallback = (
        f"You spent {format_currency(total, currency)} across {len(expenses)} transactions, led by {top_category} at {format_currency(top_total, currency)}. "
        f"Your largest purchase was {format_currency(float(largest['amount']), currency)} for {largest['description']} on {largest['date']:%b %d}."
    )
    if not api_key:
        return fallback, "spending highlights"
    prompt = f"""Write exactly 1-2 concise, friendly sentences about these spending facts. You MUST explicitly mention the largest transaction.
Total: {format_currency(total, currency)}; transactions: {len(expenses)}; largest category: {top_category} ({format_currency(top_total, currency)});
largest transaction: {format_currency(float(largest['amount']), currency)} for {largest['description']} on {largest['date']:%Y-%m-%d}.
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
