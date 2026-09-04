from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.enums import CustomerType, PaymentMethod, TransactionStatus
from app.models.models import Customer, Merchant, RiskAssessment, Transaction
from app.risk.engine import assess_risk_on_payment_failed
from app.risk.scoring import calculate_risk_score, historical_failure_rate_for_method


def make_test_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models  

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_calculate_risk_score_is_pure_multiplication():
    score = calculate_risk_score(
        failure_probability=0.2, amount=1000, recovery_probability=0.5
    )
    assert score == 100.0 


def test_historical_failure_rate_for_method_falls_back_when_no_data():
    db = make_test_session()
    try:
        rate = historical_failure_rate_for_method(db, PaymentMethod.UPI)
        assert rate == 0.10
    finally:
        db.close()


def test_historical_failure_rate_for_method_reflects_real_data():
    db = make_test_session()
    try:
        merchant = Merchant(name="Test Merchant")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)

        customer = Customer(
            merchant_id=merchant.id,
            name="A",
            email="a@example.com",
            customer_type=CustomerType.RELIABLE,
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

       
        for i in range(10):
            status = TransactionStatus.FAILED if i < 2 else TransactionStatus.SUCCESS
            db.add(
                Transaction(
                    customer_id=customer.id,
                    payment_method=PaymentMethod.UPI,
                    amount=100.0,
                    status=status,
                )
            )
        db.commit()

        rate = historical_failure_rate_for_method(db, PaymentMethod.UPI)
        assert abs(rate - 0.2) < 1e-6
    finally:
        db.close()


def test_assess_risk_on_payment_failed_persists_assessment():
    db = make_test_session()
    try:
        merchant = Merchant(name="Test Merchant")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)

        customer = Customer(
            merchant_id=merchant.id,
            name="A",
            email="a@example.com",
            customer_type=CustomerType.RELIABLE,
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

        txn = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.CREDIT_CARD,
            amount=5000.0,
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
                "amount": 5000.0,
                "payment_method": PaymentMethod.CREDIT_CARD.value,
                "customer_id": customer.id,
            },
        )

        assessment = assess_risk_on_payment_failed(db, event)

        assert assessment.transaction_id == txn.id
        assert assessment.risk_score > 0
        stored = db.query(RiskAssessment).all()
        assert len(stored) == 1
    finally:
        db.close()
