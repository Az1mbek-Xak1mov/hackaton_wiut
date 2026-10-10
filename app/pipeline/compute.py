"""Fact utilities shared by rules, ratios, monitoring, the verifier and the CFO `compute` tool.

- `new_fact_key()`      short citable id `f_xxxxxx`
- `format_display()`    the one place a fact value is turned into the string the UI and the LLM see
- `compute()`           safe arithmetic over fact values -> a citable computed FactDraft.
                        This is the ONLY way the language model obtains a new number.
"""
from __future__ import annotations

import ast
import math
import secrets
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

from app.pipeline.types import FactDraft

MONEY_UNITS = {"kUZS", "UZS"}
_KEY_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
MINUS = "−"


class ComputeError(ValueError):
    """Expression is malformed, uses an unknown fact, mixes units or divides by zero."""


def new_fact_key() -> str:
    return "f_" + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(6))


def ensure_key(fact: FactDraft) -> FactDraft:
    if not fact.key:
        fact.key = new_fact_key()
    return fact


def to_kuzs(value: float, unit: str) -> float:
    return value / 1000.0 if unit == "UZS" else value


# ---------------------------------------------------------------- formatting

def _group(int_text: str) -> str:
    out = []
    while len(int_text) > 3:
        out.insert(0, int_text[-3:])
        int_text = int_text[:-3]
    out.insert(0, int_text)
    return " ".join(out)


def format_number(value: float, decimals: int, signed: bool = False) -> str:
    """9842.3 -> '9 842.3'; -27 -> '−27.0' (true minus); signed adds '+' for positives."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    quant = Decimal(1).scaleb(-decimals)
    rounded = Decimal(repr(abs(float(value)))).quantize(quant, rounding=ROUND_HALF_UP)
    text = f"{rounded:.{decimals}f}"
    int_part, _, frac = text.partition(".")
    body = _group(int_part) + (("." + frac) if decimals > 0 else "")
    if value < 0 and rounded != 0:
        return MINUS + body
    if signed and value > 0 and rounded != 0:
        return "+" + body
    return body


def format_display(value: float, unit: str, signed: bool = False, money_scale: str = "mln") -> tuple[str, str]:
    """Returns (display, display_unit) exactly as rendered in the UI and sent to the LLM.

    kUZS/UZS -> mln UZS, 1 decimal ("9 842.3", "mln UZS"); money_scale="bn" -> bn UZS, 1 decimal
    ratio -> 2 decimals ("1.48"); pct -> 1 decimal with % ("6.0%"); days/count -> integer.
    """
    if unit in MONEY_UNITS:
        k = to_kuzs(value, unit)
        if money_scale == "bn":
            return format_number(k / 1_000_000.0, 1, signed), "bn UZS"
        return format_number(k / 1000.0, 1, signed), "mln UZS"
    if unit == "ratio":
        return format_number(value, 2, signed), ""
    if unit == "pct":
        return format_number(value, 1, signed) + "%", ""
    if unit == "days":
        return format_number(value, 0, signed), "days"
    if unit == "count":
        decimals = 0 if abs(value - round(value)) < 1e-9 else 1
        return format_number(value, decimals, signed), ""
    return format_number(value, 2, signed), unit


def fact_display(fact: FactDraft) -> tuple[str, str]:
    signed = fact.unit == "pct" and ".change" in fact.field
    return format_display(fact.value, fact.unit, signed=signed)


def display_with_unit(fact: FactDraft) -> str:
    d, u = fact_display(fact)
    return f"{d} {u}".strip()


# ---------------------------------------------------------------- safe arithmetic

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)
_MAX_EXPR_LEN = 500
_MAX_NODES = 120


def _check_tree(tree: ast.AST) -> None:
    n = 0
    for node in ast.walk(tree):
        n += 1
        if n > _MAX_NODES:
            raise ComputeError("expression too long")
        if isinstance(node, (ast.Expression, ast.Load)):
            continue
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINOPS):
                raise ComputeError(f"operator {type(node.op).__name__} is not allowed")
            continue
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARY):
                raise ComputeError(f"operator {type(node.op).__name__} is not allowed")
            continue
        if isinstance(node, (ast.operator, ast.unaryop)):
            continue
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ComputeError("only numeric constants are allowed")
            continue
        if isinstance(node, ast.Name):
            continue
        raise ComputeError(f"{type(node).__name__} is not allowed in an expression")


def _parse(expression: str) -> ast.Expression:
    if not isinstance(expression, str) or not expression.strip():
        raise ComputeError("empty expression")
    if len(expression) > _MAX_EXPR_LEN:
        raise ComputeError("expression too long")
    expr = expression.replace("×", "*").replace("÷", "/").replace(MINUS, "-")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ComputeError(f"cannot parse expression: {exc.msg}") from exc
    _check_tree(tree)
    return tree


def _names(tree: ast.AST) -> list[str]:
    seen: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in seen:
            seen.append(node.id)
    return seen


def _eval(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ComputeError(f"unknown fact {node.id}")
        return float(values[node.id])
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, values)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a = _eval(node.left, values)
        b = _eval(node.right, values)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if b == 0:
            raise ComputeError("division by zero")
        return a / b
    raise ComputeError(f"{type(node).__name__} is not allowed")


def evaluate(expression: str, values: dict[str, float]) -> float:
    """Safe evaluation of + − × ÷ and parentheses over named values."""
    tree = _parse(expression)
    result = _eval(tree, values)
    if math.isnan(result) or math.isinf(result):
        raise ComputeError("result is not a finite number")
    return result


def _dimension(node: ast.AST, units: dict[str, str]) -> int:
    """Money dimension: kUZS = 1, dimensionless = 0. +/− need equal dimensions."""
    if isinstance(node, ast.Expression):
        return _dimension(node.body, units)
    if isinstance(node, ast.Constant):
        return 0
    if isinstance(node, ast.Name):
        return 1 if units.get(node.id) in MONEY_UNITS else 0
    if isinstance(node, ast.UnaryOp):
        return _dimension(node.operand, units)
    if isinstance(node, ast.BinOp):
        a = _dimension(node.left, units)
        b = _dimension(node.right, units)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if a != b:
                raise ComputeError("cannot add or subtract money and non-money values")
            return a
        if isinstance(node.op, ast.Mult):
            return a + b
        return a - b
    raise ComputeError(f"{type(node).__name__} is not allowed")


def render_formula(expression: str, facts: dict[str, FactDraft]) -> str:
    """'f_a / f_b' -> '2 870.4 ÷ 1 940.2' using each fact's display string."""
    tree = _parse(expression)

    def r(node: ast.AST, parent_prec: int = 0) -> str:
        if isinstance(node, ast.Expression):
            return r(node.body)
        if isinstance(node, ast.Constant):
            v = float(node.value)
            return format_number(v, 0 if v == int(v) else 2)
        if isinstance(node, ast.Name):
            f = facts.get(node.id)
            return fact_display(f)[0] if f else node.id
        if isinstance(node, ast.UnaryOp):
            inner = r(node.operand, 3)
            return (MINUS + inner) if isinstance(node.op, ast.USub) else inner
        if isinstance(node, ast.BinOp):
            prec = 1 if isinstance(node.op, (ast.Add, ast.Sub)) else 2
            sym = {ast.Add: "+", ast.Sub: MINUS, ast.Mult: "×", ast.Div: "÷"}[type(node.op)]
            text = f"{r(node.left, prec)} {sym} {r(node.right, prec + 1)}"
            return f"({text})" if prec < parent_prec else text
        return "?"

    return r(tree)


