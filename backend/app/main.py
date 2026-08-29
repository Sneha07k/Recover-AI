from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.audit import router as audit_router
from app.api.metrics import router as metrics_router
from app.api.transactions import router as transactions_router
from app.config import settings
from app.database import get_db

app = FastAPI(title=settings.APP_NAME)

app.include_router(transactions_router)
app.include_router(audit_router)
app.include_router(metrics_router)


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Confirms the API is running AND the database connection actually works.
    We run a trivial query rather than just returning {"status": "ok"} so
    that a broken DB connection fails loudly here instead of surprising us
    later in a real endpoint.
    """
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }
