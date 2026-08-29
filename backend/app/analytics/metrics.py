from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.enums import RecoveryStrategy, TransactionStatus
from app.models.models import PolicyDecision, RecoveryAttempt, Transaction


class MetricsSummary(BaseModel):
    transactions_total: int
    revenue_processed: float
    transactions_failed: int
    revenue_at_risk: float
    interventions_attempted: int
    successful_recoveries: int
    failed_interventions: int
    escalations: int
    stopped_by_policy: int
    stopped_by_strategy: int
    revenue_recovered: float
    recovery_rate: float | None  # None when there have been zero interventions


def compute_metrics(db: Session) -> MetricsSummary:
    """
    The single source of truth for RecoverAI's headline numbers. Used by
    both scripts/run_simulation.py (CLI report) and GET /metrics (API),
    so the two can never silently disagree.
    """
    transactions = db.query(Transaction).all()
    revenue_processed = sum(t.amount for t in transactions)
    failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
    revenue_at_risk = sum(t.amount for t in failed)

    attempts = db.query(RecoveryAttempt).all()
    successful = [a for a in attempts if a.succeeded]
    failed_attempts = [a for a in attempts if not a.succeeded]
    revenue_recovered = sum(a.amount_recovered for a in successful)

    escalations = (
        db.query(PolicyDecision).filter(PolicyDecision.verdict == "escalate").count()
    )
    stopped_by_policy = (
        db.query(PolicyDecision).filter(PolicyDecision.verdict == "deny").count()
    )
    stopped_by_strategy = (
        db.query(PolicyDecision)
        .filter(PolicyDecision.strategy == RecoveryStrategy.STOP)
        .count()
    )

    recovery_rate = (len(successful) / len(attempts)) if attempts else None

    return MetricsSummary(
        transactions_total=len(transactions),
        revenue_processed=revenue_processed,
        transactions_failed=len(failed),
        revenue_at_risk=revenue_at_risk,
        interventions_attempted=len(attempts),
        successful_recoveries=len(successful),
        failed_interventions=len(failed_attempts),
        escalations=escalations,
        stopped_by_policy=stopped_by_policy,
        stopped_by_strategy=stopped_by_strategy,
        revenue_recovered=revenue_recovered,
        recovery_rate=recovery_rate,
    )
