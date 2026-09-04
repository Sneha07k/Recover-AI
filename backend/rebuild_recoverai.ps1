

New-Item -ItemType Directory -Force -Path 'app' | Out-Null
@'

'@ | Set-Content -Path 'app/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/agents' | Out-Null
@'

'@ | Set-Content -Path 'app/agents/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/agents' | Out-Null
@'
from app.policies.constants import HIGH_VALUE_TRANSACTION_THRESHOLD
from app.strategy.engine import StrategyRecommendation


def is_ambiguous(
    recommendation: StrategyRecommendation, amount: float, close_call_ratio: float = 0.15
) -> bool:
    
    sorted_candidates = sorted(recommendation.candidates, key=lambda c: c[3], reverse=True)
    if len(sorted_candidates) < 2:
        return False

    top_ev = sorted_candidates[0][3]
    second_ev = sorted_candidates[1][3]
    close_call = abs(top_ev - second_ev) < close_call_ratio * max(amount, 1)
    high_value = amount > HIGH_VALUE_TRANSACTION_THRESHOLD

    return close_call or high_value

'@ | Set-Content -Path 'app/agents/ambiguity.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/agents' | Out-Null
@'
import json

from app.agents.tools import TOOLS
from app.config import settings

# Groq's flagship tool-calling-capable model at time of writing. Check
# https://console.groq.com/docs/models for current options if this changes.
MODEL = "llama-3.3-70b-versatile"
MAX_TURNS = 6


def _build_client():
    from groq import Groq

    return Groq(api_key=settings.GROQ_API_KEY)


def run_agent_loop(
    system_prompt: str,
    user_message: str,
    tool_executor: dict,
    client=None,
    max_turns: int = MAX_TURNS,
) -> dict:
   
    if client is None:
        client = _build_client()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1024,
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            raise RuntimeError(
                "Agent ended its turn without calling a tool or submitting a decision."
            )

       
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ],
            }
        )

        submitted_decision = None
        for call in tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments)

            if name == "submit_recovery_decision":
                submitted_decision = args
                continue

            result = tool_executor[name](args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )

        if submitted_decision is not None:
            return submitted_decision

    raise RuntimeError(f"Agent did not submit a decision within {max_turns} turns.")

'@ | Set-Content -Path 'app/agents/client.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/agents' | Out-Null
@'
from sqlalchemy.orm import Session

from app.agents.client import run_agent_loop
from app.agents.schemas import AgentDecisionResult
from app.agents.tools import build_tool_executor
from app.models.enums import PaymentMethod
from app.models.models import AgentDecision

SYSTEM_PROMPT = """You are RecoverAI's recovery decision agent.

A payment has failed and RecoverAI's deterministic engine found this case
ambiguous enough to warrant your judgment. Use the provided tools to gather
whatever context you need about the transaction and customer before
deciding.

When you are ready, call submit_recovery_decision exactly once with your
final action, your confidence (0-1), your reason, and whether the decision
requires human approval before it can be acted on.

IMPORTANT: you are proposing a decision only. You do not execute payments,
retries, or discounts yourself, and nothing you submit takes effect until
it passes through RecoverAI's separate policy engine. Do not assume your
decision will be approved."""


def make_agent_decision(
    db: Session,
    transaction_id: int,
    customer_id: int,
    payment_method: PaymentMethod,
    amount: float,
    client=None,
) -> AgentDecision:
    tool_executor = build_tool_executor(db)

    user_message = (
        f"Transaction {transaction_id} failed. "
        f"customer_id={customer_id}, payment_method={payment_method.value}, "
        f"amount={amount}. Decide on the best recovery action."
    )

    raw_result = run_agent_loop(SYSTEM_PROMPT, user_message, tool_executor, client=client)

   
    validated = AgentDecisionResult.model_validate(raw_result)

    decision = AgentDecision(
        transaction_id=transaction_id,
        customer_id=customer_id,
        action=validated.action,
        confidence=validated.confidence,
        reason=validated.reason,
        requires_approval=validated.requires_approval,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision

'@ | Set-Content -Path 'app/agents/engine.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/agents' | Out-Null
@'
from pydantic import BaseModel, Field

from app.models.enums import RecoveryStrategy


class AgentDecisionResult(BaseModel):
    

    action: RecoveryStrategy
    confidence: float = Field(ge=0, le=1)
    reason: str
    requires_approval: bool

'@ | Set-Content -Path 'app/agents/schemas.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/agents' | Out-Null
@'
from sqlalchemy.orm import Session

from app.models.enums import PaymentMethod
from app.models.models import Transaction
from app.policies.constants import HIGH_VALUE_TRANSACTION_THRESHOLD, MAX_AUTOMATED_RECOVERY_AMOUNT
from app.risk.scoring import historical_failure_rate_for_customer
from app.strategy.probability import predict_recovery_probability


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_transaction",
            "description": "Look up a transaction's amount, payment method, and status.",
            "parameters": {
                "type": "object",
                "properties": {"transaction_id": {"type": "integer"}},
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_history",
            "description": "Get a customer's transaction count and historical failure rate so far.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "integer"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_recovery_probability",
            "description": (
                "Estimate the probability a recovery attempt succeeds for a "
                "given customer, payment method, and amount, using RecoverAI's "
                "trained model (or rule-based fallback if no model is trained)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "payment_method": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["customer_id", "payment_method", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_policy_preview",
            "description": (
                "Non-binding PREVIEW of whether a strategy is likely within policy "
                "limits. This is NOT the final policy check — RecoverAI's real "
                "policy engine (Phase 8) always re-checks before anything executes, "
                "and this preview cannot authorize any action."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["strategy", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_recovery_decision",
            "description": (
                "Submit your final recovery decision. Call this exactly once, "
                "after you've gathered the information you need. This does NOT "
                "execute anything — it only records your proposed decision."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "retry",
                            "delayed_retry",
                            "alternate_payment",
                            "incentive",
                            "customer_reminder",
                            "escalation",
                            "stop",
                        ],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                    "requires_approval": {"type": "boolean"},
                },
                "required": ["action", "confidence", "reason", "requires_approval"],
            },
        },
    },
]