def compute(
    expression: str,
    facts: dict[str, FactDraft],
    label: str = "",
    unit: str | None = None,
    field: str | None = None,
    period_label: str = "",
    note: str = "",
) -> FactDraft:
    """Evaluate `expression` whose names are fact keys and return a new computed FactDraft
    (with its own key, formula and inputs) so the result is itself citable."""
    tree = _parse(expression)
    names = _names(tree)
    missing = [n for n in names if n not in facts]
    if missing:
        raise ComputeError(f"unknown fact {', '.join(missing)}")
    units = {n: facts[n].unit for n in names}
    values = {n: to_kuzs(facts[n].value, facts[n].unit) for n in names}
    value = _eval(tree, values)
    if math.isnan(value) or math.isinf(value):
        raise ComputeError("result is not a finite number")
    if unit is None:
        dim = _dimension(tree, units)
        if dim == 1:
            unit = "kUZS"
        elif dim == 0:
            others = {u for u in units.values() if u not in MONEY_UNITS}
            has_money = any(u in MONEY_UNITS for u in units.values())
            unit = others.pop() if (len(others) == 1 and not has_money) else "ratio"
        else:
            raise ComputeError("result has an unsupported unit (money squared)")
    periods = {facts[n].period_label for n in names if facts[n].period_label}
    if not period_label and len(periods) == 1:
        period_label = periods.pop()
    return FactDraft(
        field=field or "computed.expression",
        label=label or expression,
        value=value,
        unit=unit,
        kind="computed",
        period_label=period_label,
        confidence=min([facts[n].confidence for n in names] or [1.0]),
        method="compute",
        formula=expression.strip(),
        inputs=names,
        note=note or render_formula(expression, facts),
        key=new_fact_key(),
    )


def computed_fact(
    field: str,
    label: str,
    expression: str,
    facts: dict[str, FactDraft],
    unit: str | None = None,
    period_label: str = "",
    note: str = "",
) -> FactDraft:
    """Convenience wrapper used by rules/ratios: same as compute() with a canonical field."""
    return compute(expression, facts, label=label, unit=unit, field=field, period_label=period_label, note=note)


def constant_fact(field: str, label: str, value: float, unit: str, *, formula: str = "", inputs: list[str] | None = None,
                  period_label: str = "", note: str = "", method: str = "rule", kind: str = "computed") -> FactDraft:
    """A computed fact whose value comes from declared inputs (e.g. the application form) rather than
    from other facts. `formula`/`note` must say where it came from."""
    return FactDraft(field=field, label=label, value=float(value), unit=unit, kind=kind, period_label=period_label,
                     method=method, formula=formula, inputs=list(inputs or []), note=note, key=new_fact_key())


def with_key(fact: FactDraft) -> FactDraft:
    """Copy with a fresh key (used when a draft is reused in another context)."""
    return replace(fact, key=new_fact_key())
