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
    PolicyDecision,
    RecoveryAttempt,
    StrategyDecision,
    Transaction,
)
from app.policies.engine import (
    DENY,
    ESCALATE,
    ALLOW,
    evaluate_and_record_policy,
    evaluate_policy,
)
from app.strategy.definitions import STRATEGY_DEFINITIONS, StrategyParams


def make_test_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def make_merchant(db):
    merchant = Merchant(name="M")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def make_customer(db, merchant_id, opted_out=False):
    customer = Customer(
        merchant_id=merchant_id,
        name="A",
        email="a@example.com",
        customer_type=CustomerType.RELIABLE,
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


def test_allowed_retry():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.RETRY, 500.0)

        assert result.verdict == ALLOW
        assert result.reasons == []
    finally:
        db.close()


def test_retry_limit_exceeded():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        for _ in range(3):  # MAX_RETRIES
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

        assert result.verdict == DENY
        assert any("retry attempts" in r for r in result.reasons)
    finally:
        db.close()


def test_high_value_payment_escalates_not_denies():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id, amount=30_000.0)

        result = evaluate_policy(
            db, customer.id, txn.id, RecoveryStrategy.RETRY, 30_000.0
        )

        assert result.verdict == ESCALATE
        assert any("high-value" in r.lower() for r in result.reasons)
    finally:
        db.close()


def test_too_many_interventions_today():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        for _ in range(2):  # MAX_INTERVENTIONS_PER_CUSTOMER_PER_DAY
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
                    reasoning="prior",
                )
            )
        db.commit()

        result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.RETRY, 500.0)

        assert result.verdict == DENY
        assert any("interventions today" in r for r in result.reasons)
    finally:
        db.close()


def test_excessive_discount_is_denied():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        original = STRATEGY_DEFINITIONS[RecoveryStrategy.INCENTIVE]
        STRATEGY_DEFINITIONS[RecoveryStrategy.INCENTIVE] = StrategyParams(
            cost=10, probability_multiplier=1.20, amount_multiplier=0.80  # 20% discount
        )
        try:
            result = evaluate_policy(
                db, customer.id, txn.id, RecoveryStrategy.INCENTIVE, 500.0
            )
        finally:
            STRATEGY_DEFINITIONS[RecoveryStrategy.INCENTIVE] = original

        assert result.verdict == DENY
        assert any("discount" in r.lower() for r in result.reasons)
    finally:
        db.close()


def test_customer_opt_out_denies_customer_facing_strategy():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id, opted_out=True)
        txn = make_transaction(db, customer.id)

        result = evaluate_policy(
            db, customer.id, txn.id, RecoveryStrategy.INCENTIVE, 500.0
        )

        assert result.verdict == DENY
        assert any("opted out" in r.lower() for r in result.reasons)
    finally:
        db.close()


def test_opted_out_customer_can_still_get_a_non_customer_facing_retry():
    """
    Opting out means "don't contact me" — it should NOT block a silent
    payment retry, which never involves reaching out to the customer.
    """
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id, opted_out=True)
        txn = make_transaction(db, customer.id)

        result = evaluate_policy(db, customer.id, txn.id, RecoveryStrategy.RETRY, 500.0)

        assert result.verdict == ALLOW
    finally:
        db.close()


def test_invalid_action_is_denied():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        result = evaluate_policy(db, customer.id, txn.id, "not_a_real_strategy", 500.0)

        assert result.verdict == DENY
        assert any("not a recognized" in r for r in result.reasons)
    finally:
        db.close()


def test_deny_takes_precedence_over_escalate():
    """
    A transaction that is BOTH high-value (would escalate) AND at the
    retry limit (would deny) must come out DENY overall — a hard limit
    always wins over a soft "needs human review".
    """
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(
            db, customer.id, amount=30_000.0
        )  # high-value -> escalate

        for _ in range(3):  # also at retry limit -> deny
            db.add(
                RecoveryAttempt(
                    transaction_id=txn.id,
                    failure_type=FailureType.TRANSIENT,
                    succeeded=False,
                    amount_recovered=0.0,
                )
            )
        db.commit()

        result = evaluate_policy(
            db, customer.id, txn.id, RecoveryStrategy.RETRY, 30_000.0
        )

        assert result.verdict == DENY
    finally:
        db.close()


def test_agent_requested_approval_escalates():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        result = evaluate_policy(
            db,
            customer.id,
            txn.id,
            RecoveryStrategy.RETRY,
            500.0,
            requires_approval=True,
        )

        assert result.verdict == ESCALATE
    finally:
        db.close()


def test_evaluate_and_record_policy_persists_decision():
    db = make_test_session()
    try:
        merchant = make_merchant(db)
        customer = make_customer(db, merchant.id)
        txn = make_transaction(db, customer.id)

        decision = evaluate_and_record_policy(
            db, customer.id, txn.id, RecoveryStrategy.RETRY, 500.0
        )

        assert decision.verdict == ALLOW
        stored = db.query(PolicyDecision).all()
        assert len(stored) == 1
        assert stored[0].transaction_id == txn.id
    finally:
        db.close()
