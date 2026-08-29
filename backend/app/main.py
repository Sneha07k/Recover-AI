from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.audit import router as audit_router
from app.api.metrics import router as metrics_router
from app.api.transactions import router as transactions_router
from app.config import settings
from app.database import get_db

app = FastAPI(title=settings.APP_NAME)

# Dev-only: the dashboard (Phase 11) is a static HTML file with no
# authentication, opened either directly from disk or from a different
# local port than the API. Wide-open CORS is fine for a local buildathon
# demo; this would need real origin restrictions before any deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(transactions_router)
app.include_router(audit_router)
app.include_router(metrics_router)


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }
