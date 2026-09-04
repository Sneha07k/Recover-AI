from contextlib import asynccontextmanager
from pathlib import Path
from app.api.customers import router as customers_router
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.actions import router as actions_router
from app.api.audit import router as audit_router
from app.api.metrics import router as metrics_router
from app.api.transactions import router as transactions_router
from app.config import settings
from app.database import SessionLocal, get_db, init_db
from app.events.consumers import register_default_consumers
from app.models.models import Transaction
from app.api.escalations import router as escalations_router

# Absolute, computed from THIS file's location — not relative to whatever
# directory the process happens to be launched from. A relative path here
# ("../frontend") crashes the whole app on startup the moment uvicorn is
# launched from anywhere other than backend/ itself.
# backend/app/main.py -> parents[2] is the project root, where frontend/ lives.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once when the server starts. Two things matter for a deployed
    demo specifically:
    1. init_db() must run here — previously only CLI scripts called it,
       so a fresh deployment with no prior script run would have no
       tables at all and every endpoint would 500.
    2. Auto-seeding a small population if the database is empty means a
       judge opening the deployed URL for the very first time sees a
       populated dashboard immediately, with no action required.
    """
    init_db()
    register_default_consumers()

    db = SessionLocal()
    try:
        has_data = db.query(Transaction).first() is not None
        if not has_data:
            from app.simulator.generator import run_simulation

            run_simulation(db, num_customers=200, num_transactions=1500)
    finally:
        db.close()

    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# Wide-open CORS is harmless once the dashboard is served from this same
# app (same-origin, below), but kept for local dev flexibility (e.g.
# opening frontend/index.html directly via file://, or serving it from a
# different port during development). Note POST is included now, needed
# by the Live Control Panel's action buttons.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(transactions_router)
app.include_router(audit_router)
app.include_router(metrics_router)
app.include_router(actions_router)
app.include_router(escalations_router)
app.include_router(customers_router)


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/")
def serve_dashboard():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
