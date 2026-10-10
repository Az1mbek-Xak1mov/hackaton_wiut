"""Financial model: monthly P&L -> Form 2 per period, balances -> Form 1 per date (all kUZS ints).

Form 1 balances by construction (cash plug, overdraft if the plug goes negative) and retained
earnings roll forward exactly by net profit, so R01-R04 hold unless a contradiction is planted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .company import INDUSTRIES, Company
from .spec import check_sums

MONTHS = [(y, m) for y in (2024, 2025, 2026) for m in range(1, 13)][: 12 * 2 + 9]  # 2024-01 .. 2026-09
TAX_RATE = 0.15

PERIODS = {
    "FY2024": [(2024, m) for m in range(1, 13)],
    "FY2025": [(2025, m) for m in range(1, 13)],
    "H1-2025": [(2025, m) for m in range(1, 7)],
    "H1-2026": [(2026, m) for m in range(1, 7)],
    "Q4-2025": [(2025, m) for m in (10, 11, 12)],
    "Q1-2026": [(2026, m) for m in (1, 2, 3)],
    "Q2-2026": [(2026, m) for m in (4, 5, 6)],
    "Q3-2026": [(2026, m) for m in (7, 8, 9)],
    "Q3-2025": [(2025, m) for m in (7, 8, 9)],
    "Q1-2025": [(2025, m) for m in (1, 2, 3)],
    "Q2-2025": [(2025, m) for m in (4, 5, 6)],
}
DATES = ["2024-12-31", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]


def month_end(y: int, m: int) -> date:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


@dataclass
class Loan:
    contract: str
    lender: str
    principal: int          # UZS
    rate_annual: float
    term_months: int
    first_due: date
    due_day: int
    declared: bool = True
    long_term: bool = True

    @property
    def installment(self) -> int:
        r = self.rate_annual / 12
        return int(round(self.principal * r / (1 - (1 + r) ** -self.term_months)))

    def schedule(self) -> list[tuple[date, int, int, int]]:
        """[(due_date, principal_part, interest_part, balance_after)] in UZS."""
        r = self.rate_annual / 12
        bal = self.principal
        out = []
        y, m = self.first_due.year, self.first_due.month
        inst = self.installment
        for i in range(self.term_months):
            interest = int(round(bal * r))
            princ = inst - interest if i < self.term_months - 1 else bal
            bal -= princ
            d = date(y, m, min(self.due_day, 28))
            out.append((d, princ, interest, bal))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return out

    def balance_at(self, d: date) -> int:
        bal = self.principal
        for due, princ, _i, after in self.schedule():
            if due <= d:
                bal = after
        return bal

    def interest_in_month(self, y: int, m: int) -> int:
        return sum(i for due, _p, i, _a in self.schedule() if due.year == y and due.month == m)


@dataclass
class Fin:
    company: Company
    monthly: dict[tuple[int, int], dict[str, int]]
    f2: dict[str, dict[str, int | None]]
    f1: dict[str, dict[str, int | None]]
    loans: list[Loan]
    params: dict = field(default_factory=dict)

    def month(self, y: int, m: int) -> dict[str, int]:
        return self.monthly[(y, m)]


MANUFACTURING = {"textile", "furniture", "bakery", "dairy", "plastics", "metal", "printing", "oil"}


def split_inventory(total: int, rng: np.random.Generator, industry_key: str) -> dict[str, int]:
    if industry_key in MANUFACTURING:
        w = np.array([rng.uniform(0.45, 0.6), rng.uniform(0.05, 0.15), rng.uniform(0.25, 0.45), rng.uniform(0.0, 0.05)])
    else:
        w = np.array([rng.uniform(0.03, 0.2), 0.0, 0.0, rng.uniform(0.7, 0.95)])
    w = w / w.sum()
    parts = [int(round(total * x)) for x in w]
    parts[int(np.argmax(w))] += total - sum(parts)
    return dict(zip(("150", "160", "170", "180"), parts))


def complete_f1(v: dict, rng: np.random.Generator, industry_key: str) -> dict:
    """Fill dictionary codes the model does not drive (zeros, 140 children)."""
    for c in ("120", "200", "440", "460", "580", "740", "750"):
        v.setdefault(c, 0)
    if "150" not in v:
        v.update(split_inventory(v["140"], rng, industry_key))
    return v


def complete_f2(v: dict) -> dict:
    for c in ("140", "150", "160", "190", "200", "210"):
        v.setdefault(c, 0)
    return v


def _f2_from_months(monthly, months) -> dict[str, int | None]:
    agg = {k: sum(monthly[mm][k] for mm in months) for k in monthly[months[0]]}
    v: dict[str, int | None] = {}
    v["010"] = agg["rev"]
    v["020"] = agg["cogs"]
    v["030"] = v["010"] - v["020"]
    v["050"], v["060"], v["070"] = agg["sell"], agg["admin"], agg["other_opex"]
    v["040"] = v["050"] + v["060"] + v["070"]
    v["090"] = agg["other_inc"]
    v["100"] = v["030"] - v["040"] + v["090"]
    v["120"] = 0
    v["130"] = agg["int_inc"]
    v["110"] = v["120"] + v["130"]
    v["180"] = agg["int_exp"]
    v["170"] = v["180"]
    v["220"] = v["100"] + v["110"] - v["170"]
    v["230"] = 0
    v["240"] = v["220"] + v["230"]
    v["250"] = agg["tax"]
    v["260"] = 0
    v["270"] = v["240"] - v["250"] - v["260"]
    return complete_f2(v)


def _quarter_taxes(monthly):
    """Profit tax booked per quarter (15% of positive quarterly PBT), allocated to the last month."""
    for y in (2024, 2025, 2026):
        for q in range(4):
            ms = [(y, m) for m in range(3 * q + 1, 3 * q + 4) if (y, m) in monthly]
            if len(ms) < 3:
                continue
            pbt = sum(monthly[mm]["rev"] - monthly[mm]["cogs"] - monthly[mm]["sell"] - monthly[mm]["admin"]
                      - monthly[mm]["other_opex"] + monthly[mm]["other_inc"] + monthly[mm]["int_inc"]
                      - monthly[mm]["int_exp"] for mm in ms)
            tax = int(round(max(pbt, 0) * TAX_RATE))
            for mm in ms:
                monthly[mm]["tax"] = 0
            monthly[ms[-1]]["tax"] = tax


def make_fin(rng: np.random.Generator, company: Company, *, annual_rev: float | None = None,
             growth: float | None = None, loans: list[Loan] | None = None,
             q3_shock: float = 0.0, cash_months: float | None = None) -> Fin:
    """Simulate 2024-01..2026-09. `q3_shock` multiplies Q3-2026 revenue (e.g. -0.28)."""
    _prod, _ind, cogs_rng, opex_rng = INDUSTRIES[company.industry_key]
    annual = annual_rev or float(np.exp(rng.normal(np.log(6.0e6), 0.75)))   # kUZS (6 bn UZS median)
    annual = float(np.clip(annual, 1.2e6, 45e6))
    g = growth if growth is not None else float(rng.normal(0.09, 0.08))
    amp = float(rng.uniform(0.02, 0.15))
    phase = float(rng.uniform(0, 12))
    c_share = float(rng.uniform(*cogs_rng))
    ebit_margin = float(rng.uniform(0.025, 0.12))
    o_share = max(0.03, 1.0 - c_share - ebit_margin)
    fixed_opex_share = float(rng.uniform(0.35, 0.65))
    loans = loans or []
    base = annual / 12 / (1 + g) ** 0.5
    monthly: dict[tuple[int, int], dict[str, int]] = {}
    for i, (y, m) in enumerate(MONTHS):
        trend = (1 + g) ** (i / 12)
        season = 1 + amp * math.sin(2 * math.pi * (m + phase) / 12)
        noise = float(rng.normal(1.0, 0.035))
        rev = base * trend * season * noise
        if (y, m) in PERIODS["Q3-2026"]:
            rev *= 1 + q3_shock
        rev_i = int(round(rev))
        cogs = int(round(rev * c_share * float(rng.normal(1.0, 0.015))))
        fixed = base * o_share * fixed_opex_share * (1 + g) ** (i / 24)
        opex = fixed + rev * o_share * (1 - fixed_opex_share)
        sell = int(round(opex * 0.38))
        admin = int(round(opex * 0.52))
        other_opex = int(round(opex)) - sell - admin
        other_inc = int(round(rev * float(rng.uniform(0.0, 0.012))))
        int_inc = int(round(float(rng.uniform(0, 0.0015)) * rev))
        int_exp = int(round(sum(ln.interest_in_month(y, m) for ln in loans) / 1000))
        monthly[(y, m)] = dict(rev=rev_i, cogs=cogs, sell=sell, admin=admin, other_opex=other_opex,
                               other_inc=other_inc, int_inc=int_inc, int_exp=int_exp, tax=0)
    _quarter_taxes(monthly)
    f2 = {p: _f2_from_months(monthly, ms) for p, ms in PERIODS.items()}

    # ---------------- balance sheets ----------------
    ar_days = float(rng.uniform(18, 55))
    inv_days = float(rng.uniform(20, 75))
    ap_days = float(rng.uniform(15, 50))
    fa_gross0 = annual * float(rng.uniform(0.12, 0.6))
    dep_rate = float(rng.uniform(0.06, 0.12))
    capex_m = fa_gross0 * float(rng.uniform(0.003, 0.012))
    charter = int(round(annual * float(rng.uniform(0.02, 0.08)), -2))
    reserve = int(round(charter * float(rng.uniform(0.0, 0.15))))
    provisions = int(round(annual * float(rng.uniform(0.0, 0.02))))
    cash_m = cash_months if cash_months is not None else float(rng.uniform(0.25, 0.9))
    payroll_share = float(rng.uniform(0.05, 0.12))
    f1: dict[str, dict[str, int | None]] = {}
    re_prev = None
    prev_key = None
    for dkey in DATES:
        y, mth = int(dkey[:4]), int(dkey[5:7])
        d = date.fromisoformat(dkey)
        idx = MONTHS.index((y, mth))
        last3 = [MONTHS[j] for j in range(idx - 2, idx + 1)]
        rev3 = sum(monthly[mm]["rev"] for mm in last3)
        cogs3 = sum(monthly[mm]["cogs"] for mm in last3)
        rev_d, cogs_d = rev3 / 91.0, cogs3 / 91.0
        v: dict[str, int | None] = {}
        months_since = idx + 1
        gross = fa_gross0 + capex_m * months_since
        acc_dep = fa_gross0 * 0.35 + gross * dep_rate * months_since / 12
        v["010"] = int(round(gross))
        v["011"] = int(round(min(acc_dep, gross * 0.85)))
        v["012"] = v["010"] - v["011"]
        v["020"] = int(round(annual * 0.004))
        v["021"] = int(round(v["020"] * min(0.2 + 0.02 * months_since, 0.9)))
        v["022"] = v["020"] - v["021"]
        v["030"] = 0
        v["090"] = 0
        v["100"] = int(round(capex_m * 2)) if months_since % 7 == 0 else 0
        v["110"] = 0
        v["130"] = v["012"] + v["022"] + v["030"] + v["090"] + v["100"] + v["110"]
        v["140"] = int(round(inv_days * cogs_d * float(rng.normal(1, 0.05))))
        v["190"] = int(round(rev3 * 0.004))
        v["220"] = int(round(ar_days * rev_d * float(rng.normal(1, 0.05))))
        v["260"] = int(round(cogs3 / 3 * float(rng.uniform(0.01, 0.06))))
        v["270"] = int(round(rev3 / 3 * float(rng.uniform(0.002, 0.01))))
        v["310"] = int(round(rev3 / 3 * float(rng.uniform(0.0, 0.02))))
        v["210"] = v["220"] + v["260"] + v["270"] + v["310"]
        v["370"] = 0
        v["380"] = 0
        # liabilities
        v["570"] = int(round(sum(ln.balance_at(d) for ln in loans if ln.declared and ln.long_term) / 1000))
        v["490"] = v["570"]
        v["610"] = int(round(ap_days * cogs_d * float(rng.normal(1, 0.05))))
        v["670"] = int(round(rev3 / 3 * float(rng.uniform(0.0, 0.05))))
        v["680"] = int(round(rev3 / 3 * float(rng.uniform(0.02, 0.05))))
        v["690"] = int(round(rev3 / 3 * 0.002))
        v["700"] = int(round(rev3 / 3 * payroll_share * 0.12))
        v["720"] = int(round(rev3 / 3 * payroll_share * 0.5))
        v["730"] = int(round(sum(ln.balance_at(d) for ln in loans if ln.declared and not ln.long_term) / 1000))
        v["760"] = int(round(rev3 / 3 * float(rng.uniform(0.0, 0.02))))
        v["410"], v["420"], v["430"], v["470"] = charter, 0, reserve, provisions
        min_cash = int(round(rev3 / 3 * cash_m))
        cur_liab = lambda: sum(v[c] for c in ("610", "670", "680", "690", "700", "720", "730", "760"))  # noqa: E731
        non_cash_assets = v["130"] + v["140"] + v["190"] + v["210"] + v["370"] + v["380"]
        if re_prev is None:
            v["330"] = int(round(min_cash * 0.02))
            v["340"] = min_cash - v["330"]
            v["350"] = 0
            v["320"] = v["330"] + v["340"] + v["350"]
            assets = non_cash_assets + v["320"]
            v["450"] = assets - cur_liab() - v["490"] - (charter + reserve + provisions)
            if v["450"] < 0:  # recapitalise so equity stays positive
                v["410"] = charter = charter + (-v["450"]) + int(round(annual * 0.01, -2))
                v["450"] = assets - cur_liab() - v["490"] - (charter + reserve + provisions)
        else:
            per = {"2025-12-31": "FY2025", "2026-03-31": "Q1-2026", "2026-06-30": "Q2-2026", "2026-09-30": "Q3-2026"}[dkey]
            v["450"] = re_prev + f2[per]["270"]
            equity = v["410"] + v["420"] + v["430"] + v["450"] + v["470"]
            v["330"] = int(round(min_cash * 0.02))
            v["350"] = 0
            cash = equity + v["490"] + cur_liab() - non_cash_assets
            settle = cash - v["330"]
            if settle < min_cash * 0.3:  # overdraft / short-term facility closes the gap
                gap = int(round(min_cash * 0.3)) - settle
                v["730"] += gap
                settle += gap
            v["340"] = settle
            v["320"] = v["330"] + v["340"] + v["350"]
        v["390"] = v["140"] + v["190"] + v["210"] + v["320"] + v["370"] + v["380"]
        v["400"] = v["130"] + v["390"]
        v["480"] = v["410"] + v["420"] + v["430"] + v["450"] + v["470"]
        v["600"] = cur_liab()
        v["770"] = v["490"] + v["600"]
        v["780"] = v["480"] + v["770"]
        complete_f1(v, rng, company.industry_key)
        assert v["400"] == v["780"], (dkey, v["400"], v["780"])
        errs = check_sums("form1", v)
        assert not errs, errs
        f1[dkey] = v
        re_prev = v["450"]
        prev_key = dkey
    # H1-2026 RE roll (2025-12-31 -> 2026-06-30) equals NP(Q1)+NP(Q2) == NP(H1) because taxes are quarterly
    assert f1["2026-06-30"]["450"] - f1["2025-12-31"]["450"] == f2["H1-2026"]["270"]
    params = dict(annual_rev=annual, growth=g, cogs_share=c_share, opex_share=o_share, ar_days=ar_days,
                  inv_days=inv_days, ap_days=ap_days, payroll_share=payroll_share, cash_months=cash_m)
    return Fin(company=company, monthly=monthly, f2=f2, f1=f1, loans=loans, params=params)
