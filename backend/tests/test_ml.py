import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ml.features import build_recovery_dataset
from app.ml.train import prepare_features, train_and_evaluate
from app.models.enums import CustomerType, FailureType, PaymentMethod, TransactionStatus
from app.models.models import Customer, Merchant, RecoveryAttempt, Transaction


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
        name="Test",
        email="test@example.com",
        customer_type=CustomerType.RELIABLE,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def test_build_recovery_dataset_only_includes_failed_with_attempt():
    db = make_test_session()
    try:
        merchant = Merchant(name="M")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
        customer = _make_customer(db, merchant.id)

        success_txn = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=100.0,
            status=TransactionStatus.SUCCESS,
        )
        failed_with_attempt = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=200.0,
            status=TransactionStatus.FAILED,
        )
        failed_without_attempt = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=300.0,
            status=TransactionStatus.FAILED,
        )
        db.add_all([success_txn, failed_with_attempt, failed_without_attempt])
        db.commit()
        db.refresh(failed_with_attempt)

        db.add(
            RecoveryAttempt(
                transaction_id=failed_with_attempt.id,
                failure_type=FailureType.TRANSIENT,
                succeeded=True,
                amount_recovered=200.0,
            )
        )
        db.commit()

        df = build_recovery_dataset(db)
        assert len(df) == 1
        assert df.iloc[0]["transaction_id"] == failed_with_attempt.id
        assert df.iloc[0]["recovered"] == 1
    finally:
        db.close()


def test_dataset_features_do_not_leak_the_current_transaction():
    db = make_test_session()
    try:
        merchant = Merchant(name="M")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
        customer = _make_customer(db, merchant.id)

        first_failure = Transaction(
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=500.0,
            status=TransactionStatus.FAILED,
        )
        db.add(first_failure)
        db.commit()
        db.refresh(first_failure)

        db.add(
            RecoveryAttempt(
                transaction_id=first_failure.id,
                failure_type=FailureType.PERMANENT,
                succeeded=False,
                amount_recovered=0.0,
            )
        )
        db.commit()

        df = build_recovery_dataset(db)
        row = df.iloc[0]
        assert row["customer_prior_transactions"] == 0
        assert row["customer_fail_rate"] == 0.0
    finally:
        db.close()


def test_train_and_evaluate_runs_end_to_end_on_small_synthetic_data():
    import numpy as np

    rng = np.random.default_rng(42)
    n = 200
    methods = rng.choice([m.value for m in PaymentMethod], size=n)
    df = pd.DataFrame(
        {
            "amount": rng.lognormal(mean=6.5, sigma=0.6, size=n),
            "payment_method": methods,
            "customer_prior_transactions": rng.integers(0, 20, size=n),
            "customer_fail_rate": rng.uniform(0, 0.3, size=n),
            "customer_recovery_rate": rng.uniform(0.2, 0.8, size=n),
            "method_fail_rate": rng.uniform(0.05, 0.15, size=n),
            "method_recovery_rate": rng.uniform(0.3, 0.7, size=n),
            "recovered": rng.integers(0, 2, size=n),
        }
    )

    model, feature_names, report, cm, auc = train_and_evaluate(df, n_splits=5)

    assert 0.0 <= auc <= 1.0
    assert cm.shape == (2, 2)
    assert "amount" in feature_names
    assert any(name.startswith("method_") for name in feature_names)
