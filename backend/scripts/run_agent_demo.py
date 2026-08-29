"""
Run with: python scripts/run_agent_demo.py
Requires GROQ_API_KEY to be set in backend/.env
Assumes scripts/run_simulation.py has already been run.

Deliberately NOT wired into the automatic event pipeline: real LLM calls
have cost and latency that a bulk simulation of thousands of transactions
shouldn't pay for every single failure. Only genuinely ambiguous cases
(see app/agents/ambiguity.py) get sent to the agent, and only a handful
per run here.
"""
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
                f"\nAmbiguous case: txn={txn.id} amount=â‚¹{txn.amount:,.2f} "
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
            print("No ambiguous cases found in this dataset â€” try a larger simulation run.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

