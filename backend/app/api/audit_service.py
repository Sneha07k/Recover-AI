from sqlalchemy.orm import Session

from app.api.schemas import (
    AgentDecisionOut,
    AuditTrailEntry,
    PolicyDecisionOut,
    RecoveryAttemptOut,
    RiskAssessmentOut,
    StrategyDecisionOut,
    TransactionOut,
)
from app.models.models import (
    AgentDecision,
    PolicyDecision,
    RecoveryAttempt,
    RiskAssessment,
    StrategyDecision,
    Transaction,
)


def build_audit_entry(db: Session, transaction_id: int) -> AuditTrailEntry | None:
    """
    Joins across every decision table for one transaction into a single,
    denormalized, human-readable record. Each table stays separate in
    storage (each engine only knows its own concern) — this function is
    the one place that reassembles the full story for a reviewer.
    """
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        return None

    risk = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.transaction_id == transaction_id)
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )
    strategy = (
        db.query(StrategyDecision)
        .filter(StrategyDecision.transaction_id == transaction_id)
        .order_by(StrategyDecision.created_at.desc())
        .first()
    )
    agent = (
        db.query(AgentDecision)
        .filter(AgentDecision.transaction_id == transaction_id)
        .order_by(AgentDecision.created_at.desc())
        .first()
    )
    policy = (
        db.query(PolicyDecision)
        .filter(PolicyDecision.transaction_id == transaction_id)
        .order_by(PolicyDecision.created_at.desc())
        .first()
    )
    attempt = (
        db.query(RecoveryAttempt)
        .filter(RecoveryAttempt.transaction_id == transaction_id)
        .order_by(RecoveryAttempt.created_at.desc())
        .first()
    )

    return AuditTrailEntry(
        transaction=TransactionOut.model_validate(transaction),
        risk_assessment=RiskAssessmentOut.model_validate(risk) if risk else None,
        strategy_decision=(
            StrategyDecisionOut.model_validate(strategy) if strategy else None
        ),
        agent_decision=AgentDecisionOut.model_validate(agent) if agent else None,
        policy_decision=PolicyDecisionOut.model_validate(policy) if policy else None,
        recovery_attempt=(
            RecoveryAttemptOut.model_validate(attempt) if attempt else None
        ),
    )
