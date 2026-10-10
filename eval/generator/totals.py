"""Compute Form 1 / Form 2 totals from leaf values (used for the pinned hero companies)."""
from __future__ import annotations

F1_LEAVES = ["010", "011", "020", "021", "030", "090", "100", "110", "120", "150", "160", "170", "180", "190", "200",
             "220", "260", "270", "310", "330", "340", "350", "370", "380", "410", "420", "430", "440", "450", "460",
             "470", "570", "580", "610", "670", "680", "690", "700", "720", "730", "740", "750", "760"]
F2_LEAVES = ["010", "020", "050", "060", "070", "090", "120", "130", "140", "150", "160", "180", "190", "200", "210",
             "230", "250", "260"]


def f1_totals(leaf: dict[str, int]) -> dict[str, int]:
    v = {c: int(leaf.get(c, 0)) for c in F1_LEAVES}
    v["012"] = v["010"] - v["011"]
    v["022"] = v["020"] - v["021"]
    v["130"] = v["012"] + v["022"] + v["030"] + v["090"] + v["100"] + v["110"] + v["120"]
    v["140"] = v["150"] + v["160"] + v["170"] + v["180"]
    v["210"] = v["220"] + v["260"] + v["270"] + v["310"]
    v["320"] = v["330"] + v["340"] + v["350"]
    v["390"] = v["140"] + v["190"] + v["200"] + v["210"] + v["320"] + v["370"] + v["380"]
    v["400"] = v["130"] + v["390"]
    v["480"] = v["410"] + v["420"] + v["430"] - v["440"] + v["450"] + v["460"] + v["470"]
    v["490"] = v["570"] + v["580"]
    v["600"] = sum(v[c] for c in ("610", "670", "680", "690", "700", "720", "730", "740", "750", "760"))
    v["770"] = v["490"] + v["600"]
    v["780"] = v["480"] + v["770"]
    return v


def f2_totals(leaf: dict[str, int]) -> dict[str, int]:
    v = {c: int(leaf.get(c, 0)) for c in F2_LEAVES}
    v["030"] = v["010"] - v["020"]
    v["040"] = v["050"] + v["060"] + v["070"]
    v["100"] = v["030"] - v["040"] + v["090"]
    v["110"] = v["120"] + v["130"] + v["140"] + v["150"] + v["160"]
    v["170"] = v["180"] + v["190"] + v["200"] + v["210"]
    v["220"] = v["100"] + v["110"] - v["170"]
    v["240"] = v["220"] + v["230"]
    v["270"] = v["240"] - v["250"] - v["260"]
    return v


def plug_cash(leaf: dict[str, int], code: str = "340") -> dict[str, int]:
    """Set `code` so the balance closes (assets = equity + liabilities)."""
    leaf = dict(leaf)
    leaf[code] = 0
    v = f1_totals(leaf)
    leaf[code] = v["780"] - v["400"]
    return leaf


def plug_equity(leaf: dict[str, int], code: str = "470") -> dict[str, int]:
    leaf = dict(leaf)
    leaf[code] = 0
    v = f1_totals(leaf)
    leaf[code] = v["400"] - v["780"]
    return leaf
