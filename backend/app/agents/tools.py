from sqlalchemy.orm import Session

from app.models.enums import PaymentMethod
from app.models.models import Transaction
from app.policies.constants import HIGH_VALUE_TRANSACTION_THRESHOLD, MAX_AUTOMATED_RECOVERY_AMOUNT
from app.risk.scoring import historical_failure_rate_for_customer
from app.strategy.probability import predict_recovery_probability

# Tool schemas in Groq's (OpenAI-compatible) function-calling format. Every
# tool here except submit_recovery_decision is read-only â€” it looks things
# up, it never changes anything. submit_recovery_decision is intercepted by
# the agent loop itself (see app/agents/client.py) rather than "executed"
# at all.
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
                "limits. This is NOT the final policy check â€” RecoverAI's real "
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
                "execute anything â€” it only records your proposed decision."
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
    """
    Returns {tool_name: callable} for every tool EXCEPT submit_recovery_decision,
    which the agent loop handles specially rather than "executing".
    """

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
            reason = "High-value transaction â€” likely requires human approval."

        return {
            "compliant": compliant,
            "reason": reason,
            "note": "Preview only â€” not binding. Phase 8's policy engine has final authority.",
        }

    return {
        "get_transaction": get_transaction,
        "get_customer_history": get_customer_history,
        "estimate_recovery_probability": estimate_recovery_probability,
        "check_policy_preview": check_policy_preview,
    }

