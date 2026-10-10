from enum import Enum
from typing import Dict, List


class Scope(str, Enum):
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    APPLICATION_READ = "application:read"
    APPLICATION_WRITE = "application:write"
    DECISION_WRITE = "decision:write"
    BORROWER_READ = "borrower:read"
    BORROWER_WRITE = "borrower:write"
    MONITORING_READ = "monitoring:read"
    MONITORING_RUN = "monitoring:run"
    FACT_REVIEW = "fact:review"
    CFO_USE = "cfo:use"
    OWNER_FILES = "owner:files"
    SETTINGS_WRITE = "settings:write"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    AUDIT_READ = "audit:read"


class Role(str, Enum):
    ADMIN = "admin"
    OFFICER = "officer"
    OWNER = "owner"
    DEMO_VIEWER = "demo_viewer"


_BANK_READ = [Scope.DOCUMENT_READ, Scope.APPLICATION_READ, Scope.BORROWER_READ, Scope.MONITORING_READ]

ROLE_SCOPES: Dict[Role, List[Scope]] = {
    Role.DEMO_VIEWER: _BANK_READ + [Scope.OWNER_FILES],
    Role.OFFICER: _BANK_READ + [
        Scope.DOCUMENT_WRITE, Scope.APPLICATION_WRITE, Scope.DECISION_WRITE, Scope.BORROWER_WRITE,
        Scope.MONITORING_RUN, Scope.FACT_REVIEW, Scope.SETTINGS_WRITE, Scope.AUDIT_READ,
    ],
    Role.OWNER: [Scope.DOCUMENT_READ, Scope.DOCUMENT_WRITE, Scope.FACT_REVIEW, Scope.CFO_USE, Scope.OWNER_FILES],
    Role.ADMIN: list(Scope),
}

# Roles that see every borrower; an owner sees only the borrower bound to them.
PORTFOLIO_ROLES = {Role.ADMIN.value, Role.OFFICER.value, Role.DEMO_VIEWER.value}


def scopes_for(role: str) -> List[str]:
    return [s.value for s in ROLE_SCOPES.get(Role(role), [])]
