import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.integrations.razorpay_client import create_recovery_payment_link
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import Customer, Merchant, RazorpayPaymentLink, Transaction


def make_test_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


class FakePaymentLinkResource:
    """
    Mimics razorpay.Client().payment_link — records what it was called
    with, and returns a response shaped exactly like Razorpay's real
    documented response (see create-standard payment link API reference).
    """

    def __init__(self):
        self.last_payload = None

    def create(self, payload):
        self.last_payload = payload
        return {
            "id": "plink_FAKE123",
            "short_url": "https://rzp.io/i/fake123",
            "status": "created",
            "amount": payload["amount"],
            "currency": payload["currency"],
        }


class FakeRazorpayClient:
    def __init__(self):
        self.payment_link = FakePaymentLinkResource()


def _make_transaction_and_customer(db, amount=1000.0, payment_method=PaymentMethod.UPI):
    merchant = Merchant(name="M")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    customer = Customer(
        merchant_id=merchant.id,
        name="Test Customer",
        email="test@example.com",
        customer_type=CustomerType.RELIABLE,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    txn = Transaction(
        customer_id=customer.id,
        payment_method=payment_method,
        amount=amount,
        status=TransactionStatus.FAILED,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    return txn, customer


def test_rejects_non_customer_facing_strategy():
    db = make_test_session()
    try:
        txn, customer = _make_transaction_and_customer(db)
        fake_client = FakeRazorpayClient()

        with pytest.raises(ValueError):
            create_recovery_payment_link(
                db, txn, customer, RecoveryStrategy.RETRY, client=fake_client
            )
    finally:
        db.close()


def test_converts_amount_to_paise_correctly():
    db = make_test_session()
    try:
        txn, customer = _make_transaction_and_customer(db, amount=1000.0)
        fake_client = FakeRazorpayClient()

        create_recovery_payment_link(
            db, txn, customer, RecoveryStrategy.CUSTOMER_REMINDER, client=fake_client
        )

        # CUSTOMER_REMINDER has amount_multiplier=1.0, so 1000.00 rupees
        # should become exactly 100000 paise.
        assert fake_client.payment_link.last_payload["amount"] == 100000
    finally:
        db.close()


def test_incentive_discount_reduces_link_amount():
    db = make_test_session()
    try:
        txn, customer = _make_transaction_and_customer(db, amount=1000.0)
        fake_client = FakeRazorpayClient()

        create_recovery_payment_link(
            db, txn, customer, RecoveryStrategy.INCENTIVE, client=fake_client
        )

        # INCENTIVE has amount_multiplier=0.90 -> 900.00 rupees -> 90000 paise
        assert fake_client.payment_link.last_payload["amount"] == 90000
    finally:
        db.close()


def test_notifications_are_always_disabled():
    """
    Safety check: our simulated customers have fake contact details.
    Notifications and reminders must never be enabled, even accidentally.
    """
    db = make_test_session()
    try:
        txn, customer = _make_transaction_and_customer(db)
        fake_client = FakeRazorpayClient()

        create_recovery_payment_link(
            db, txn, customer, RecoveryStrategy.INCENTIVE, client=fake_client
        )

        payload = fake_client.payment_link.last_payload
        assert payload["notify"]["sms"] is False
        assert payload["notify"]["email"] is False
        assert payload["reminder_enable"] is False
    finally:
        db.close()


def test_reference_id_includes_transaction_id():
    db = make_test_session()
    try:
        txn, customer = _make_transaction_and_customer(db)
        fake_client = FakeRazorpayClient()

        create_recovery_payment_link(
            db, txn, customer, RecoveryStrategy.INCENTIVE, client=fake_client
        )

        assert (
            f"recoverai-{txn.id}-"
            in fake_client.payment_link.last_payload["reference_id"]
        )
    finally:
        db.close()


def test_persists_payment_link_record():
    db = make_test_session()
    try:
        txn, customer = _make_transaction_and_customer(db)
        fake_client = FakeRazorpayClient()

        link = create_recovery_payment_link(
            db, txn, customer, RecoveryStrategy.CUSTOMER_REMINDER, client=fake_client
        )

        assert link.razorpay_payment_link_id == "plink_FAKE123"
        assert link.short_url == "https://rzp.io/i/fake123"
        assert link.status == "created"

        stored = db.query(RazorpayPaymentLink).all()
        assert len(stored) == 1
        assert stored[0].transaction_id == txn.id
    finally:
        db.close()
