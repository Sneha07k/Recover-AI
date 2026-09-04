from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.execution.controller import (
    ESCALATED,
    EXECUTED,
    STOPPED_BY_POLICY,
    STOPPED_BY_STRATEGY,
    categorize_outcome,
    run_closed_loop,
)
from app.execution.executor import execute_strategy
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import (
    Customer,
    Merchant,
    PolicyDecision,
    RecoveryAttempt,
    Transaction,
)
from app.policies.engine import ALLOW, DENY, ESCALATE


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


def make_customer(
    db, merchant_id, customer_type=CustomerType.RELIABLE, opted_out=False
):
    customer = Customer(
        merchant_id=merchant_id,
        name="A",
        email="a@example.com",
        customer_type=customer_type,
        opted_out=opted_out,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def make_transaction(db, customer_id, amount=500.0, payment_method=PaymentMethod.UPI):
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




def test_categorize_stop_strategy_regardless_of_verdict():
    assert categorize_outcome(RecoveryStrategy.STOP, ALLOW) == STOPPED_BY_STRATEGY


def test_categorize_escalation_strategy_is_escalated():
    assert categorize_outcome(RecoveryStrategy.ESCALATION, ALLOW) == ESCALATED


def test_categorize_escalate_verdict_is_escalated_even_for_retry():
    assert categorize_outcome(RecoveryStrategy.RETRY, ESCALATE) == ESCALATED


def test_categorize_deny_is_stopped_by_policy():
    assert categorize_outcome(RecoveryStrategy.RETRY, DENY) == STOPPED_BY_POLICY


def test_categorize_allow_retry_is_executed():
    assert categorize_outcome(RecoveryStrategy.RETRY, ALLOW) == EXECUTED



def test_execute_strategy_persists_recovery_attempt_with_strategy():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id, amount=1000.0)

        attempt = execute_strategy(db, txn, customer, RecoveryStrategy.RETRY)

        assert attempt.strategy == RecoveryStrategy.RETRY
        assert attempt.transaction_id == txn.id
        stored = db.query(RecoveryAttempt).all()
        assert len(stored) == 1
    finally:
        db.close()


def test_execute_strategy_updates_transaction_when_successful():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id, customer_type=CustomerType.RELIABLE)
        txn = make_transaction(
            db, customer.id, amount=1000.0, payment_method=PaymentMethod.UPI
        )

        attempt = execute_strategy(
            db, txn, customer, RecoveryStrategy.ALTERNATE_PAYMENT
        )

        if attempt.succeeded:
            assert txn.recovered is True
            assert txn.recovered_amount == attempt.amount_recovered
            assert attempt.amount_recovered > 0
        else:
            assert txn.recovered is False
            assert txn.recovered_amount == 0.0
    finally:
        db.close()


def test_execute_strategy_incentive_recovers_discounted_amount():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id, customer_type=CustomerType.RELIABLE)
        txn = make_transaction(
            db, customer.id, amount=1000.0, payment_method=PaymentMethod.UPI
        )

        succeeded_once = False
        for _ in range(20):
            fresh_txn = make_transaction(
                db, customer.id, amount=1000.0, payment_method=PaymentMethod.UPI
            )
            attempt = execute_strategy(
                db, fresh_txn, customer, RecoveryStrategy.INCENTIVE
            )
            if attempt.succeeded:
                assert attempt.amount_recovered == 900.0
                succeeded_once = True
                break
        assert (
            succeeded_once
        ), "Expected at least one successful incentive recovery in 20 tries"
    finally:
        db.close()



def test_closed_loop_denies_when_retry_limit_already_hit():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(
            db, customer.id, amount=500.0, payment_method=PaymentMethod.CREDIT_CARD
        )

        from app.models.enums import FailureType

        for _ in range(3):
            db.add(
                RecoveryAttempt(
                    transaction_id=txn.id,
                    strategy=RecoveryStrategy.RETRY,
                    failure_type=FailureType.PERMANENT,
                    succeeded=False,
                    amount_recovered=0.0,
                )
            )
        db.commit()

        outcome = run_closed_loop(
            db, txn.id, customer.id, PaymentMethod.CREDIT_CARD, 500.0
        )

        stored_attempts = (
            db.query(RecoveryAttempt)
            .filter(RecoveryAttempt.transaction_id == txn.id)
            .count()
        )
        assert stored_attempts <= 4
    finally:
        db.close()


def test_closed_loop_escalates_high_value_transaction():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id, amount=30_000.0)

        outcome = run_closed_loop(db, txn.id, customer.id, PaymentMethod.UPI, 30_000.0)

        assert outcome["bucket"] == ESCALATED
        assert "succeeded" not in outcome
        assert db.query(RecoveryAttempt).count() == 0
    finally:
        db.close()


def test_closed_loop_records_policy_decision():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id, amount=500.0)

        run_closed_loop(db, txn.id, customer.id, PaymentMethod.UPI, 500.0)

        stored = (
            db.query(PolicyDecision)
            .filter(PolicyDecision.transaction_id == txn.id)
            .all()
        )
        assert len(stored) == 1
    finally:
        db.close()
