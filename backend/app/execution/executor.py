import numpy as np
from sqlalchemy.orm import Session
from app.simulator import chaos

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.enums import FailureType, RecoveryStrategy
from app.models.models import Customer, RecoveryAttempt, Transaction
from app.simulator.ground_truth import (
    RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE,
    TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE,
    TRANSIENT_PROBABILITY_BY_METHOD,
)
from app.strategy.definitions import STRATEGY_DEFINITIONS


def execute_strategy(
    db: Session,
    transaction: Transaction,
    customer: Customer,
    strategy: RecoveryStrategy,
) -> RecoveryAttempt:
    """
    The ONLY function in the system that simulates a real-world recovery
    outcome and mutates transaction state. This plays the role of
    "reality" — it's allowed to use the customer's true behavioral type,
    exactly like the transaction generator does. Everything upstream
    (risk engine, ML model, strategy engine, agent) only ever sees
    observable history, never this.

    This function should only ever be called after the Policy Engine
    (Phase 8) has returned ALLOW for a non-STOP, non-ESCALATION strategy —
    the closed-loop controller enforces that; this function does not
    re-check policy itself.
    """

    transient_prob = chaos.get_transient_probability_override(transaction.payment_method)
    if transient_prob is None:
        transient_prob = TRANSIENT_PROBABILITY_BY_METHOD[transaction.payment_method]
    transient_prob += TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE[customer.customer_type]
    transient_prob = min(max(transient_prob, 0.05), 0.95)
    failure_type = (
        FailureType.TRANSIENT
        if np.random.random() < transient_prob
        else FailureType.PERMANENT
    )
    base_success_prob = RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE[failure_type]

    params = STRATEGY_DEFINITIONS[strategy]
    true_success_prob = min(base_success_prob * params.probability_multiplier, 0.97)
    succeeded = np.random.random() < true_success_prob

    amount_recovered = (
        transaction.amount * params.amount_multiplier if succeeded else 0.0
    )

    attempt = RecoveryAttempt(
        transaction_id=transaction.id,
        strategy=strategy,
        failure_type=failure_type,
        succeeded=succeeded,
        amount_recovered=amount_recovered,
    )
    db.add(attempt)

    if succeeded:
        transaction.recovered = True
        transaction.recovered_amount = amount_recovered

    db.flush()

    event_payload = {
        "amount": transaction.amount,
        "payment_method": transaction.payment_method.value,
        "customer_id": customer.id,
        "strategy": strategy.value,
        "amount_recovered": amount_recovered,
    }
    event_bus.publish(
        db,
        Event(
            event_type=EventType.RECOVERY_ATTEMPTED,
            entity_type="transaction",
            entity_id=transaction.id,
            payload=event_payload,
        ),
    )
    event_bus.publish(
        db,
        Event(
            event_type=(
                EventType.RECOVERY_SUCCESS if succeeded else EventType.RECOVERY_FAILED
            ),
            entity_type="transaction",
            entity_id=transaction.id,
            payload=event_payload,
        ),
    )

    db.flush()
    db.refresh(attempt)
    db.refresh(transaction)
    return attempt
