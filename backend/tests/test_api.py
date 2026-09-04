import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
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
    RiskAssessment,
    StrategyDecision,
    Transaction,
)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, expire_on_commit=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True, scope="module")
def override_dependency():
   
    from app.models import models  

    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


client = TestClient(app)


def seed_one_processed_failure(db):
    merchant = Merchant(name="M")
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
        payment_method=PaymentMethod.UPI,
        amount=1000.0,
        status=TransactionStatus.FAILED,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    db.add(
        RiskAssessment(
            transaction_id=txn.id,
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=1000.0,
            failure_probability=0.1,
            recovery_probability=0.5,
            risk_score=50.0,
        )
    )
    db.add(
        StrategyDecision(
            transaction_id=txn.id,
            customer_id=customer.id,
            payment_method=PaymentMethod.UPI,
            amount=1000.0,
            strategy=RecoveryStrategy.RETRY,
            estimated_probability=0.5,
            cost=5,
            expected_value=100,
            reasoning="test",
        )
    )
    db.add(
        PolicyDecision(
            transaction_id=txn.id,
            customer_id=customer.id,
            strategy=RecoveryStrategy.RETRY,
            amount=1000.0,
            verdict="allow",
            reasons=[],
        )
    )
    db.commit()
    return txn


def test_list_transactions_returns_seeded_transaction():
    db = TestSession()
    txn = seed_one_processed_failure(db)
    db.close()

    response = client.get("/transactions")
    assert response.status_code == 200
    assert any(t["id"] == txn.id for t in response.json())


def test_get_transaction_by_id():
    db = TestSession()
    txn = seed_one_processed_failure(db)
    db.close()

    response = client.get(f"/transactions/{txn.id}")
    assert response.status_code == 200
    assert response.json()["id"] == txn.id


def test_get_transaction_404_for_unknown_id():
    response = client.get("/transactions/999999")
    assert response.status_code == 404


def test_audit_log_entry_combines_all_available_pieces():
    db = TestSession()
    txn = seed_one_processed_failure(db)
    db.close()

    response = client.get(f"/audit-log/{txn.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["transaction"]["id"] == txn.id
    assert data["risk_assessment"] is not None
    assert data["strategy_decision"] is not None
    assert data["policy_decision"] is not None
    assert data["agent_decision"] is None
    assert data["recovery_attempt"] is None


def test_audit_log_404_for_unknown_transaction():
    response = client.get("/audit-log/999999")
    assert response.status_code == 404


def test_audit_log_list_returns_entries():
    db = TestSession()
    seed_one_processed_failure(db)
    db.close()

    response = client.get("/audit-log")
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_metrics_endpoint_returns_expected_shape():
    db = TestSession()
    seed_one_processed_failure(db)
    db.close()

    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "revenue_processed" in data
    assert "recovery_rate" in data
    assert data["transactions_total"] >= 1
