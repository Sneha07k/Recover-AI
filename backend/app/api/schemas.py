from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    FailureType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    payment_method: PaymentMethod
    amount: float
    status: TransactionStatus
    recovered: bool
    recovered_amount: float
    created_at: datetime


class RiskAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    customer_id: int
    payment_method: PaymentMethod
    amount: float
    failure_probability: float
    recovery_probability: float
    risk_score: float
    created_at: datetime


class StrategyDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    customer_id: int
    strategy: RecoveryStrategy
    estimated_probability: float
    cost: float
    expected_value: float
    reasoning: str
    created_at: datetime


class AgentDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    customer_id: int
    action: RecoveryStrategy
    confidence: float
    reason: str
    requires_approval: bool
    created_at: datetime


class PolicyDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    customer_id: int
    strategy: RecoveryStrategy
    amount: float
    verdict: str
    reasons: list[str]
    created_at: datetime


class RecoveryAttemptOut(BaseModel):
   

    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    strategy: Optional[RecoveryStrategy]
    failure_type: FailureType
    succeeded: bool
    amount_recovered: float
    created_at: datetime


class AuditTrailEntry(BaseModel):
    

    transaction: TransactionOut
    risk_assessment: Optional[RiskAssessmentOut] = None
    strategy_decision: Optional[StrategyDecisionOut] = None
    agent_decision: Optional[AgentDecisionOut] = None
    policy_decision: Optional[PolicyDecisionOut] = None
    recovery_attempt: Optional[RecoveryAttemptOut] = None
