from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.enums import (
    CustomerType,
    FailureType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import (
    Customer,
    Merchant,
    RecoveryAttempt,
    StrategyDecision,
    Transaction,
)
from app.policies.engine import evaluate_policy


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_customer(db, merchant_id, opted_out=False):
    customer = Customer(
        merchant_id=merchant_id,
        name="Demo Customer",
        email="demo@example.com",
        customer_type=CustomerType.RELIABLE,
        opted_out=opted_out,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def make_transaction(db, customer_id, amount, payment_method=PaymentMethod.UPI):
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


def show(label, result):
    print(f"\n{label}")
    print(f"  Verdict: {result.verdict.upper()}")
    for reason in result.reasons:
        print(f"  - {reason}")
    if not result.reasons:
        print("  (all checks passed)")


def main():
    db = make_session()
    merchant = Merchant(name="Demo Merchant")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

   
    customer = make_customer(db, merchant.id)
    txn = make_transaction(db, customer.id, amount=500.0)
    result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.RETRY, 500.0)
    show("1. Allowed retry", result)

    
    customer = make_customer(db, merchant.id)
    txn = make_transaction(db, customer.id, amount=500.0)
    for _ in range(3):
        db.add(
            RecoveryAttempt(
                transaction_id=txn.id,
                failure_type=FailureType.TRANSIENT,
                succeeded=False,
                amount_recovered=0.0,
            )
        )
    db.commit()
    result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.RETRY, 500.0)
    show("2. Retry limit exceeded", result)

    
    customer = make_customer(db, merchant.id)
    txn = make_transaction(db, customer.id, amount=30_000.0)
    result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.RETRY, 30_000.0)
    show("3. High-value payment", result)

   
    customer = make_customer(db, merchant.id)
    txn = make_transaction(db, customer.id, amount=500.0)
    for _ in range(2):
        db.add(
            StrategyDecision(
                transaction_id=txn.id,
                customer_id=customer.id,
                payment_method=PaymentMethod.UPI,
                amount=500.0,
                strategy=RecoveryStrategy.RETRY,
                estimated_probability=0.5,
                cost=5,
                expected_value=100,
                reasoning="prior intervention",
            )
        )
    db.commit()
    result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.RETRY, 500.0)
    show("4. Too many interventions today", result)

    
    from app.strategy.definitions import STRATEGY_DEFINITIONS, StrategyParams

    original = STRATEGY_DEFINITIONS[RecoveryStrategy.INCENTIVE]
    STRATEGY_DEFINITIONS[RecoveryStrategy.INCENTIVE] = StrategyParams(
        cost=10, probability_multiplier=1.20, amount_multiplier=0.80  # 20% discount
    )
    customer = make_customer(db, merchant.id)
    txn = make_transaction(db, customer.id, amount=500.0)
    result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.INCENTIVE, 500.0)
    show("5. Excessive discount", result)
    STRATEGY_DEFINITIONS[RecoveryStrategy.INCENTIVE] = original  # restore

    
    customer = make_customer(db, merchant.id, opted_out=True)
    txn = make_transaction(db, customer.id, amount=500.0)
    result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.INCENTIVE, 500.0)
    show("6. Customer opt-out", result)

    
    customer = make_customer(db, merchant.id)
    txn = make_transaction(db, customer.id, amount=500.0)
    result = evaluate_policy(db, customer.id, txn.id, "teleport_the_money", 500.0)
    show("7. Invalid action", result)


if __name__ == "__main__":
    main()
