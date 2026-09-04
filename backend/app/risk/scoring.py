from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import PaymentMethod, TransactionStatus
from app.models.models import Transaction


RECOVERY_PROBABILITY_BY_METHOD = {
    PaymentMethod.UPI: 0.55,
    PaymentMethod.CREDIT_CARD: 0.35,
    PaymentMethod.DEBIT_CARD: 0.40,
    PaymentMethod.NET_BANKING: 0.45,
    PaymentMethod.WALLET: 0.60,
}


MIN_SAMPLES_FOR_CUSTOMER_RATE = 5


def historical_failure_rate_for_method(
    db: Session, payment_method: PaymentMethod, exclude_transaction_id: int | None = None
) -> float:
    
    query = db.query(func.count(Transaction.id)).filter(
        Transaction.payment_method == payment_method
    )
    if exclude_transaction_id is not None:
        query = query.filter(Transaction.id != exclude_transaction_id)
    total = query.scalar()

    if not total:
        return 0.10  

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
    
    method_rate = historical_failure_rate_for_method(
        db, payment_method, exclude_transaction_id
    )
    customer_rate, sample_size = historical_failure_rate_for_customer(
        db, customer_id, exclude_transaction_id
    )

    if sample_size < MIN_SAMPLES_FOR_CUSTOMER_RATE:
        return method_rate

 
    weight = min(sample_size / 20, 0.8)
    return weight * customer_rate + (1 - weight) * method_rate


def calculate_risk_score(
    failure_probability: float, amount: float, recovery_probability: float
) -> float:
   
    return failure_probability * amount * recovery_probability

