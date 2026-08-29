from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.metrics import MetricsSummary, compute_metrics
from app.database import get_db

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsSummary)
def get_metrics(db: Session = Depends(get_db)):
    return compute_metrics(db)
