"""Lookup of statutory and statement facts by (form, code, period)."""
from __future__ import annotations

from collections import defaultdict

from app.pipeline.compute import ensure_key
from app.pipeline.rules.periods import Period, parse_period
from app.pipeline.types import FactDraft

STAT_FORMS = ("form1", "form2")
_STATUS_RANK = {"corrected": 3, "verified": 2, "auto": 1, "": 1, "flagged": 0}


def stat_parts(field: str) -> tuple[str, str] | None:
    parts = (field or "").split(".")
    if len(parts) >= 2 and parts[0] in STAT_FORMS and parts[1].isdigit():
        return parts[0], parts[1].zfill(3)
    return None


def _rank(f: FactDraft) -> tuple:
    status = getattr(f, "status", "auto") or "auto"
    return (_STATUS_RANK.get(status, 1), f.confidence)


class FactIndex:
    def __init__(self, facts: list[FactDraft]):
        self.facts = [ensure_key(f) for f in facts]
        self.by_key: dict[str, FactDraft] = {f.key: f for f in self.facts}
        self._stat: dict[tuple[str, str], dict[str, list[FactDraft]]] = defaultdict(lambda: defaultdict(list))
        self._periods: dict[str, Period] = {}
        self.by_field: dict[str, list[FactDraft]] = defaultdict(list)
        for f in self.facts:
            self.by_field[f.field].append(f)
            sp = stat_parts(f.field)
            if sp:
                p = self.period(f.period_label)
                self._stat[sp][p.key].append(f)

    def period(self, label: str) -> Period:
        if label not in self._periods:
            self._periods[label] = parse_period(label)
        return self._periods[label]

    # ---- statutory facts
    def stat(self, form: str, code: str, period: str | Period | None = None) -> FactDraft | None:
        by_p = self._stat.get((form, code))
        if not by_p:
            return None
        if period is None:
            p = self.latest_period(form, code)
            return self.stat(form, code, p) if p else None
        key = period.key if isinstance(period, Period) else self.period(period).key
        cands = by_p.get(key) or []
        return max(cands, key=_rank) if cands else None

    def stat_all(self, form: str, code: str, period: str | Period) -> list[FactDraft]:
        key = period.key if isinstance(period, Period) else self.period(period).key
        return list(self._stat.get((form, code), {}).get(key, []))

    def periods_for(self, form: str, code: str, kind: str | None = None) -> list[Period]:
        ps = [self.period_from_key(k) for k in self._stat.get((form, code), {})]
        if kind:
            ps = [p for p in ps if p.kind == kind]
        return sorted(ps, key=lambda p: p.sort_key())

    def period_from_key(self, key: str) -> Period:
        return self.period(key)

    def latest_period(self, form: str, code: str, kind: str | None = None) -> Period | None:
        ps = self.periods_for(form, code, kind)
        return ps[-1] if ps else None

    def form_periods(self, form: str, kind: str | None = None) -> list[Period]:
        keys = set()
        for (fm, _code), by_p in self._stat.items():
            if fm == form:
                keys.update(by_p.keys())
        ps = [self.period(k) for k in keys]
        if kind:
            ps = [p for p in ps if p.kind == kind]
        return sorted(ps, key=lambda p: p.sort_key())

    def has_form(self, form: str) -> bool:
        return any(fm == form for (fm, _c) in self._stat)

    # ---- statement / application facts
    def field(self, field: str) -> FactDraft | None:
        cands = self.by_field.get(field) or []
        return max(cands, key=_rank) if cands else None

    def prefix(self, prefix: str) -> list[FactDraft]:
        return [f for f in self.facts if f.field.startswith(prefix)]

    def add(self, fact: FactDraft) -> FactDraft:
        ensure_key(fact)
        self.facts.append(fact)
        self.by_key[fact.key] = fact
        self.by_field[fact.field].append(fact)
        sp = stat_parts(fact.field)
        if sp:
            self._stat[sp][self.period(fact.period_label).key].append(fact)
        return fact
