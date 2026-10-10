from app.core.formatting import display_for, fmt_number, kuzs_to_bn, kuzs_to_mln
from app.modules.documents.periods import label_end, pretty, resolve_label


def test_money_and_ratio_display():
    assert kuzs_to_mln(9842316) == "9 842.3"
    assert kuzs_to_mln(-117900) == "−117.9"
    assert kuzs_to_bn(86_400_000) == "86.4"
    assert display_for(1.4789, "ratio") == ("1.48", "")
    assert display_for(6.0, "pct") == ("6.0%", "")
    assert display_for(31, "days") == ("31", "days")
    assert display_for(18_500_000, "UZS") == ("18.5", "mln UZS")
    assert fmt_number(-0.01, 1) == "0.0"


def test_period_labels():
    from datetime import date
    assert resolve_label("cur", "form2", date(2025, 1, 1), date(2025, 12, 31)) == "FY2025"
    assert resolve_label("prev", "form2", date(2026, 1, 1), date(2026, 6, 30)) == "H1-2025"
    assert resolve_label("prev", "form1", None, date(2026, 6, 30)) == "FY2025"
    assert resolve_label("Q3-2026", "form2", None, date(2026, 9, 30)) == "Q3-2026"
    assert label_end("H1-2026") == date(2026, 6, 30) and pretty("H1-2026") == "H1 2026"
