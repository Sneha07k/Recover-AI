from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum,
    JSON,
    Boolean,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    TransactionStatus,
    FailureType,
    RecoveryStrategy,
)


class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

    customers = relationship("Customer", back_populates="merchant")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    merchant_id = Column(
        Integer, ForeignKey("merchants.id"), nullable=False, index=True
    )
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    customer_type = Column(Enum(CustomerType), nullable=False)
    opted_out = Column(Boolean, nullable=False, default=False)

    merchant = relationship("Merchant", back_populates="customers")
    transactions = relationship("Transaction", back_populates="customer")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    customer_id = Column(
        Integer, ForeignKey("customers.id"), nullable=False, index=True
    )
    payment_method = Column(Enum(PaymentMethod), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    status = Column(Enum(TransactionStatus), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    recovered = Column(Boolean, nullable=False, default=False)
    recovered_amount = Column(Float, nullable=False, default=0.0)

    customer = relationship("Customer", back_populates="transactions")


class EventLog(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    customer_id = Column(
        Integer, ForeignKey("customers.id"), nullable=False, index=True
    )
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    amount = Column(Float, nullable=False)
    failure_probability = Column(Float, nullable=False)
    recovery_probability = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    strategy = Column(Enum(RecoveryStrategy), nullable=True)
    failure_type = Column(Enum(FailureType), nullable=False)
    succeeded = Column(Boolean, nullable=False)
    amount_recovered = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class StrategyDecision(Base):
    __tablename__ = "strategy_decisions"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    customer_id = Column(
        Integer, ForeignKey("customers.id"), nullable=False, index=True
    )
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    amount = Column(Float, nullable=False)
    strategy = Column(Enum(RecoveryStrategy), nullable=False)
    estimated_probability = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    expected_value = Column(Float, nullable=False)
    reasoning = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    customer_id = Column(
        Integer, ForeignKey("customers.id"), nullable=False, index=True
    )
    action = Column(Enum(RecoveryStrategy), nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    requires_approval = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    customer_id = Column(
        Integer, ForeignKey("customers.id"), nullable=False, index=True
    )
    strategy = Column(Enum(RecoveryStrategy), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    verdict = Column(String, nullable=False)
    reasons = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExperimentResult(Base):
    __tablename__ = "experiment_results"

    id = Column(Integer, primary_key=True)
    condition = Column(String, nullable=False, index=True)
    transaction_id = Column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    strategy = Column(Enum(RecoveryStrategy), nullable=False)
    policy_verdict = Column(String, nullable=False)
    executed = Column(Boolean, nullable=False)
    succeeded = Column(Boolean, nullable=False)
    amount_recovered = Column(Float, nullable=False, default=0.0)
    cost = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RazorpayPaymentLink(Base):
    """
    A REAL Razorpay test-mode Payment Link created for a customer-facing
    recovery strategy (INCENTIVE, CUSTOMER_REMINDER). This is a verifiable
    side-artifact only — RecoverAI's simulator (Phase 9) remains the sole
    source of truth for whether the recovery succeeded. Nothing in this
    table is ever read back to decide simulated outcomes.
    """

    __tablename__ = "razorpay_payment_links"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    strategy = Column(Enum(RecoveryStrategy), nullable=False)
    amount_paise = Column(Integer, nullable=False)
    razorpay_payment_link_id = Column(String, nullable=False)
    short_url = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
