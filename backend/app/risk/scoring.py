from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import PaymentMethod, TransactionStatus
from app.models.models import Transaction

# Rule-based estimate of how likely a failed payment is to be recoverable
# if we intervene (e.g. retry). Deliberately simple for Phase 4 â€” Phase 5
# replaces this with a real ML model trained on observed outcomes.
RECOVERY_PROBABILITY_BY_METHOD = {
    PaymentMethod.UPI: 0.55,
    PaymentMethod.CREDIT_CARD: 0.35,
    PaymentMethod.DEBIT_CARD: 0.40,
    PaymentMethod.NET_BANKING: 0.45,
    PaymentMethod.WALLET: 0.60,
}

# Below this many past transactions, we don't yet trust a customer's own
# failure rate enough to rely on it over the payment method's baseline.
MIN_SAMPLES_FOR_CUSTOMER_RATE = 5


def historical_failure_rate_for_method(
    db: Session, payment_method: PaymentMethod, exclude_transaction_id: int | None = None
) -> float:
    """
    Fraction of all past transactions on this payment method that failed â€”
    the population baseline we'd guess for a customer we know nothing about.
    """
    query = db.query(func.count(Transaction.id)).filter(
        Transaction.payment_method == payment_method
    )
    if exclude_transaction_id is not None:
        query = query.filter(Transaction.id != exclude_transaction_id)
    total = query.scalar()

    if not total:
        return 0.10  # fallback prior when we have no data at all

    failed_query = db.query(func.count(Transaction.id)).filter(
        Transaction.payment_method == payment_method,
        Transaction.status == TransactionStatus.FAILED,
    )
    if exclude_transaction_id is not None:
        failed_query = failed_query.filter(Transaction.id != exclude_transaction_id)
    failed = failed_query.scalar()

    return failed / total


def historical_failure_rate_for_customer(
    db: Session, customer_id: int, exclude_transaction_id: int | None = None
) -> tuple[float, int]:
    """
    Same idea, scoped to one customer's own transaction history.
    Returns (rate, sample_size) so the caller can decide whether to trust it.
    """
    query = db.query(func.count(Transaction.id)).filter(
        Transaction.customer_id == customer_id
    )
    if exclude_transaction_id is not None:
        query = query.filter(Transaction.id != exclude_transaction_id)
    total = query.scalar()

    if not total:
        return 0.0, 0

    failed_query = db.query(func.count(Transaction.id)).filter(
        Transaction.customer_id == customer_id,
        Transaction.status == TransactionStatus.FAILED,
    )
    if exclude_transaction_id is not None:
        failed_query = failed_query.filter(Transaction.id != exclude_transaction_id)
    failed = failed_query.scalar()

    return failed / total, total


def estimate_failure_probability(
    db: Session,
    customer_id: int,
    payment_method: PaymentMethod,
    exclude_transaction_id: int | None = None,
) -> float:
    """
    Blends the customer's own history with the payment method's population
    baseline. We deliberately do NOT read the simulator's hidden
    `customer_type` field here â€” in a real system that field doesn't exist,
    only observed behavior does. Reading it would be label leakage: the
    same mistake we must avoid with ML in Phase 5.
    """
    method_rate = historical_failure_rate_for_method(
        db, payment_method, exclude_transaction_id
    )
    customer_rate, sample_size = historical_failure_rate_for_customer(
        db, customer_id, exclude_transaction_id
    )

    if sample_size < MIN_SAMPLES_FOR_CUSTOMER_RATE:
        return method_rate

    # More history on this customer -> more weight on their own rate,
    # capped so the method baseline is never fully ignored.
    weight = min(sample_size / 20, 0.8)
    return weight * customer_rate + (1 - weight) * method_rate


def calculate_risk_score(
    failure_probability: float, amount: float, recovery_probability: float
) -> float:
    """
    RecoverAI's core prioritization formula:

        risk_score = failure_probability Ã— amount Ã— recovery_probability

    This is NOT plain "expected loss" (that would omit recovery_probability).
    It's "expected recoverable revenue" â€” a big, likely-recoverable failure
    scores higher than an equally likely failure that's hard to recover,
    because the system's job is deciding where to spend intervention effort.
    """
    return failure_probability * amount * recovery_probability

