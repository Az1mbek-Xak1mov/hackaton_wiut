"""Imports every model so Base.metadata is complete (Alembic, tests)."""
from app.core.base_model import Base  # noqa: F401
from app.modules.applications.models import Application, ApplicationDocument, Decision  # noqa: F401
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.borrowers.models import Borrower, Loan, Repayment  # noqa: F401
from app.modules.cfo.models import CfoMessage, CfoThread  # noqa: F401
from app.modules.documents.models import Document, Page  # noqa: F401
from app.modules.extraction.models import Fact  # noqa: F401
from app.modules.jobs.models import Job  # noqa: F401
from app.modules.llm.models import LlmCall, NarrativeRun  # noqa: F401
from app.modules.monitoring.models import MonitoringResult, MonitoringRun  # noqa: F401
from app.modules.reconcile.models import Finding  # noqa: F401
from app.modules.reviews.models import FactReview  # noqa: F401
from app.modules.settings.models import AppSetting  # noqa: F401
from app.modules.statements.models import Transaction  # noqa: F401
from app.modules.users.models import User  # noqa: F401
