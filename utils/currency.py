"""Currency metadata and current-rate conversion helpers."""

from __future__ import annotations

import time
from decimal import Decimal, ROUND_HALF_UP

import requests


CURRENCIES = {
    "USD": {"label": "US Dollar (USD)", "symbol": "$", "decimals": 2},
    "INR": {"label": "Indian Rupee (INR)", "symbol": "₹", "decimals": 2},
    "EUR": {"label": "Euro (EUR)", "symbol": "€", "decimals": 2},
    "GBP": {"label": "British Pound (GBP)", "symbol": "£", "decimals": 2},
    "JPY": {"label": "Japanese Yen (JPY)", "symbol": "¥", "decimals": 0},
}
RATE_CACHE_SECONDS = 60 * 60
_rate_cache: dict[tuple[str, str], tuple[float, str, float]] = {}


class CurrencyConversionError(RuntimeError):
    """Raised when a current exchange rate cannot be retrieved."""


def get_exchange_rate(base: str, quote: str) -> tuple[float, str]:
    """Fetch the latest published rate, caching each pair for one hour."""
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return 1.0, "same currency"
    cached = _rate_cache.get((base, quote))
    if cached and time.time() - cached[2] < RATE_CACHE_SECONDS:
        return cached[0], cached[1]
    try:
        response = requests.get(f"https://api.frankfurter.dev/v2/rate/{base}/{quote}", timeout=10)
        response.raise_for_status()
        data = response.json()
        rate, rate_date = float(data["rate"]), str(data["date"])
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise CurrencyConversionError("Couldn't retrieve the latest exchange rate. Please try again.") from exc
    _rate_cache[(base, quote)] = (rate, rate_date, time.time())
    return rate, rate_date


def convert_amount(amount: float, base: str, quote: str) -> tuple[float, str]:
    """Convert an amount using the latest available rate for the selected pair."""
    rate, rate_date = get_exchange_rate(base, quote)
    decimals = CURRENCIES.get(quote.upper(), CURRENCIES["USD"])["decimals"]
    quantizer = Decimal("1") if decimals == 0 else Decimal("0.01")
    result = (Decimal(str(amount)) * Decimal(str(rate))).quantize(quantizer, rounding=ROUND_HALF_UP)
    return float(result), rate_date


def format_currency(amount: float, currency: str) -> str:
    metadata = CURRENCIES.get(currency, CURRENCIES["USD"])
    return f"{metadata['symbol']}{amount:,.{metadata['decimals']}f}"


def number_format(currency: str) -> str:
    metadata = CURRENCIES.get(currency, CURRENCIES["USD"])
    return f"{metadata['symbol']}%.{metadata['decimals']}f"
