from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings
from app.database import get_db

app = FastAPI(title=settings.APP_NAME)


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

