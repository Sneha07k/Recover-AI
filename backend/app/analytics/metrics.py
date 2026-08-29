from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.enums import RecoveryStrategy, TransactionStatus
from app.models.models import PolicyDecision, RecoveryAttempt, Transaction


class MetricsSummary(BaseModel):
    transactions_total: int
    revenue_processed: float
    transactions_failed: int
    revenue_at_risk: float
    revenue_attempted: float
    interventions_attempted: int
    successful_recoveries: int
    failed_interventions: int
    escalations: int
    stopped_by_policy: int
    stopped_by_strategy: int
    revenue_recovered: float
    recovery_rate: float | None


class StrategyBreakdown(BaseModel):
    strategy: str
    attempted: int
    succeeded: int
    revenue_recovered: float


class PaymentMethodBreakdown(BaseModel):
    payment_method: str
    failed: int
    recovered: int
    recovery_rate: float | None


class FailureReasonBreakdown(BaseModel):
    failure_type: str
    count: int


class PolicyVerdictBreakdown(BaseModel):
    verdict: str
    count: int


def compute_metrics(db: Session) -> MetricsSummary:
    transactions = db.query(Transaction).all()
    revenue_processed = sum(t.amount for t in transactions)
    failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
    revenue_at_risk = sum(t.amount for t in failed)

    attempts = db.query(RecoveryAttempt).all()
    successful = [a for a in attempts if a.succeeded]
    failed_attempts = [a for a in attempts if not a.succeeded]
    revenue_recovered = sum(a.amount_recovered for a in successful)

    attempted_txn_ids = {a.transaction_id for a in attempts}
    revenue_attempted = sum(t.amount for t in transactions if t.id in attempted_txn_ids)

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
        revenue_attempted=revenue_attempted,
        interventions_attempted=len(attempts),
        successful_recoveries=len(successful),
        failed_interventions=len(failed_attempts),
        escalations=escalations,
        stopped_by_policy=stopped_by_policy,
        stopped_by_strategy=stopped_by_strategy,
        revenue_recovered=revenue_recovered,
        recovery_rate=recovery_rate,
    )


def compute_strategy_breakdown(db: Session) -> list[StrategyBreakdown]:
    attempts = db.query(RecoveryAttempt).all()
    grouped = defaultdict(
        lambda: {"attempted": 0, "succeeded": 0, "revenue_recovered": 0.0}
    )
    for a in attempts:
        key = a.strategy.value if a.strategy else "unknown"
        grouped[key]["attempted"] += 1
        if a.succeeded:
            grouped[key]["succeeded"] += 1
            grouped[key]["revenue_recovered"] += a.amount_recovered
    return [StrategyBreakdown(strategy=k, **v) for k, v in grouped.items()]


def compute_payment_method_breakdown(db: Session) -> list[PaymentMethodBreakdown]:
    failed_txns = (
        db.query(Transaction)
        .filter(Transaction.status == TransactionStatus.FAILED)
        .all()
    )
    grouped = defaultdict(lambda: {"failed": 0, "recovered": 0})
    for t in failed_txns:
        key = t.payment_method.value
        grouped[key]["failed"] += 1
        if t.recovered:
            grouped[key]["recovered"] += 1

    result = []
    for k, v in grouped.items():
        rate = v["recovered"] / v["failed"] if v["failed"] else None
        result.append(
            PaymentMethodBreakdown(
                payment_method=k,
                failed=v["failed"],
                recovered=v["recovered"],
                recovery_rate=rate,
            )
        )
    return result


def compute_failure_reason_breakdown(db: Session) -> list[FailureReasonBreakdown]:
    """
    Note: only covers transactions that got a recovery ATTEMPT — failures
    that were denied or escalated never reveal their hidden failure_type,
    since we only simulate it at the moment of execution (Phase 9).
    """
    attempts = db.query(RecoveryAttempt).all()
    grouped = defaultdict(int)
    for a in attempts:
        grouped[a.failure_type.value] += 1
    return [FailureReasonBreakdown(failure_type=k, count=v) for k, v in grouped.items()]


def compute_policy_verdict_breakdown(db: Session) -> list[PolicyVerdictBreakdown]:
    decisions = db.query(PolicyDecision).all()
    grouped = defaultdict(int)
    for d in decisions:
        grouped[d.verdict] += 1
    return [PolicyVerdictBreakdown(verdict=k, count=v) for k, v in grouped.items()]
