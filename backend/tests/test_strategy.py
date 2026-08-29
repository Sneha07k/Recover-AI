from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import Customer, Merchant, StrategyDecision, Transaction
from app.strategy.definitions import STRATEGY_DEFINITIONS
from app.strategy.engine import recommend_strategy, recommend_strategy_on_payment_failed
from app.strategy.probability import build_live_features


def make_test_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401 registers tables on Base

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _make_customer(db, merchant_id):
    customer = Customer(
        merchant_id=merchant_id,
        name="A",
        email="a@example.com",
        customer_type=CustomerType.RELIABLE,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def test_stop_strategy_always_has_zero_cost_and_zero_probability_multiplier():
    stop = STRATEGY_DEFINITIONS[RecoveryStrategy.STOP]
    assert stop.cost == 0
    assert stop.probability_multiplier == 0.0


def test_build_live_features_excludes_current_transaction():
    db = make_test_session()
    try:
        merchant = Merchant(name="M")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
        customer = _make_customer(db, merchant.id)

        txn = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=500.0,
            status=TransactionStatus.FAILED,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        features = build_live_features(
            db, customer.id, PaymentMethod.UPI, 500.0, exclude_transaction_id=txn.id
        )
        assert features["customer_prior_transactions"] == 0
        assert features["amount"] == 500.0
        assert features["payment_method"] == "upi"
    finally:
        db.close()


def test_recommend_strategy_never_has_negative_expected_value():
    db = make_test_session()
    try:
        merchant = Merchant(name="M")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
        customer = _make_customer(db, merchant.id)

        txn = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.CREDIT_CARD,
            amount=50.0,
            status=TransactionStatus.FAILED,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        recommendation = recommend_strategy(
            db, txn.id, customer.id, PaymentMethod.CREDIT_CARD, 50.0
        )

        assert recommendation.expected_value >= 0.0
        assert recommendation.cost == STRATEGY_DEFINITIONS[recommendation.strategy].cost
    finally:
        db.close()


def test_recommend_strategy_on_payment_failed_persists_decision():
    db = make_test_session()
    try:
        merchant = Merchant(name="M")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
        customer = _make_customer(db, merchant.id)

        txn = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=2000.0,
            status=TransactionStatus.FAILED,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        event = Event(
            event_type=EventType.PAYMENT_FAILED,
            entity_type="transaction",
            entity_id=txn.id,
            payload={
                "amount": 2000.0,
                "payment_method": PaymentMethod.UPI.value,
                "customer_id": customer.id,
            },
        )

        decision = recommend_strategy_on_payment_failed(db, event)

        assert decision.transaction_id == txn.id
        stored = db.query(StrategyDecision).all()
        assert len(stored) == 1
        assert stored[0].strategy in list(RecoveryStrategy)
    finally:
        db.close()
