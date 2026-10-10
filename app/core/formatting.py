"""Display strings for figures. The frontend shows these verbatim and never formats numbers itself.

Conventions (design/DESIGN.md "Number & language formatting"):
- money in kUZS (thousand UZS, as printed) or UZS → mln UZS, 1 decimal, space thousands, true minus sign
- ratio → 2 decimals; pct facts are stored in percent (6.0 → "6.0%"), as in app/pipeline/compute.py;
  days/count → integers
"""
from decimal import Decimal

MINUS = "−"


def _group(int_part: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return " ".join(out)


def fmt_number(value: float | Decimal | None, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    v = float(value)
    text = f"{abs(v):.{decimals}f}"
    if decimals:
        int_part, frac = text.split(".")
        body = f"{_group(int_part)}.{frac}"
    else:
        body = _group(text)
    is_zero = float(text.replace(" ", "")) == 0
    return f"{MINUS}{body}" if v < 0 and not is_zero else body


def kuzs_to_mln(value: float | Decimal | None) -> str:
    return fmt_number(None if value is None else float(value) / 1000.0, 1)


def kuzs_to_bn(value: float | Decimal | None) -> str:
    return fmt_number(None if value is None else float(value) / 1_000_000.0, 1)


def fmt_pct(fraction: float | None, decimals: int = 1, signed: bool = False) -> str:
    if fraction is None:
        return "n/a"
    body = fmt_number(fraction * 100.0, decimals)
    if signed and fraction > 0:
        body = "+" + body
    return body + "%"


def display_for(value: float | Decimal | None, unit: str) -> tuple[str, str]:
    """Returns (display, display_unit) for a fact value in its canonical unit."""
    if value is None:
        return "n/a", ""
    v = float(value)
    if unit == "kUZS":
        return kuzs_to_mln(v), "mln UZS"
    if unit == "UZS":
        return fmt_number(v / 1_000_000.0, 1), "mln UZS"
    if unit == "ratio":
        return fmt_number(v, 2), ""
    if unit == "pct":
        return fmt_number(v, 1) + "%", ""
    if unit == "days":
        return fmt_number(v, 0), "days"
    if unit == "count":
        return fmt_number(v, 0), ""
    return fmt_number(v, 2), unit
