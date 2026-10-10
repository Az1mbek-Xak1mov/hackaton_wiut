from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.scopes import PORTFOLIO_ROLES
from app.modules.applications.models import Application, ApplicationDocument
from app.modules.applications.service import enqueue_analysis
from app.modules.audit import service as audit
from app.modules.borrowers.models import Borrower
from app.modules.documents.models import Document
from app.modules.extraction.models import Fact
from app.modules.reviews.models import FactReview

FACT_FIELDS = ("value", "status", "confidence")


class ReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def fact_or_404(self, fact_uuid: UUID) -> Fact:
        f = self.db.scalars(select(Fact).where(Fact.uuid == fact_uuid)).first()
        if f is None:
            raise NotFoundError("fact")
        return f

    def _check_owner(self, fact: Fact, actor) -> None:
        if actor.role in PORTFOLIO_ROLES:
            return
        bid = fact.borrower_id
        if bid is None and fact.document_id:
            doc = self.db.get(Document, fact.document_id)
            bid = doc.borrower_id if doc else None
        b = self.db.get(Borrower, bid) if bid else None
        if b is None or b.owner_user_id != actor.id:
            raise ForbiddenError("This figure belongs to another business")

    def review(self, fact: Fact, data: dict, actor) -> Fact:
        """verify / correct / flag (H3). A correction re-runs the application's rules and ratios."""
        self._check_owner(fact, actor)
        before = audit.snapshot(fact, FACT_FIELDS)
        rv = FactReview(fact_id=fact.id, user_id=actor.id, action=data["action"], note=data.get("note") or "")
        if data["action"] == "verify":
            fact.status = "verified"
            fact.confidence = 1.0
        elif data["action"] == "correct":
            rv.old_value, rv.new_value = fact.value, data["value"]
            fact.value = data["value"]
            fact.status = "corrected"
            fact.confidence = 1.0
        else:
            fact.status = "flagged"
        self.db.add(rv)
        self.db.flush()
        audit.record(self.db, actor, data["action"], "fact", fact.uuid, before=before,
                     after=audit.snapshot(fact, FACT_FIELDS) | {"key": fact.key, "note": rv.note})
        if data["action"] == "correct":
            for app in self._applications_of(fact):
                enqueue_analysis(self.db, app)
        self._update_document_status(fact)
        self.db.commit()
        self.db.refresh(fact)
        return fact

    def _applications_of(self, fact: Fact) -> list[Application]:
        ids = set()
        if fact.application_id:
            ids.add(fact.application_id)
        if fact.document_id:
            ids.update(self.db.scalars(select(ApplicationDocument.application_id)
                                       .where(ApplicationDocument.document_id == fact.document_id)).all())
        return [a for a in (self.db.get(Application, i) for i in ids) if a is not None]

    def _update_document_status(self, fact: Fact) -> None:
        """A document leaves 'needs clarification' once no low-confidence figure is left."""
        if not fact.document_id:
            return
        doc = self.db.get(Document, fact.document_id)
        if doc is None or doc.status != "clarification":
            return
        low = self.db.scalars(select(Fact).where(Fact.document_id == doc.id, Fact.kind == "extracted",
                                                 Fact.confidence < 0.80, Fact.id != fact.id)).first()
        if low is None:
            doc.status = "analyzed"
