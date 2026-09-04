from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.execution.executor import execute_strategy
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import Customer, Merchant, Transaction
from app.policies.constants import MAX_RETRIES
from app.policies.engine import DENY, evaluate_policy


def make_test_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models 

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def make_merchant(db):
    merchant = Merchant(name="M")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def make_customer(db, merchant_id):
    customer = Customer(
        merchant_id=merchant_id,
        name="A",
        email="a@example.com",
        customer_type=CustomerType.FREQUENTLY_FAILS,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def make_transaction(
    db, customer_id, amount=1500.0, payment_method=PaymentMethod.CREDIT_CARD
):
    txn = Transaction(
        customer_id=customer_id,
        payment_method=payment_method,
        amount=amount,
        status=TransactionStatus.FAILED,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def test_repeated_execution_naturally_hits_retry_limit():
   
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        for _ in range(MAX_RETRIES):
            execute_strategy(db, txn, customer, RecoveryStrategy.RETRY)

        result = evaluate_policy(
            db, customer.id, txn.id, RecoveryStrategy.RETRY, txn.amount
        )
        assert result.verdict == DENY
    finally:
        db.close()


def test_mixed_retry_family_strategies_share_the_same_limit():
    
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        execute_strategy(db, txn, customer, RecoveryStrategy.RETRY)
        execute_strategy(db, txn, customer, RecoveryStrategy.ALTERNATE_PAYMENT)
        execute_strategy(db, txn, customer, RecoveryStrategy.DELAYED_RETRY)

        result = evaluate_policy(
            db, customer.id, txn.id, RecoveryStrategy.RETRY, txn.amount
        )
        assert result.verdict == DENY
    finally:
        db.close()