def build_tool_executor(db: Session) -> dict:
    

    def get_transaction(tool_input: dict) -> dict:
        txn = db.get(Transaction, tool_input["transaction_id"])
        if txn is None:
            return {"error": "transaction not found"}
        return {
            "transaction_id": txn.id,
            "amount": txn.amount,
            "payment_method": txn.payment_method.value,
            "status": txn.status.value,
        }

    def get_customer_history(tool_input: dict) -> dict:
        customer_id = tool_input["customer_id"]
        fail_rate, total = historical_failure_rate_for_customer(db, customer_id)
        return {
            "customer_id": customer_id,
            "total_transactions": total,
            "historical_failure_rate": round(fail_rate, 3),
        }

    def estimate_recovery_probability(tool_input: dict) -> dict:
        probability = predict_recovery_probability(
            db,
            tool_input["customer_id"],
            PaymentMethod(tool_input["payment_method"]),
            tool_input["amount"],
        )
        return {"estimated_recovery_probability": round(probability, 3)}

    def check_policy_preview(tool_input: dict) -> dict:
        strategy = tool_input["strategy"]
        amount = tool_input["amount"]
        compliant = True
        reason = "Within preview thresholds."

        if strategy == "incentive" and amount > MAX_AUTOMATED_RECOVERY_AMOUNT:
            compliant = False
            reason = "Incentives on high-value transactions typically need approval."
        if amount > HIGH_VALUE_TRANSACTION_THRESHOLD:
            compliant = False
            reason = "High-value transaction — likely requires human approval."

        return {
            "compliant": compliant,
            "reason": reason,
            "note": "Preview only — not binding. Phase 8's policy engine has final authority.",
        }

    return {
        "get_transaction": get_transaction,
        "get_customer_history": get_customer_history,
        "estimate_recovery_probability": estimate_recovery_probability,
        "check_policy_preview": check_policy_preview,
    }

'@ | Set-Content -Path 'app/agents/tools.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/analytics' | Out-Null
@'

'@ | Set-Content -Path 'app/analytics/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/api' | Out-Null
@'

'@ | Set-Content -Path 'app/api/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app' | Out-Null
@'
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    

    model_config = SettingsConfigDict(env_file=".env")

    APP_NAME: str = "RecoverAI"
    ENVIRONMENT: str = "development"

    
    GROQ_API_KEY: str = ""


# Created once, imported everywhere else that needs config.
settings = Settings()

'@ | Set-Content -Path 'app/config.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app' | Out-Null
@'
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


Base = declarative_base()


def init_db():
   
    from app.models import models  # noqa: F401 (import registers the tables)

    Base.metadata.create_all(bind=engine)


def get_db():
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

'@ | Set-Content -Path 'app/database.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/events' | Out-Null
@'

'@ | Set-Content -Path 'app/events/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/events' | Out-Null
@'
from collections import defaultdict
from typing import Callable

from sqlalchemy.orm import Session

from app.events.enums import EventType
from app.events.schemas import Event
from app.models.models import EventLog


class EventBus:
    

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable[[Session, Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Callable[[Session, Event], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, db: Session, event: Event) -> None:
       
        record = EventLog(
            event_type=event.event_type.value,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            payload=event.payload,
            created_at=event.created_at,
        )
        db.add(record)
        db.commit()

        for handler in self._subscribers[event.event_type]:
            handler(db, event)



event_bus = EventBus()

'@ | Set-Content -Path 'app/events/bus.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/events' | Out-Null
@'
import logging

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.risk.engine import assess_risk_on_payment_failed
from app.strategy.engine import recommend_strategy_on_payment_failed

logger = logging.getLogger("recoverai.events")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def log_payment_failed(db, event: Event) -> None:
   
    txn_id = event.entity_id
    amount = event.payload.get("amount")
    method = event.payload.get("payment_method")
    logger.info(f"[event] PAYMENT_FAILED txn={txn_id} amount={amount} method={method}")


def register_default_consumers() -> None:
    event_bus.subscribe(EventType.PAYMENT_FAILED, log_payment_failed)
    event_bus.subscribe(EventType.PAYMENT_FAILED, assess_risk_on_payment_failed)
    event_bus.subscribe(EventType.PAYMENT_FAILED, recommend_strategy_on_payment_failed)

'@ | Set-Content -Path 'app/events/consumers.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/events' | Out-Null
@'
import enum


class EventType(str, enum.Enum):
    PAYMENT_CREATED = "payment_created"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    CHECKOUT_STARTED = "checkout_started"
    CHECKOUT_ABANDONED = "checkout_abandoned"
    SUBSCRIPTION_FAILED = "subscription_failed"
    INVOICE_OVERDUE = "invoice_overdue"
    RECOVERY_ATTEMPTED = "recovery_attempted"
    RECOVERY_SUCCESS = "recovery_success"
    RECOVERY_FAILED = "recovery_failed"

'@ | Set-Content -Path 'app/events/enums.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/events' | Out-Null
@'
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.events.enums import EventType


class Event(BaseModel):
   

    event_type: EventType
    entity_type: str
    entity_id: int
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

'@ | Set-Content -Path 'app/events/schemas.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app' | Out-Null
@'
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings
from app.database import get_db

app = FastAPI(title=settings.APP_NAME)


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }

'@ | Set-Content -Path 'app/main.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/ml' | Out-Null
@'

'@ | Set-Content -Path 'app/ml/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/ml' | Out-Null
@'
from collections import defaultdict

import pandas as pd
from sqlalchemy.orm import Session

from app.models.enums import TransactionStatus
from app.models.models import RecoveryAttempt, Transaction


def build_recovery_dataset(db: Session) -> pd.DataFrame:
    
    transactions = db.query(Transaction).order_by(Transaction.id.asc()).all()
    attempts_by_txn = {a.transaction_id: a for a in db.query(RecoveryAttempt).all()}

    customer_seen = defaultdict(int)
    customer_failed = defaultdict(int)
    customer_recovery_attempts = defaultdict(int)
    customer_recovery_success = defaultdict(int)

    method_seen = defaultdict(int)
    method_failed = defaultdict(int)
    method_recovery_attempts = defaultdict(int)
    method_recovery_success = defaultdict(int)

    rows = []

    for txn in transactions:
        cid = txn.customer_id
        method = txn.payment_method
        attempt = attempts_by_txn.get(txn.id)

        if txn.status == TransactionStatus.FAILED and attempt is not None:
            customer_total = customer_seen[cid]
            customer_fail_rate = (
                customer_failed[cid] / customer_total if customer_total else 0.0
            )
            customer_recovery_rate = (
                customer_recovery_success[cid] / customer_recovery_attempts[cid]
                if customer_recovery_attempts[cid]
                else None
            )

            method_total = method_seen[method]
            method_fail_rate = (
                method_failed[method] / method_total if method_total else 0.10
            )
            method_recovery_rate = (
                method_recovery_success[method] / method_recovery_attempts[method]
                if method_recovery_attempts[method]
                else 0.5
            )

            rows.append(
                {
                    "transaction_id": txn.id,
                    "amount": txn.amount,
                    "payment_method": method.value,
                    "customer_prior_transactions": customer_total,
                    "customer_fail_rate": customer_fail_rate,
                    # Fall back to the method's recovery rate until we have
                    # any prior recovery attempts of our own for this customer.
                    "customer_recovery_rate": (
                        customer_recovery_rate
                        if customer_recovery_rate is not None
                        else method_recovery_rate
                    ),
                    "method_fail_rate": method_fail_rate,
                    "method_recovery_rate": method_recovery_rate,
                    "recovered": int(attempt.succeeded),
                }
            )

        
        customer_seen[cid] += 1
        method_seen[method] += 1
        if txn.status == TransactionStatus.FAILED:
            customer_failed[cid] += 1
            method_failed[method] += 1
            if attempt is not None:
                customer_recovery_attempts[cid] += 1
                method_recovery_attempts[method] += 1
                if attempt.succeeded:
                    customer_recovery_success[cid] += 1
                    method_recovery_success[method] += 1

    return pd.DataFrame(rows)

'@ | Set-Content -Path 'app/ml/features.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/ml' | Out-Null
@'
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FEATURE_COLUMNS_NUMERIC = [
    "amount",
    "customer_prior_transactions",
    "customer_fail_rate",
    "customer_recovery_rate",
    "method_fail_rate",
    "method_recovery_rate",
]


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
   
    method_dummies = pd.get_dummies(df["payment_method"], prefix="method").astype(float)
    X = pd.concat([df[FEATURE_COLUMNS_NUMERIC], method_dummies], axis=1)
    y = df["recovered"]
    return X, y


def train_and_evaluate(df: pd.DataFrame, n_splits: int = 5):

    X, y = prepare_features(df)

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    )

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    y_proba = cross_val_predict(pipeline, X, y, cv=cv, method="predict_proba")[:, 1]
    y_pred = (y_proba >= 0.5).astype(int)

    report = classification_report(y, y_pred, digits=3, zero_division=0)
    cm = confusion_matrix(y, y_pred)
    auc = roc_auc_score(y, y_proba)

   
    final_pipeline = pipeline.fit(X, y)

    return final_pipeline, X.columns.tolist(), report, cm, auc

'@ | Set-Content -Path 'app/ml/train.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/models' | Out-Null
@'

'@ | Set-Content -Path 'app/models/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/models' | Out-Null
@'
import enum


class CustomerType(str, enum.Enum):

    RELIABLE = "reliable"
    OCCASIONAL_PAYER = "occasional_payer"
    PRICE_SENSITIVE = "price_sensitive"
    HIGH_VALUE = "high_value"
    FREQUENTLY_FAILS = "frequently_fails"
    SUBSCRIPTION_HEAVY = "subscription_heavy"


class PaymentMethod(str, enum.Enum):
    UPI = "upi"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    NET_BANKING = "net_banking"
    WALLET = "wallet"


class TransactionStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"


class FailureType(str, enum.Enum):
   
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class RecoveryStrategy(str, enum.Enum):
    RETRY = "retry"
    DELAYED_RETRY = "delayed_retry"
    ALTERNATE_PAYMENT = "alternate_payment"
    INCENTIVE = "incentive"
    CUSTOMER_REMINDER = "customer_reminder"
    ESCALATION = "escalation"
    STOP = "stop"

'@ | Set-Content -Path 'app/models/enums.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/models' | Out-Null
@'
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
    
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RiskAssessment(Base):
  
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
    
    __tablename__ = "recovery_attempts"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    failure_type = Column(Enum(FailureType), nullable=False)
    succeeded = Column(Boolean, nullable=False)
    amount_recovered = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class StrategyDecision(Base):
   
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
   
    __tablename__ = "agent_decisions"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    action = Column(Enum(RecoveryStrategy), nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    requires_approval = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

'@ | Set-Content -Path 'app/models/models.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/policies' | Out-Null
@'

'@ | Set-Content -Path 'app/policies/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/policies' | Out-Null
@'
# These constants preview the guardrails formally enforced by the Policy
# Engine in Phase 8. Here in Phase 7, the agent can only ask about them via
# a non-binding "preview" tool — it cannot use them to authorize anything.
MAX_RETRIES = 3
MAX_AUTOMATED_RECOVERY_AMOUNT = 10_000
MAX_DISCOUNT = 0.10
MAX_INTERVENTIONS_PER_CUSTOMER_PER_DAY = 2
HIGH_VALUE_TRANSACTION_THRESHOLD = 25_000

'@ | Set-Content -Path 'app/policies/constants.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/risk' | Out-Null
@'

'@ | Set-Content -Path 'app/risk/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/risk' | Out-Null
@'
from sqlalchemy.orm import Session

from app.events.schemas import Event
from app.models.enums import PaymentMethod
from app.models.models import RiskAssessment
from app.risk.scoring import (
    RECOVERY_PROBABILITY_BY_METHOD,
    calculate_risk_score,
    estimate_failure_probability,
)


def assess_risk_on_payment_failed(db: Session, event: Event) -> RiskAssessment:
   
    transaction_id = event.entity_id
    customer_id = event.payload["customer_id"]
    payment_method = PaymentMethod(event.payload["payment_method"])
    amount = event.payload["amount"]

    failure_probability = estimate_failure_probability(
        db, customer_id, payment_method, exclude_transaction_id=transaction_id
    )
    recovery_probability = RECOVERY_PROBABILITY_BY_METHOD[payment_method]
    risk_score = calculate_risk_score(failure_probability, amount, recovery_probability)

    assessment = RiskAssessment(
        transaction_id=transaction_id,
        customer_id=customer_id,
        payment_method=payment_method,
        amount=amount,
        failure_probability=failure_probability,
        recovery_probability=recovery_probability,
        risk_score=risk_score,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment

'@ | Set-Content -Path 'app/risk/engine.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/risk' | Out-Null
@'
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import PaymentMethod, TransactionStatus
from app.models.models import Transaction


RECOVERY_PROBABILITY_BY_METHOD = {
    PaymentMethod.UPI: 0.55,
    PaymentMethod.CREDIT_CARD: 0.35,
    PaymentMethod.DEBIT_CARD: 0.40,
    PaymentMethod.NET_BANKING: 0.45,
    PaymentMethod.WALLET: 0.60,
}


MIN_SAMPLES_FOR_CUSTOMER_RATE = 5


def historical_failure_rate_for_method(
    db: Session, payment_method: PaymentMethod, exclude_transaction_id: int | None = None
) -> float:
    
    query = db.query(func.count(Transaction.id)).filter(
        Transaction.payment_method == payment_method
    )
    if exclude_transaction_id is not None:
        query = query.filter(Transaction.id != exclude_transaction_id)
    total = query.scalar()

    if not total:
        return 0.10  # fallback prior when we have no data at all

    failed_query = db.query(func.count(Transaction.id)).filter(
        Transaction.payment_method == payment_method,
        Transaction.status == TransactionStatus.FAILED,
    )
    if exclude_transaction_id is not None:
        failed_query = failed_query.filter(Transaction.id != exclude_transaction_id)
    failed = failed_query.scalar()

    return failed / total


def historical_failure_rate_for_customer(
    db: Session, customer_id: int, exclude_transaction_id: int | None = None
) -> tuple[float, int]:
    
    query = db.query(func.count(Transaction.id)).filter(
        Transaction.customer_id == customer_id
    )
    if exclude_transaction_id is not None:
        query = query.filter(Transaction.id != exclude_transaction_id)
    total = query.scalar()

    if not total:
        return 0.0, 0

    failed_query = db.query(func.count(Transaction.id)).filter(
        Transaction.customer_id == customer_id,
        Transaction.status == TransactionStatus.FAILED,
    )
    if exclude_transaction_id is not None:
        failed_query = failed_query.filter(Transaction.id != exclude_transaction_id)
    failed = failed_query.scalar()

    return failed / total, total


def estimate_failure_probability(
    db: Session,
    customer_id: int,
    payment_method: PaymentMethod,
    exclude_transaction_id: int | None = None,
) -> float:
    
    method_rate = historical_failure_rate_for_method(
        db, payment_method, exclude_transaction_id
    )
    customer_rate, sample_size = historical_failure_rate_for_customer(
        db, customer_id, exclude_transaction_id
    )

    if sample_size < MIN_SAMPLES_FOR_CUSTOMER_RATE:
        return method_rate

   
    weight = min(sample_size / 20, 0.8)
    return weight * customer_rate + (1 - weight) * method_rate


def calculate_risk_score(
    failure_probability: float, amount: float, recovery_probability: float
) -> float:
    
    return failure_probability * amount * recovery_probability

'@ | Set-Content -Path 'app/risk/scoring.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/services' | Out-Null
@'

'@ | Set-Content -Path 'app/services/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/simulator' | Out-Null
@'

'@ | Set-Content -Path 'app/simulator/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/simulator' | Out-Null
@'
import random

import numpy as np
from faker import Faker
from sqlalchemy.orm import Session

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.enums import CustomerType, FailureType, PaymentMethod, TransactionStatus
from app.models.models import Merchant, Customer, RecoveryAttempt, Transaction

fake = Faker()


BASE_FAILURE_PROBABILITY = {
    PaymentMethod.UPI: 0.05,
    PaymentMethod.CREDIT_CARD: 0.12,
    PaymentMethod.DEBIT_CARD: 0.10,
    PaymentMethod.NET_BANKING: 0.08,
    PaymentMethod.WALLET: 0.04,
}


CUSTOMER_FAILURE_MULTIPLIER = {
    CustomerType.RELIABLE: 0.5,
    CustomerType.OCCASIONAL_PAYER: 1.0,
    CustomerType.PRICE_SENSITIVE: 1.1,
    CustomerType.HIGH_VALUE: 0.7,
    CustomerType.FREQUENTLY_FAILS: 2.5,
    CustomerType.SUBSCRIPTION_HEAVY: 1.0,
}


CUSTOMER_TYPE_WEIGHTS = {
    CustomerType.RELIABLE: 0.30,
    CustomerType.OCCASIONAL_PAYER: 0.25,
    CustomerType.PRICE_SENSITIVE: 0.15,
    CustomerType.HIGH_VALUE: 0.10,
    CustomerType.FREQUENTLY_FAILS: 0.10,
    CustomerType.SUBSCRIPTION_HEAVY: 0.10,
}


AMOUNT_MEAN_LOG = {
    CustomerType.RELIABLE: 7.0,
    CustomerType.OCCASIONAL_PAYER: 6.5,
    CustomerType.PRICE_SENSITIVE: 6.0,
    CustomerType.HIGH_VALUE: 9.0,
    CustomerType.FREQUENTLY_FAILS: 6.8,
    CustomerType.SUBSCRIPTION_HEAVY: 7.2,
}


TRANSIENT_PROBABILITY_BY_METHOD = {
    PaymentMethod.UPI: 0.85,
    PaymentMethod.WALLET: 0.85,
    PaymentMethod.NET_BANKING: 0.70,
    PaymentMethod.DEBIT_CARD: 0.60,
    PaymentMethod.CREDIT_CARD: 0.50,
}


TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE = {
    CustomerType.RELIABLE: 0.05,
    CustomerType.OCCASIONAL_PAYER: 0.0,
    CustomerType.PRICE_SENSITIVE: 0.0,
    CustomerType.HIGH_VALUE: 0.05,
    CustomerType.FREQUENTLY_FAILS: -0.30,
    CustomerType.SUBSCRIPTION_HEAVY: 0.0,
}


RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE = {
    FailureType.TRANSIENT: 0.80,
    FailureType.PERMANENT: 0.05,
}


def create_merchant(db: Session, name: str = "Demo Merchant") -> Merchant:
    merchant = Merchant(name=name)
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def generate_customers(db: Session, merchant: Merchant, n: int) -> list[Customer]:
    types = list(CUSTOMER_TYPE_WEIGHTS.keys())
    weights = list(CUSTOMER_TYPE_WEIGHTS.values())

    customers = []
    for _ in range(n):
        customer_type = random.choices(types, weights=weights, k=1)[0]
        customer = Customer(
            merchant_id=merchant.id,
            name=fake.name(),
            email=fake.email(),
            customer_type=customer_type,
        )
        db.add(customer)
        customers.append(customer)

    db.commit()
    for c in customers:
        db.refresh(c)
    return customers


def generate_transactions(
    db: Session, customers: list[Customer], n: int
) -> list[Transaction]:
    methods = list(PaymentMethod)

    transactions = []
    for _ in range(n):
        customer = random.choice(customers)
        payment_method = random.choice(methods)

      
        mean_log = AMOUNT_MEAN_LOG[customer.customer_type]
        amount = float(np.random.lognormal(mean=mean_log, sigma=0.6))
        amount = round(min(amount, 200_000), 2)

       
        fail_prob = BASE_FAILURE_PROBABILITY[payment_method]
        fail_prob *= CUSTOMER_FAILURE_MULTIPLIER[customer.customer_type]
        fail_prob = min(fail_prob, 0.95)

      
        will_fail = np.random.random() < fail_prob
        status = TransactionStatus.FAILED if will_fail else TransactionStatus.SUCCESS

        txn = Transaction(
            customer_id=customer.id,
            payment_method=payment_method,
            amount=amount,
            status=status,
        )
        db.add(txn)
        db.flush()  # assigns txn.id without committing, so events can reference it

        event_payload = {
            "amount": amount,
            "payment_method": payment_method.value,
            "customer_id": customer.id,
        }

       
        event_bus.publish(
            db,
            Event(
                event_type=EventType.PAYMENT_CREATED,
                entity_type="transaction",
                entity_id=txn.id,
                payload=event_payload,
            ),
        )
        event_bus.publish(
            db,
            Event(
                event_type=EventType.PAYMENT_FAILED if will_fail else EventType.PAYMENT_SUCCESS,
                entity_type="transaction",
                entity_id=txn.id,
                payload=event_payload,
            ),
        )

        if will_fail:
           
            transient_prob = TRANSIENT_PROBABILITY_BY_METHOD[payment_method]
            transient_prob += TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE[customer.customer_type]
            transient_prob = min(max(transient_prob, 0.05), 0.95)

            failure_type = (
                FailureType.TRANSIENT
                if np.random.random() < transient_prob
                else FailureType.PERMANENT
            )
            recovery_success_prob = RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE[failure_type]
            recovered = np.random.random() < recovery_success_prob

            attempt = RecoveryAttempt(
                transaction_id=txn.id,
                failure_type=failure_type,
                succeeded=recovered,
                amount_recovered=amount if recovered else 0.0,
            )
            db.add(attempt)
            db.flush()

            event_bus.publish(
                db,
                Event(
                    event_type=EventType.RECOVERY_ATTEMPTED,
                    entity_type="transaction",
                    entity_id=txn.id,
                    payload=event_payload,
                ),
            )
            event_bus.publish(
                db,
                Event(
                    event_type=EventType.RECOVERY_SUCCESS if recovered else EventType.RECOVERY_FAILED,
                    entity_type="transaction",
                    entity_id=txn.id,
                    payload={**event_payload, "amount_recovered": attempt.amount_recovered},
                ),
            )

        transactions.append(txn)

    for t in transactions:
        db.refresh(t)
    return transactions


def run_simulation(
    db: Session,
    num_customers: int = 200,
    num_transactions: int = 1000,
    merchant_name: str = "Demo Merchant",
):
   
    merchant = create_merchant(db, name=merchant_name)
    customers = generate_customers(db, merchant, num_customers)
    transactions = generate_transactions(db, customers, num_transactions)
    return merchant, customers, transactions

'@ | Set-Content -Path 'app/simulator/generator.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/strategy' | Out-Null
@'

'@ | Set-Content -Path 'app/strategy/__init__.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/strategy' | Out-Null
@'
from dataclasses import dataclass

from app.models.enums import RecoveryStrategy


@dataclass(frozen=True)
class StrategyParams:
    cost: float
    probability_multiplier: float
    amount_multiplier: float



STRATEGY_DEFINITIONS: dict[RecoveryStrategy, StrategyParams] = {
    # A plain immediate retry: cheap, no change to the base probability.
    RecoveryStrategy.RETRY: StrategyParams(
        cost=5, probability_multiplier=1.0, amount_multiplier=1.0
    ),
    # Waiting before retrying gives transient issues (network blips,
    # temporary provider outages) time to resolve on their own.
    RecoveryStrategy.DELAYED_RETRY: StrategyParams(
        cost=5, probability_multiplier=1.15, amount_multiplier=1.0
    ),
    # Switching payment method sidesteps whatever was wrong with the
    # original method entirely — the biggest probability boost, but costlier.
    RecoveryStrategy.ALTERNATE_PAYMENT: StrategyParams(
        cost=15, probability_multiplier=1.30, amount_multiplier=1.0
    ),
    # A discount raises the odds the customer follows through, but reduces
    # the amount actually recovered if it works.
    RecoveryStrategy.INCENTIVE: StrategyParams(
        cost=10, probability_multiplier=1.20, amount_multiplier=0.90
    ),
    RecoveryStrategy.CUSTOMER_REMINDER: StrategyParams(
        cost=8, probability_multiplier=1.10, amount_multiplier=1.0
    ),
    # Human involvement: most expensive, modest probability boost — reserved
    # for cases nothing automated handles well (formalized in Phase 8).
    RecoveryStrategy.ESCALATION: StrategyParams(
        cost=50, probability_multiplier=1.05, amount_multiplier=1.0
    ),
    # Doing nothing always costs 0 and always has probability 0 -> expected
    # value is always exactly 0. This is what guarantees the engine never
    # recommends a money-losing action: STOP wins by default if every real
    # option has negative expected value.
    RecoveryStrategy.STOP: StrategyParams(
        cost=0, probability_multiplier=0.0, amount_multiplier=1.0
    ),
}

'@ | Set-Content -Path 'app/strategy/definitions.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/strategy' | Out-Null
@'
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.events.schemas import Event
from app.models.enums import PaymentMethod, RecoveryStrategy
from app.models.models import StrategyDecision
from app.strategy.definitions import STRATEGY_DEFINITIONS
from app.strategy.probability import predict_recovery_probability


@dataclass
class StrategyRecommendation:
    strategy: RecoveryStrategy
    estimated_probability: float
    cost: float
    expected_value: float
    reasoning: str
    candidates: list[tuple[RecoveryStrategy, float, float, float]]


def recommend_strategy(
    db: Session,
    transaction_id: int,
    customer_id: int,
    payment_method: PaymentMethod,
    amount: float,
) -> StrategyRecommendation:
   
    base_probability = predict_recovery_probability(
        db, customer_id, payment_method, amount, exclude_transaction_id=transaction_id
    )

    candidates = []
    for strategy, params in STRATEGY_DEFINITIONS.items():
        if strategy == RecoveryStrategy.STOP:
            probability = 0.0
            expected_value = 0.0
        else:
            probability = min(base_probability * params.probability_multiplier, 0.95)
            expected_value = probability * amount * params.amount_multiplier - params.cost
        candidates.append((strategy, probability, params.cost, expected_value))

    best_strategy, best_probability, best_cost, best_ev = max(
        candidates, key=lambda c: c[3]
    )

    reasoning = (
        f"Base recovery probability {base_probability:.2f}; chose {best_strategy.value} "
        f"(adjusted probability {best_probability:.2f}, cost \u20b9{best_cost:.2f}) with the "
        f"highest expected value (\u20b9{best_ev:.2f}) among {len(candidates)} candidates."
    )

    return StrategyRecommendation(
        strategy=best_strategy,
        estimated_probability=best_probability,
        cost=best_cost,
        expected_value=best_ev,
        reasoning=reasoning,
        candidates=candidates,
    )


def recommend_strategy_on_payment_failed(db: Session, event: Event) -> StrategyDecision:
   
    transaction_id = event.entity_id
    customer_id = event.payload["customer_id"]
    payment_method = PaymentMethod(event.payload["payment_method"])
    amount = event.payload["amount"]

    recommendation = recommend_strategy(
        db, transaction_id, customer_id, payment_method, amount
    )

    decision = StrategyDecision(
        transaction_id=transaction_id,
        customer_id=customer_id,
        payment_method=payment_method,
        amount=amount,
        strategy=recommendation.strategy,
        estimated_probability=recommendation.estimated_probability,
        cost=recommendation.cost,
        expected_value=recommendation.expected_value,
        reasoning=recommendation.reasoning,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision

'@ | Set-Content -Path 'app/strategy/engine.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'app/strategy' | Out-Null
@'
import logging
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from app.models.enums import PaymentMethod
from app.models.models import RecoveryAttempt, Transaction
from app.risk.scoring import (
    RECOVERY_PROBABILITY_BY_METHOD,
    historical_failure_rate_for_customer,
    historical_failure_rate_for_method,
)

logger = logging.getLogger("recoverai.strategy")

# backend/app/strategy/probability.py -> parents[3] is the project root,
# where data/ lives alongside backend/.
MODEL_PATH = Path(__file__).resolve().parents[3] / "data" / "models" / "recovery_model.pkl"


@lru_cache(maxsize=1)
def _load_model():
    
    try:
        bundle = joblib.load(MODEL_PATH)
        return bundle["model"], bundle["feature_names"]
    except FileNotFoundError:
        logger.info("No trained recovery model found at %s — using rule-based fallback.", MODEL_PATH)
        return None, None


def _recovery_counts(db: Session, filter_clause, exclude_transaction_id):
    query = (
        db.query(RecoveryAttempt)
        .join(Transaction, RecoveryAttempt.transaction_id == Transaction.id)
        .filter(filter_clause)
    )
    if exclude_transaction_id is not None:
        query = query.filter(RecoveryAttempt.transaction_id != exclude_transaction_id)
    attempts = query.all()
    total = len(attempts)
    success = sum(1 for a in attempts if a.succeeded)
    return success, total


def build_live_features(
    db: Session,
    customer_id: int,
    payment_method: PaymentMethod,
    amount: float,
    exclude_transaction_id: int | None = None,
) -> dict:
    
    customer_fail_rate, customer_total = historical_failure_rate_for_customer(
        db, customer_id, exclude_transaction_id
    )
    method_fail_rate = historical_failure_rate_for_method(
        db, payment_method, exclude_transaction_id
    )

    method_success, method_total = _recovery_counts(
        db, Transaction.payment_method == payment_method, exclude_transaction_id
    )
    method_recovery_rate = method_success / method_total if method_total else 0.5

    customer_success, customer_recovery_total = _recovery_counts(
        db, Transaction.customer_id == customer_id, exclude_transaction_id
    )
    customer_recovery_rate = (
        customer_success / customer_recovery_total
        if customer_recovery_total
        else method_recovery_rate
    )

    return {
        "amount": amount,
        "payment_method": payment_method.value,
        "customer_prior_transactions": customer_total,
        "customer_fail_rate": customer_fail_rate,
        "customer_recovery_rate": customer_recovery_rate,
        "method_fail_rate": method_fail_rate,
        "method_recovery_rate": method_recovery_rate,
    }


def predict_recovery_probability(
    db: Session,
    customer_id: int,
    payment_method: PaymentMethod,
    amount: float,
    exclude_transaction_id: int | None = None,
) -> float:
    
    model, feature_names = _load_model()

    if model is None:
        return RECOVERY_PROBABILITY_BY_METHOD[payment_method]

    features = build_live_features(
        db, customer_id, payment_method, amount, exclude_transaction_id
    )
    row = pd.DataFrame([features])
    method_dummies = pd.get_dummies(row["payment_method"], prefix="method").astype(float)
    numeric = row.drop(columns=["payment_method"])
    X = pd.concat([numeric, method_dummies], axis=1)
    # Align columns exactly to what the model was trained on. Any payment
    # method missing from this single row (or one the model never saw)
    # gets filled with 0 rather than crashing on a column mismatch.
    X = X.reindex(columns=feature_names, fill_value=0.0)

    return float(model.predict_proba(X)[0, 1])

'@ | Set-Content -Path 'app/strategy/probability.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'scripts' | Out-Null
@'

from app.agents.ambiguity import is_ambiguous
from app.agents.engine import make_agent_decision
from app.database import SessionLocal, init_db
from app.models.enums import TransactionStatus
from app.models.models import Transaction
from app.strategy.engine import recommend_strategy

MAX_CASES_TO_REVIEW = 3


def main():
    init_db()
    db = SessionLocal()
    try:
        failed_txns = (
            db.query(Transaction).filter(Transaction.status == TransactionStatus.FAILED).all()
        )
        print(f"Scanning {len(failed_txns)} failed transactions for ambiguous cases...")

        reviewed = 0
        for txn in failed_txns:
            recommendation = recommend_strategy(
                db, txn.id, txn.customer_id, txn.payment_method, txn.amount
            )
            if not is_ambiguous(recommendation, txn.amount):
                continue

            print(
                f"\nAmbiguous case: txn={txn.id} amount=₹{txn.amount:,.2f} "
                f"deterministic pick={recommendation.strategy.value}"
            )

            try:
                decision = make_agent_decision(
                    db, txn.id, txn.customer_id, txn.payment_method, txn.amount
                )
                print(
                    f"  Agent decision: {decision.action.value} "
                    f"(confidence={decision.confidence:.2f}, "
                    f"requires_approval={decision.requires_approval})"
                )
                print(f"  Reason: {decision.reason}")
            except Exception as e:
                print(f"  Agent call failed: {e}")
                print("  Make sure GROQ_API_KEY is set in backend/.env")

            reviewed += 1
            if reviewed >= MAX_CASES_TO_REVIEW:
                break

        if reviewed == 0:
            print("No ambiguous cases found in this dataset — try a larger simulation run.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

'@ | Set-Content -Path 'scripts/run_agent_demo.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'scripts' | Out-Null
@'

import sys

from sqlalchemy import func

from app.database import SessionLocal, init_db
from app.events.consumers import register_default_consumers
from app.models.enums import TransactionStatus
from app.models.models import EventLog, RiskAssessment, StrategyDecision
from app.simulator.generator import run_simulation


def main():
    num_customers = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    num_transactions = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    init_db()
    register_default_consumers()

    db = SessionLocal()
    try:
        merchant, customers, transactions = run_simulation(
            db, num_customers=num_customers, num_transactions=num_transactions
        )

        total_amount = sum(t.amount for t in transactions)
        failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
        failed_amount = sum(t.amount for t in failed)
        event_count = db.query(EventLog).count()

        print(f"Merchant:            {merchant.name}")
        print(f"Customers generated: {len(customers)}")
        print(f"Transactions:        {len(transactions)}")
        print(f"Total volume:        ₹{total_amount:,.2f}")
        print(f"Failed transactions: {len(failed)} ({len(failed)/len(transactions):.1%})")
        print(f"Failed volume:       ₹{failed_amount:,.2f}")
        print(f"Events recorded:     {event_count}")

        top_risks = (
            db.query(RiskAssessment)
            .order_by(RiskAssessment.risk_score.desc())
            .limit(5)
            .all()
        )
        print("\nTop 5 recoverable-revenue opportunities:")
        for r in top_risks:
            print(
                f"  txn={r.transaction_id:<5} amount=₹{r.amount:>9,.2f}  "
                f"fail_prob={r.failure_probability:.2f}  "
                f"recover_prob={r.recovery_probability:.2f}  "
                f"risk_score={r.risk_score:,.2f}"
            )

        strategy_counts = (
            db.query(StrategyDecision.strategy, func.count(StrategyDecision.id))
            .group_by(StrategyDecision.strategy)
            .all()
        )
        total_ev = db.query(func.sum(StrategyDecision.expected_value)).scalar() or 0.0

        print("\nRecommended strategy distribution:")
        for strategy, count in strategy_counts:
            print(f"  {strategy.value:<20} {count}")
        print(f"\nTotal expected recoverable value (sum of chosen strategies' EV): ₹{total_ev:,.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

'@ | Set-Content -Path 'scripts/run_simulation.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path 'scripts' | Out-Null
@'

import os

import joblib

from app.database import SessionLocal, init_db
from app.ml.features import build_recovery_dataset
from app.ml.train import train_and_evaluate


def main():
    init_db()
    db = SessionLocal()
    try:
        df = build_recovery_dataset(db)
        print(f"Dataset size: {len(df)} failed transactions with recovery attempts")
        if len(df) == 0:
            print("No data found. Run scripts/run_simulation.py first.")
            return

        print(f"Recovered: {df['recovered'].sum()} ({df['recovered'].mean():.1%})")

        if len(df) < 30:
            print("Not enough data to train reliably — re-run the simulator with more transactions.")
            return

        model, feature_names, report, cm, auc = train_and_evaluate(df)

        print("\nClassification report (5-fold cross-validated, out-of-fold predictions):")
        print(report)
        print("Confusion matrix (rows=actual, cols=predicted; [not_recovered, recovered]):")
        print(cm)
        print(f"ROC-AUC: {auc:.3f}")

        os.makedirs("../data/models", exist_ok=True)
        joblib.dump(
            {"model": model, "feature_names": feature_names},
            "../data/models/recovery_model.pkl",
        )
        print("\nModel saved to data/models/recovery_model.pkl")
    finally:
        db.close()


if __name__ == "__main__":
    main()

'@ | Set-Content -Path 'scripts/train_recovery_model.py' -Encoding utf8

New-Item -ItemType Directory -Force -Path '.' | Out-Null
@'
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.9.2
pydantic-settings==2.5.2
sqlalchemy==2.0.35
python-dotenv==1.0.1
numpy==2.1.1
faker==29.0.0
pandas==2.2.3
scikit-learn==1.5.2
joblib==1.4.2
groq==1.7.0
pytest==8.3.3
httpx==0.27.2

'@ | Set-Content -Path 'requirements.txt' -Encoding utf8

@'
APP_NAME=RecoverAI
ENVIRONMENT=development
DATABASE_URL=sqlite:///../data/recoverai.db
GROQ_API_KEY=

'@ | Set-Content -Path '.env.example' -Encoding utf8

@'
[pytest]
pythonpath = .

'@ | Set-Content -Path 'pytest.ini' -Encoding utf8

Write-Host "Rebuild complete. Now run:"
Write-Host "  pip install -r requirements.txt"
Write-Host "  copy .env.example .env"
Write-Host "  python -m pytest"
