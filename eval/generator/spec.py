"""Form 1 (balance sheet) and Form 2 (financial results) line specs used by the generator.

Built-in codes follow the statutory NSBU templates (Form 1: 010..780, Form 2: 010..270).
If app/pipeline/dictionary/forms.yaml exists, its labels override ours for the same code so the
generated documents use exactly the wording the extractor's dictionary knows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .translit import to_cyrillic

ROOT = Path(__file__).resolve().parents[2]
DICT_PATH = ROOT / "app" / "pipeline" / "dictionary" / "forms.yaml"


@dataclass
class Line:
    form: str
    code: str
    ru: str
    uz: str
    en: str
    sum_of: list[tuple[str, int]] = field(default_factory=list)  # (code, sign)
    total: bool = False
    indent: int = 0
    uz_cyrl: str = ""
    in_dictionary: bool = True
    parts: list[str] = field(default_factory=list)
    kind: str = "amount"

    def label(self, lang: str) -> str:
        if lang == "ru":
            return self.ru
        if lang == "uz_cyrl":
            return self.uz_cyrl or to_cyrillic(self.uz)
        if lang == "en":
            return self.en
        return self.uz


def _p(*codes: str) -> list[tuple[str, int]]:
    out = []
    for c in codes:
        out.append((c[1:], -1) if c.startswith("-") else (c, 1))
    return out


F1: list[Line] = [
    Line("form1", "010", "Основные средства: первоначальная (восстановительная) стоимость", "Asosiy vositalar: boshlang'ich (tiklash) qiymati", "Fixed assets: initial cost"),
    Line("form1", "011", "Износ основных средств", "Asosiy vositalarning eskirish summasi", "Accumulated depreciation", indent=1),
    Line("form1", "012", "Остаточная (балансовая) стоимость (стр. 010-011)", "Qoldiq (balans) qiymati (010-011)", "Fixed assets, net", _p("010", "-011"), indent=1),
    Line("form1", "020", "Нематериальные активы: первоначальная стоимость", "Nomoddiy aktivlar: boshlang'ich qiymati", "Intangible assets: initial cost"),
    Line("form1", "021", "Амортизация нематериальных активов", "Nomoddiy aktivlar amortizatsiyasi", "Amortisation", indent=1),
    Line("form1", "022", "Остаточная стоимость (стр. 020-021)", "Qoldiq qiymati (020-021)", "Intangible assets, net", _p("020", "-021"), indent=1),
    Line("form1", "030", "Долгосрочные инвестиции, всего", "Uzoq muddatli investitsiyalar, jami", "Long-term investments"),
    Line("form1", "090", "Оборудование к установке", "O'rnatiladigan asbob-uskunalar", "Equipment to be installed"),
    Line("form1", "100", "Капитальные вложения", "Kapital qo'yilmalar", "Capital investments"),
    Line("form1", "110", "Долгосрочная дебиторская задолженность", "Uzoq muddatli debitorlik qarzlari", "Long-term receivables"),
    Line("form1", "130", "Итого по разделу I (стр. 012+022+030+090+100+110)", "I bo'lim bo'yicha jami", "Total non-current assets", _p("012", "022", "030", "090", "100", "110"), total=True),
    Line("form1", "140", "Товарно-материальные запасы, всего", "Tovar-moddiy zaxiralar, jami", "Inventories"),
    Line("form1", "190", "Расходы будущих периодов", "Kelgusi davr xarajatlari", "Prepaid expenses"),
    Line("form1", "210", "Дебиторы, всего", "Debitorlar, jami", "Receivables, total", _p("220", "260", "270", "310")),
    Line("form1", "220", "Задолженность покупателей и заказчиков", "Xaridor va buyurtmachilarning qarzi", "Trade receivables", indent=1),
    Line("form1", "260", "Авансы, выданные поставщикам и подрядчикам", "Mol yetkazib beruvchilar va pudratchilarga berilgan bo'naklar", "Advances to suppliers", indent=1),
    Line("form1", "270", "Авансовые платежи по налогам и сборам в бюджет", "Budjetga soliq va yig'imlar bo'yicha bo'nak to'lovlari", "Tax prepayments", indent=1),
    Line("form1", "310", "Прочая дебиторская задолженность", "Boshqa debitorlik qarzlari", "Other receivables", indent=1),
    Line("form1", "320", "Денежные средства, всего", "Pul mablag'lari, jami", "Cash, total", _p("330", "340", "350")),
    Line("form1", "330", "Денежные средства в кассе", "Kassadagi pul mablag'lari", "Cash on hand", indent=1),
    Line("form1", "340", "Денежные средства на расчетном счете", "Hisob-kitob schyotidagi pul mablag'lari", "Cash at settlement account", indent=1),
    Line("form1", "350", "Денежные средства в иностранной валюте", "Xorijiy valyutadagi pul mablag'lari", "Cash in foreign currency", indent=1),
    Line("form1", "370", "Краткосрочные инвестиции", "Qisqa muddatli investitsiyalar", "Short-term investments"),
    Line("form1", "380", "Прочие текущие активы", "Boshqa joriy aktivlar", "Other current assets"),
    Line("form1", "390", "Итого по разделу II (стр. 140+190+210+320+370+380)", "II bo'lim bo'yicha jami", "Total current assets", _p("140", "190", "210", "320", "370", "380"), total=True),
    Line("form1", "400", "Всего по активу баланса (стр. 130+390)", "Balans aktivi bo'yicha jami (130+390)", "Total assets", _p("130", "390"), total=True),
    Line("form1", "410", "Уставный капитал", "Ustav kapitali", "Charter capital"),
    Line("form1", "420", "Добавленный капитал", "Qo'shilgan kapital", "Additional paid-in capital"),
    Line("form1", "430", "Резервный капитал", "Rezerv kapitali", "Reserve capital"),
    Line("form1", "450", "Нераспределенная прибыль (непокрытый убыток)", "Taqsimlanmagan foyda (qoplanmagan zarar)", "Retained earnings"),
    Line("form1", "470", "Резервы предстоящих расходов и платежей", "Kelgusi xarajatlar va to'lovlar zaxiralari", "Provisions for future expenses"),
    Line("form1", "480", "Итого по разделу I (стр. 410+420+430+450+470)", "I bo'lim bo'yicha jami", "Total equity", _p("410", "420", "430", "450", "470"), total=True),
    Line("form1", "490", "Долгосрочные обязательства, всего", "Uzoq muddatli majburiyatlar, jami", "Long-term liabilities", _p("570")),
    Line("form1", "570", "Долгосрочные банковские кредиты", "Uzoq muddatli bank kreditlari", "Long-term bank loans", indent=1),
    Line("form1", "600", "Текущие обязательства, всего", "Joriy majburiyatlar, jami", "Current liabilities", _p("610", "670", "680", "690", "700", "720", "730", "760")),
    Line("form1", "610", "Задолженность поставщикам и подрядчикам", "Mol yetkazib beruvchilar va pudratchilarga qarz", "Trade payables", indent=1),
    Line("form1", "670", "Полученные авансы", "Olingan bo'naklar", "Advances received", indent=1),
    Line("form1", "680", "Задолженность по платежам в бюджет", "Budjetga to'lovlar bo'yicha qarz", "Taxes payable", indent=1),
    Line("form1", "690", "Задолженность по страхованию", "Sug'urta bo'yicha qarz", "Insurance payables", indent=1),
    Line("form1", "700", "Задолженность по платежам в государственные целевые фонды", "Davlat maqsadli jamg'armalariga to'lovlar bo'yicha qarz", "State fund payables", indent=1),
    Line("form1", "720", "Задолженность по оплате труда", "Mehnatga haq to'lash bo'yicha qarz", "Payroll payables", indent=1),
    Line("form1", "730", "Краткосрочные банковские кредиты", "Qisqa muddatli bank kreditlari", "Short-term bank loans", indent=1),
    Line("form1", "760", "Прочие кредиторские задолженности", "Boshqa kreditorlik qarzlari", "Other payables", indent=1),
    Line("form1", "770", "Итого по разделу II (стр. 490+600)", "II bo'lim bo'yicha jami (490+600)", "Total liabilities", _p("490", "600"), total=True),
    Line("form1", "780", "Всего по пассиву баланса (стр. 480+770)", "Balans passivi bo'yicha jami (480+770)", "Total equity and liabilities", _p("480", "770"), total=True),
]

F2: list[Line] = [
    Line("form2", "010", "Чистая выручка от реализации продукции (товаров, работ и услуг)", "Mahsulot (tovar, ish va xizmat)larni sotishdan sof tushum", "Net revenue"),
    Line("form2", "020", "Себестоимость реализованной продукции (товаров, работ и услуг)", "Sotilgan mahsulot (tovar, ish va xizmat)larning tannarxi", "Cost of sales"),
    Line("form2", "030", "Валовая прибыль (убыток) от реализации продукции (стр. 010-020)", "Mahsulot sotishning yalpi foydasi (zarari) (010-020)", "Gross profit", _p("010", "-020"), total=True),
    Line("form2", "040", "Расходы периода, всего (стр. 050+060+070)", "Davr xarajatlari, jami (050+060+070)", "Period expenses", _p("050", "060", "070")),
    Line("form2", "050", "Расходы по реализации", "Sotish xarajatlari", "Selling expenses", indent=1),
    Line("form2", "060", "Административные расходы", "Ma'muriy xarajatlar", "Administrative expenses", indent=1),
    Line("form2", "070", "Прочие операционные расходы", "Boshqa operatsion xarajatlar", "Other operating expenses", indent=1),
    Line("form2", "090", "Прочие доходы от основной деятельности", "Asosiy faoliyatning boshqa daromadlari", "Other operating income"),
    Line("form2", "100", "Прибыль (убыток) от основной деятельности (стр. 030-040+090)", "Asosiy faoliyatning foydasi (zarari) (030-040+090)", "Operating profit", _p("030", "-040", "090"), total=True),
    Line("form2", "110", "Доходы от финансовой деятельности, всего", "Moliyaviy faoliyatdan daromadlar, jami", "Finance income", _p("120", "130")),
    Line("form2", "120", "Доходы в виде дивидендов", "Dividendlar ko'rinishidagi daromadlar", "Dividend income", indent=1),
    Line("form2", "130", "Доходы в виде процентов", "Foizlar ko'rinishidagi daromadlar", "Interest income", indent=1),
    Line("form2", "170", "Расходы по финансовой деятельности, всего", "Moliyaviy faoliyat bo'yicha xarajatlar, jami", "Finance costs", _p("180")),
    Line("form2", "180", "Расходы в виде процентов", "Foizlar ko'rinishidagi xarajatlar", "Interest expense", indent=1),
    Line("form2", "220", "Прибыль (убыток) от общехозяйственной деятельности (стр. 100+110-170)", "Umumxo'jalik faoliyatining foydasi (zarari) (100+110-170)", "Profit from ordinary activities", _p("100", "110", "-170"), total=True),
    Line("form2", "230", "Чрезвычайные прибыли и убытки", "Favqulodda foyda va zararlar", "Extraordinary items"),
    Line("form2", "240", "Прибыль (убыток) до уплаты налога на прибыль (стр. 220+/-230)", "Foyda solig'ini to'lagunga qadar foyda (zarar) (220+/-230)", "Profit before tax", _p("220", "230"), total=True),
    Line("form2", "250", "Налог на прибыль", "Daromad (foyda) solig'i", "Profit tax"),
    Line("form2", "260", "Прочие налоги и сборы от прибыли", "Foydadan boshqa soliqlar va yig'imlar", "Other taxes on profit"),
    Line("form2", "270", "Чистая прибыль (убыток) отчетного периода (стр. 240-250-260)", "Hisobot davrining sof foydasi (zarari) (240-250-260)", "Net profit for the period", _p("240", "-250", "-260"), total=True),
]

F1_SECTIONS = {
    "010": ("АКТИВ\nI. Долгосрочные активы", "AKTIV\nI. Uzoq muddatli aktivlar", "ASSETS\nI. Non-current assets"),
    "140": ("II. Текущие активы", "II. Joriy aktivlar", "II. Current assets"),
    "410": ("ПАССИВ\nI. Источники собственных средств", "PASSIV\nI. O'z mablag'lari manbalari", "EQUITY AND LIABILITIES\nI. Equity"),
    "490": ("II. Обязательства", "II. Majburiyatlar", "II. Liabilities"),
}

_dict_cache: dict | None = None


def load_dictionary() -> dict[tuple[str, str], dict]:
    """(form, code) -> yaml entry, or {} if the dictionary is not there yet."""
    global _dict_cache
    if _dict_cache is not None:
        return _dict_cache
    out: dict[tuple[str, str], dict] = {}
    if DICT_PATH.exists():
        import yaml
        data = yaml.safe_load(DICT_PATH.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else (data.get("entries") or data.get("lines") or [])
        for e in entries:
            if isinstance(e, dict) and "code" in e and "form" in e:
                out[(str(e["form"]), str(e["code"]).zfill(3))] = e
    _dict_cache = out
    return out


def _first(labels, key):
    v = labels.get(key) if isinstance(labels, dict) else None
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _parse_sum(items) -> list[tuple[str, int]]:
    return _p(*[str(x) for x in (items or [])])


def lines(form: str) -> list[Line]:
    """Rows to print for a form: every dictionary line + our extra official rows not in the dictionary."""
    base = {ln.code: ln for ln in (F1 if form == "form1" else F2)}
    d = load_dictionary()
    if not d:
        return list(base.values())
    out: dict[str, Line] = {}
    for (f, code), e in d.items():
        if f != form:
            continue
        labels = e.get("labels", {})
        b = base.get(code)
        is_total = e.get("kind") == "total" or bool(e.get("sum_of")) or bool(e.get("parts"))
        out[code] = Line(
            form=form, code=code,
            ru=_first(labels, "ru") or (b.ru if b else code),
            uz=_first(labels, "uz_latn") or (b.uz if b else code),
            en=_first(labels, "en") or (b.en if b else code),
            uz_cyrl=_first(labels, "uz_cyrl") or "",
            sum_of=_parse_sum(e.get("sum_of")),
            total=is_total and code in TOTAL_BOLD,
            indent=b.indent if b else (1 if code in INDENT1 else 0),
            in_dictionary=True,
            parts=[str(x) for x in (e.get("parts") or [])],
            kind=e.get("kind", "amount"),
        )
    for code, b in base.items():
        if code not in out:
            out[code] = Line(**{**b.__dict__, "in_dictionary": False, "sum_of": [], "parts": [], "kind": "amount"})
    return [out[c] for c in sorted(out)]


INDENT1 = {"150", "160", "170", "180", "580", "740", "750", "140", "150", "160", "190", "200", "210"}
TOTAL_BOLD = {"130", "390", "400", "480", "770", "780", "030", "100", "220", "240", "270"}


def zero_as_dash(line: Line) -> bool:
    """Zero is printed '-' for plain amount lines and '0' for totals (e.g. 490 = 0)."""
    return getattr(line, "kind", "amount") not in ("total",) and not line.sum_of and not getattr(line, "parts", [])


def check_sums(form: str, values: dict[str, int | None]) -> list[str]:
    """Violated exhaustive sum relations (dictionary `sum_of`, else built-in)."""
    errs = []
    for ln in lines(form):
        rel = ln.sum_of
        if not rel or values.get(ln.code) is None:
            continue
        s = sum(sign * (values.get(c) or 0) for c, sign in rel)
        if abs(s - values[ln.code]) > 1:
            errs.append(f"{ln.code}: {values[ln.code]} != {s}")
    return errs
