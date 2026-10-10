import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.pipeline.numbers import amount_to_kuzs, fmt_mln_from_k, parse_number  # noqa: E402
from app.pipeline.rows import cluster_rows, merge_numeric_tokens, norm_text  # noqa: E402
from app.pipeline.types import Word  # noqa: E402


@pytest.mark.parametrize("text,value", [
    ("9 842 316", 9842316), ("(1 234)", -1234), ("9.842.316", 9842316), ("1 234,5", 1234.5),
    ("1,234.50", 1234.5), ("-", 0), ("−27", -27), ("1234.56", 1234.56), ("2 870.4", 2870.4),
    ("5 316 400", 5316400),
])
def test_parse_number(text, value):
    assert parse_number(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["х", "abc", "12 34", ""])
def test_parse_number_rejects(text):
    assert parse_number(text) is None


def test_units_and_format():
    assert amount_to_kuzs(850_000_000, "сум") == 850_000
    assert amount_to_kuzs(10_400, "млн сум") == 10_400_000
    assert amount_to_kuzs(148_000, "ming so'm") == 148_000
    assert fmt_mln_from_k(9842316) == "9 842.3"


def test_merge_split_thousands_and_ocr_regroup():
    ws = [Word("9", 100, 10, 106, 20), Word("842", 109, 10, 127, 20), Word("316", 130, 10, 148, 20),
          Word("010", 40, 10, 58, 20)]
    assert [w.text for w in merge_numeric_tokens(ws)] == ["010", "9 842 316"]
    ocr = [Word("1339", 1914, 631, 1993, 654), Word("800", 2006, 631, 2058, 654)]
    assert [w.text for w in merge_numeric_tokens(ocr, ocr=True)] == ["1 339 800"]
    ocr = [Word("$", 1396, 465, 1411, 488), Word("812 400", 1423, 464, 1542, 488)]
    assert [w.text for w in merge_numeric_tokens(ocr, ocr=True)] == ["5 812 400"]


def test_distant_columns_not_merged():
    ws = [Word("120", 300, 10, 318, 20), Word("340", 400, 10, 418, 20)]
    assert len(merge_numeric_tokens(ws)) == 2


def test_rows_and_norm_text():
    ws = [Word("a", 0, 10, 5, 20), Word("b", 10, 11, 15, 21), Word("c", 0, 40, 5, 50)]
    rows = cluster_rows(ws, 1)
    assert [len(r.words) for r in rows] == [2, 1]
    assert norm_text("Итого по разделу II (стр. 140 + 190)") == "итого по разделу ii"
    assert norm_text("Bo‘yicha  JAMI") == "bo'yicha jami"
