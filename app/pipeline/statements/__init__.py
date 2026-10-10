"""Bank-statement normalisation: header detection, categorisation, recurring payments, aggregate facts."""
from app.pipeline.statements.categorise import CATEGORIES, CATEGORY_LABELS, Categoriser
from app.pipeline.statements.io import load_xlsx_doc, load_xlsx_sheets
from app.pipeline.statements.normalise import normalise_statement, statement_summary
from app.pipeline.statements.recurring import detect_recurring

__all__ = [
    "CATEGORIES", "CATEGORY_LABELS", "Categoriser", "detect_recurring", "load_xlsx_doc", "load_xlsx_sheets",
    "normalise_statement", "statement_summary",
]
