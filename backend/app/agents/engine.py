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

    trace: list = []
    raw_result = run_agent_loop(
        SYSTEM_PROMPT, user_message, tool_executor, client=client, trace=trace
    )

    # Validate the model's structured output against our own schema before
    # trusting any of it — a tool schema is a strong hint to the model,
    # never a guarantee.
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
    # Transient attribute, not a DB column — just lets callers that want to
    # show the agent's reasoning process (which tools it called, in what
    # order, what it learned) do so without a schema change.
    decision.trace = trace
    return decision
