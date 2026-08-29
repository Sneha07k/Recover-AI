from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, JSON, Boolean
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.enums import CustomerType, PaymentMethod, TransactionStatus, FailureType, RecoveryStrategy


class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

    customers = relationship("Customer", back_populates="merchant")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    customer_type = Column(Enum(CustomerType), nullable=False)

    merchant = relationship("Merchant", back_populates="customers")
    transactions = relationship("Transaction", back_populates="customer")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(Enum(TransactionStatus), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    customer = relationship("Customer", back_populates="transactions")


class EventLog(Base):
    """
    Persisted record of every event published on the event bus â€” the raw
    material for the audit trail we build properly in Phase 10.
    """
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RiskAssessment(Base):
    """
    One deterministic risk assessment produced for a failed transaction:
    how likely it was to fail, how much money is involved, how likely a
    recovery action is to succeed, and the combined priority score.
    """
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    amount = Column(Float, nullable=False)
    failure_probability = Column(Float, nullable=False)
    recovery_probability = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RecoveryAttempt(Base):
    """
    Records the outcome of a (simplified, unconditional) retry made on a
    failed transaction. This is the historical, labeled data we need to
    train the recovery-prediction model in Phase 5. failure_type is the
    simulator's hidden ground truth â€” it must NEVER be used as a model
    feature, only to generate this training label.
    """
    __tablename__ = "recovery_attempts"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    failure_type = Column(Enum(FailureType), nullable=False)
    succeeded = Column(Boolean, nullable=False)
    amount_recovered = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class StrategyDecision(Base):
    """
    A recommended recovery strategy and the expected-value reasoning
    behind it, for one failed transaction. Nothing is executed here â€”
    this is a recommendation only. Phase 8 adds policy gating; Phase 9
    wires in real execution.
    """
    __tablename__ = "strategy_decisions"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    amount = Column(Float, nullable=False)
    strategy = Column(Enum(RecoveryStrategy), nullable=False)
    estimated_probability = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    expected_value = Column(Float, nullable=False)
    reasoning = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentDecision(Base):
    """
    A recovery decision produced by the LLM agent for an AMBIGUOUS case
    only (see app/agents/ambiguity.py) â€” most failures never reach this
    table because Phase 6's deterministic engine already handles them.
    This is still just a proposal: nothing is executed here either.
    """
    __tablename__ = "agent_decisions"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    action = Column(Enum(RecoveryStrategy), nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    requires_approval = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

