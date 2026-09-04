from sqlalchemy.orm import Session

from app.agents.ambiguity import is_ambiguous
from app.agents.engine import make_agent_decision
from app.events.schemas import Event
from app.execution.executor import execute_strategy
from app.models.enums import PaymentMethod, RecoveryStrategy
from app.models.models import Customer, Transaction
from app.policies.engine import ALLOW, DENY, ESCALATE, evaluate_and_record_policy
from app.strategy.engine import persist_strategy_decision, recommend_strategy

STOPPED_BY_STRATEGY = "stopped_by_strategy"
STOPPED_BY_POLICY = "stopped_by_policy"
ESCALATED = "escalated"
EXECUTED = "executed"


def categorize_outcome(strategy: RecoveryStrategy, policy_verdict: str) -> str:
    if strategy == RecoveryStrategy.STOP:
        return STOPPED_BY_STRATEGY
    if strategy == RecoveryStrategy.ESCALATION or policy_verdict == ESCALATE:
        return ESCALATED
    if policy_verdict == DENY:
        return STOPPED_BY_POLICY
    return EXECUTED


def run_closed_loop(
    db: Session,
    transaction_id: int,
    customer_id: int,
    payment_method: PaymentMethod,
    amount: float,
    use_agent_for_ambiguous: bool = False,
) -> dict:
    
    recommendation = recommend_strategy(
        db, transaction_id, customer_id, payment_method, amount
    )
    persist_strategy_decision(
        db, transaction_id, customer_id, payment_method, amount, recommendation
    )

    strategy = recommendation.strategy
    requires_approval = False

    if use_agent_for_ambiguous and is_ambiguous(recommendation, amount):
        agent_decision = make_agent_decision(
            db, transaction_id, customer_id, payment_method, amount
        )
        strategy = agent_decision.action
        requires_approval = agent_decision.requires_approval

    policy_decision = evaluate_and_record_policy(
        db, customer_id, transaction_id, strategy, amount, requires_approval
    )

    outcome = {
        "transaction_id": transaction_id,
        "strategy": strategy.value,
        "policy_verdict": policy_decision.verdict,
        "bucket": categorize_outcome(strategy, policy_decision.verdict),
    }

    if outcome["bucket"] == EXECUTED:
        transaction = db.get(Transaction, transaction_id)
        customer = db.get(Customer, customer_id)
        attempt = execute_strategy(db, transaction, customer, strategy)
        outcome["succeeded"] = attempt.succeeded
        outcome["amount_recovered"] = attempt.amount_recovered

    return outcome


def run_closed_loop_on_payment_failed(
    db: Session, event: Event, use_agent_for_ambiguous: bool = False
) -> dict:
    return run_closed_loop(
        db,
        transaction_id=event.entity_id,
        customer_id=event.payload["customer_id"],
        payment_method=PaymentMethod(event.payload["payment_method"]),
        amount=event.payload["amount"],
        use_agent_for_ambiguous=use_agent_for_ambiguous,
    )
