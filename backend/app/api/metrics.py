from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.metrics import (
    FailureReasonBreakdown,
    MetricsSummary,
    PaymentMethodBreakdown,
    PolicyVerdictBreakdown,
    StrategyBreakdown,
    compute_failure_reason_breakdown,
    compute_metrics,
    compute_payment_method_breakdown,
    compute_policy_verdict_breakdown,
    compute_strategy_breakdown,
)
from app.database import get_db

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsSummary)
def get_metrics(db: Session = Depends(get_db)):
    return compute_metrics(db)


@router.get("/metrics/by-strategy", response_model=list[StrategyBreakdown])
def get_metrics_by_strategy(db: Session = Depends(get_db)):
    return compute_strategy_breakdown(db)


@router.get("/metrics/by-payment-method", response_model=list[PaymentMethodBreakdown])
def get_metrics_by_payment_method(db: Session = Depends(get_db)):
    return compute_payment_method_breakdown(db)


@router.get("/metrics/failure-reasons", response_model=list[FailureReasonBreakdown])
def get_metrics_failure_reasons(db: Session = Depends(get_db)):
    return compute_failure_reason_breakdown(db)


@router.get("/metrics/policy-verdicts", response_model=list[PolicyVerdictBreakdown])
def get_metrics_policy_verdicts(db: Session = Depends(get_db)):
    return compute_policy_verdict_breakdown(db)
