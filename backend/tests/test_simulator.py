from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.enums import TransactionStatus
from app.simulator.generator import run_simulation

# Use an isolated in-memory database for tests so we never touch the real
# data/recoverai.db file, and each test run starts from a clean slate.
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine)


def setup_module(module):
    from app.models import models  # noqa: F401 registers tables on Base

    Base.metadata.create_all(bind=engine)


def test_simulation_generates_expected_counts():
    db = TestSession()
    try:
        merchant, customers, transactions = run_simulation(
            db, num_customers=50, num_transactions=300
        )
        assert merchant.id is not None
        assert len(customers) == 50
        assert len(transactions) == 300
    finally:
        db.close()


def test_all_transaction_amounts_are_positive():
    db = TestSession()
    try:
        _, _, transactions = run_simulation(db, num_customers=20, num_transactions=100)
        assert all(t.amount > 0 for t in transactions)
    finally:
        db.close()


def test_failure_rate_is_within_plausible_range():
    db = TestSession()
    try:
        _, _, transactions = run_simulation(
            db, num_customers=200, num_transactions=2000
        )
        failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
        failure_rate = len(failed) / len(transactions)
        # With our configured base rates and multipliers, overall failure
        # rate should land roughly between 5% and 20%. This is a sanity
        # check, not an exact assertion, since it's randomly generated.
        assert 0.05 < failure_rate < 0.20
    finally:
        db.close()
