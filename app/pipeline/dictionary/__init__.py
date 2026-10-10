"""Line-code dictionary for Uzbek statutory Form 1 / Form 2 (see forms.yaml header).

Look entries up by slug (stable meaning) rather than by code:
    by_slug("form2", "net_revenue").code  -> "010"
    field_for("form1", "total_assets")    -> "form1.400.total_assets"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

import yaml

_DIR = Path(__file__).resolve().parent
LANGS = ("uz_latn", "uz_cyrl", "ru", "en")


@dataclass(frozen=True)
class Entry:
    form: str
    code: str
    slug: str
    section: str
    side: str
    kind: str                         # amount | total | result
    labels: Mapping[str, tuple[str, ...]]
    sum_of: tuple[str, ...] = ()      # exhaustive, "-" prefix subtracts
    parts: tuple[str, ...] = ()       # non-exhaustive "of which"

    @property
    def field(self) -> str:
        return f"{self.form}.{self.code}.{self.slug}"

    @property
    def label_en(self) -> str:
        return (self.labels.get("en") or (self.slug.replace("_", " ").capitalize(),))[0]

    def label(self, lang: str = "en") -> str:
        vals = self.labels.get(lang) or self.labels.get("en") or (self.slug,)
        return vals[0]

    def all_labels(self) -> list[str]:
        out: list[str] = []
        for lang in LANGS:
            out.extend(self.labels.get(lang, ()))
        return out

    def terms(self) -> list[tuple[int, str]]:
        """sum_of as (sign, code) pairs."""
        res = []
        for t in self.sum_of:
            t = str(t)
            if t.startswith("-"):
                res.append((-1, t[1:]))
            else:
                res.append((1, t.lstrip("+")))
        return res


@dataclass(frozen=True)
class Forms:
    meta: Mapping
    entries: tuple[Entry, ...]
    _by_code: Mapping[tuple[str, str], Entry] = field(default_factory=dict)
    _by_slug: Mapping[tuple[str, str], Entry] = field(default_factory=dict)


@lru_cache(maxsize=1)
def _load() -> Forms:
    raw = yaml.safe_load((_DIR / "forms.yaml").read_text(encoding="utf-8"))
    entries = []
    for e in raw["entries"]:
        entries.append(Entry(
            form=e["form"], code=str(e["code"]).zfill(3), slug=e["slug"], section=e.get("section", ""),
            side=e.get("side", ""), kind=e.get("kind", "amount"),
            labels={k: tuple(v) for k, v in (e.get("labels") or {}).items()},
            sum_of=tuple(str(x) for x in e.get("sum_of", []) or []),
            parts=tuple(str(x) for x in e.get("parts", []) or []),
        ))
    by_code = {(e.form, e.code): e for e in entries}
    by_slug = {(e.form, e.slug): e for e in entries}
    if len(by_code) != len(entries) or len(by_slug) != len(entries):
        raise ValueError("forms.yaml: duplicate code or slug")
    return Forms(meta=raw.get("meta", {}), entries=tuple(entries), _by_code=by_code, _by_slug=by_slug)


def load_forms() -> list[Entry]:
    return list(_load().entries)


def meta() -> Mapping:
    return _load().meta


def entries(form: str) -> list[Entry]:
    return [e for e in _load().entries if e.form == form]


def by_code(form: str, code: str) -> Entry | None:
    return _load()._by_code.get((form, str(code).zfill(3)))


def by_slug(form: str, slug: str) -> Entry | None:
    return _load()._by_slug.get((form, slug))


def code_for(form: str, slug: str) -> str:
    e = by_slug(form, slug)
    if e is None:
        raise KeyError(f"{form}.{slug}")
    return e.code


def field_for(form: str, slug: str) -> str:
    return f"{form}.{code_for(form, slug)}.{slug}"


def codes(form: str) -> set[str]:
    return {e.code for e in entries(form)}


def evaluate_sum(entry: Entry, values: Mapping[str, float]) -> float | None:
    """Σ of entry.sum_of over `values` (code -> value). None if any term is missing or there is no formula."""
    if not entry.sum_of:
        return None
    total = 0.0
    for sign, code in entry.terms():
        if code not in values or values[code] is None:
            return None
        total += sign * float(values[code])
    return total


def check_sums(form: str, values: Mapping[str, float], tol: float = 1.0) -> list[dict]:
    """All sum_of relations of `form` that can be evaluated: [{code, expected, actual, ok, terms}]."""
    out = []
    for e in entries(form):
        if not e.sum_of or e.code not in values or values[e.code] is None:
            continue
        exp = evaluate_sum(e, values)
        if exp is None:
            continue
        out.append({"code": e.code, "slug": e.slug, "expected": exp, "actual": float(values[e.code]),
                    "ok": abs(exp - float(values[e.code])) <= tol, "terms": list(e.sum_of)})
    return out


def iter_labels(form: str | None = None) -> Iterable[tuple[Entry, str, str]]:
    """(entry, lang, label) for all labels."""
    for e in _load().entries:
        if form and e.form != form:
            continue
        for lang in LANGS:
            for lab in e.labels.get(lang, ()):
                yield e, lang, lab


@lru_cache(maxsize=1)
def application_fields() -> dict:
    """Label synonyms for loan-application fields (shared with the data generator)."""
    return yaml.safe_load((_DIR / "application.yaml").read_text(encoding="utf-8"))
