from app.modules.analyse.router import router as analyse_router
from app.modules.applications.router import router as applications_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.borrowers.router import router as borrowers_router
from app.modules.cfo.router import router as cfo_router
from app.modules.documents.router import router as documents_router
from app.modules.extraction.router import router as facts_router
from app.modules.jobs.router import router as jobs_router
from app.modules.monitoring.router import router as monitoring_router
from app.modules.owner.router import router as owner_router
from app.modules.ratios.router import router as ratios_router
from app.modules.reconcile.router import router as findings_router
from app.modules.reviews.router import router as reviews_router
from app.modules.settings.router import router as settings_router
from app.modules.statements.router import router as statements_router
from app.modules.system.router import router as system_router
from app.modules.users.router import router as users_router

ALL_ROUTERS = [
    system_router, auth_router, users_router, audit_router, settings_router, jobs_router, analyse_router,
    documents_router, facts_router, statements_router, applications_router, findings_router, ratios_router,
    reviews_router, borrowers_router, monitoring_router, owner_router, cfo_router,
]
