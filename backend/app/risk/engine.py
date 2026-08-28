from sqlalchemy.orm import Session

from app.events.schemas import Event
from app.models.enums import PaymentMethod
from app.models.models import RiskAssessment
from app.risk.scoring import (
    RECOVERY_PROBABILITY_BY_METHOD,
    calculate_risk_score,
    estimate_failure_probability,
)


def assess_risk_on_payment_failed(db: Session, event: Event) -> RiskAssessment:
    """
    Consumer for PAYMENT_FAILED events. Computes a deterministic risk score
    and persists it — the first real "brain" in the pipeline, even though
    no ML or LLM is involved yet.
    """
    transaction_id = event.entity_id
    customer_id = event.payload["customer_id"]
    payment_method = PaymentMethod(event.payload["payment_method"])
    amount = event.payload["amount"]

    failure_probability = estimate_failure_probability(
        db, customer_id, payment_method, exclude_transaction_id=transaction_id
    )
    recovery_probability = RECOVERY_PROBABILITY_BY_METHOD[payment_method]
    risk_score = calculate_risk_score(failure_probability, amount, recovery_probability)

    assessment = RiskAssessment(
        transaction_id=transaction_id,
        customer_id=customer_id,
        payment_method=payment_method,
        amount=amount,
        failure_probability=failure_probability,
        recovery_probability=recovery_probability,
        risk_score=risk_score,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment
