import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.ambiguity import is_ambiguous
from app.agents.client import run_agent_loop
from app.agents.engine import make_agent_decision
from app.agents.schemas import AgentDecisionResult
from app.agents.tools import build_tool_executor
from app.database import Base
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import AgentDecision, Customer, Merchant, Transaction
from app.strategy.engine import StrategyRecommendation


def make_test_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401 registers tables on Base

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


# ---------------------------------------------------------------------
# Fake Groq client — mimics just enough of the OpenAI-compatible response
# shape for run_agent_loop's logic to be tested with zero network calls.
# Real Groq/OpenAI tool call arguments arrive as a JSON STRING, which is
# why FakeFunction.arguments below is always a json.dumps(...) string,
# not a raw dict — matching the real API's behavior exactly.
# ---------------------------------------------------------------------
class FakeFunction:
    def __init__(self, name, arguments: dict):
        self.name = name
        self.arguments = json.dumps(arguments)


class FakeToolCall:
    def __init__(self, id, name, arguments: dict):
        self.id = id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeChat:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)


class FakeClient:
    def __init__(self, responses):
        self.chat = FakeChat(responses)


def test_stop_and_incentive_are_valid_actions_in_schema():
    result = AgentDecisionResult(
        action=RecoveryStrategy.INCENTIVE,
        confidence=0.7,
        reason="test",
        requires_approval=False,
    )
    assert result.action == RecoveryStrategy.INCENTIVE


def test_agent_decision_result_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        AgentDecisionResult(
            action=RecoveryStrategy.RETRY,
            confidence=1.5,
            reason="bad",
            requires_approval=False,
        )


def test_is_ambiguous_true_for_close_expected_values():
    recommendation = StrategyRecommendation(
        strategy=RecoveryStrategy.RETRY,
        estimated_probability=0.5,
        cost=5,
        expected_value=100.0,
        reasoning="test",
        candidates=[
            (RecoveryStrategy.RETRY, 0.5, 5, 100.0),
            (RecoveryStrategy.DELAYED_RETRY, 0.55, 5, 99.0),
            (RecoveryStrategy.STOP, 0.0, 0, 0.0),
        ],
    )
    assert is_ambiguous(recommendation, amount=1000) is True


def test_is_ambiguous_false_for_clear_winner_and_low_amount():
    recommendation = StrategyRecommendation(
        strategy=RecoveryStrategy.RETRY,
        estimated_probability=0.5,
        cost=5,
        expected_value=500.0,
        reasoning="test",
        candidates=[
            (RecoveryStrategy.RETRY, 0.5, 5, 500.0),
            (RecoveryStrategy.STOP, 0.0, 0, 0.0),
        ],
    )
    assert is_ambiguous(recommendation, amount=1000) is False


def test_is_ambiguous_true_for_high_value_regardless_of_gap():
    recommendation = StrategyRecommendation(
        strategy=RecoveryStrategy.RETRY,
        estimated_probability=0.5,
        cost=5,
        expected_value=20000.0,
        reasoning="test",
        candidates=[
            (RecoveryStrategy.RETRY, 0.5, 5, 20000.0),
            (RecoveryStrategy.STOP, 0.0, 0, 0.0),
        ],
    )
    assert is_ambiguous(recommendation, amount=30_000) is True


def test_get_transaction_tool_returns_expected_fields():
    db = make_test_session()
    try:
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
            amount=999.0,
            status=TransactionStatus.FAILED,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        executor = build_tool_executor(db)
        result = executor["get_transaction"]({"transaction_id": txn.id})

        assert result["amount"] == 999.0
        assert result["payment_method"] == "upi"
        assert result["status"] == "failed"
    finally:
        db.close()


def test_run_agent_loop_calls_tool_then_returns_submitted_decision():
    """
    Simulates a two-turn conversation: the model first calls get_transaction,
    then (having "seen" the result) submits its final decision. No network
    call happens — the fake client just returns pre-scripted responses.
    """
    turn_1 = FakeResponse(
        message=FakeMessage(
            tool_calls=[
                FakeToolCall("call_1", "get_transaction", {"transaction_id": 42})
            ]
        )
    )
    turn_2 = FakeResponse(
        message=FakeMessage(
            tool_calls=[
                FakeToolCall(
                    "call_2",
                    "submit_recovery_decision",
                    {
                        "action": "retry",
                        "confidence": 0.8,
                        "reason": "Transaction looks recoverable",
                        "requires_approval": False,
                    },
                )
            ]
        )
    )
    fake_client = FakeClient([turn_1, turn_2])

    calls_seen = []
    tool_executor = {
        "get_transaction": lambda tool_input: calls_seen.append(tool_input)
        or {"amount": 999.0}
    }

    result = run_agent_loop(
        system_prompt="test system prompt",
        user_message="test user message",
        tool_executor=tool_executor,
        client=fake_client,
    )

    assert result["action"] == "retry"
    assert result["confidence"] == 0.8
    assert calls_seen == [{"transaction_id": 42}]
    assert len(fake_client.chat.completions.calls) == 2  # one API call per turn


def test_run_agent_loop_raises_if_no_decision_within_max_turns():
    turn = FakeResponse(
        message=FakeMessage(
            tool_calls=[
                FakeToolCall("call_x", "get_transaction", {"transaction_id": 1})
            ]
        )
    )
    fake_client = FakeClient([turn, turn, turn])
    tool_executor = {"get_transaction": lambda tool_input: {"amount": 1.0}}

    with pytest.raises(RuntimeError):
        run_agent_loop(
            system_prompt="test",
            user_message="test",
            tool_executor=tool_executor,
            client=fake_client,
            max_turns=3,
        )


def test_make_agent_decision_persists_agent_decision_row():
    db = make_test_session()
    try:
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
            amount=30000.0,
            status=TransactionStatus.FAILED,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        submit_response = FakeResponse(
            message=FakeMessage(
                tool_calls=[
                    FakeToolCall(
                        "call_1",
                        "submit_recovery_decision",
                        {
                            "action": "escalation",
                            "confidence": 0.6,
                            "reason": "High-value transaction warrants human review",
                            "requires_approval": True,
                        },
                    )
                ]
            )
        )
        fake_client = FakeClient([submit_response])

        decision = make_agent_decision(
            db, txn.id, customer.id, PaymentMethod.UPI, 30000.0, client=fake_client
        )

        assert decision.action == RecoveryStrategy.ESCALATION
        assert decision.requires_approval is True
        stored = db.query(AgentDecision).all()
        assert len(stored) == 1
    finally:
        db.close()
