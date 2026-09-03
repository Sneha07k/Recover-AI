from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.execution.executor import execute_strategy
from app.models.models import Customer, PolicyDecision, Transaction

router = APIRouter(prefix="/escalations", tags=["escalations"])


def _serialize(pd: PolicyDecision, txn: Transaction, customer: Customer) -> dict:
    return {
        "id": pd.id,
        "transaction_id": pd.transaction_id,
        "customer_id": pd.customer_id,
        "customer_type": customer.customer_type.value if customer else None,
        "payment_method": txn.payment_method.value if txn else None,
        "strategy": pd.strategy.value,
        "amount": pd.amount,
        "reasons": pd.reasons,
        "human_resolution": pd.human_resolution,
        "resolved_at": pd.resolved_at,
        "created_at": pd.created_at,
    }


@router.get("")
def list_escalations(
    status: str = Query("pending", pattern="^(pending|approved|denied|all)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Lists escalated cases — the ones the policy engine flagged as needing
    a human, not the strategy engine's own choices. `pending` (default)
    shows only cases nobody has acted on yet; the whole point of this
    endpoint existing is that ESCALATE previously had no interface for
    the human it escalates TO.
    """
    query = db.query(PolicyDecision).filter(PolicyDecision.verdict == "escalate")

    if status == "pending":
        query = query.filter(PolicyDecision.human_resolution.is_(None))
    elif status == "approved":
        query = query.filter(PolicyDecision.human_resolution == "approved")
    elif status == "denied":
        query = query.filter(PolicyDecision.human_resolution == "denied")
    # "all" applies no additional filter

    decisions = query.order_by(PolicyDecision.id.desc()).limit(limit).all()

    results = []
    for pd in decisions:
        txn = db.get(Transaction, pd.transaction_id)
        customer = db.get(Customer, pd.customer_id)
        results.append(_serialize(pd, txn, customer))
    return results


@router.post("/{policy_decision_id}/approve")
def approve_escalation(policy_decision_id: int, db: Session = Depends(get_db)):
    """
    A human approves this specific escalated action. This is a deliberate
    override — we do NOT re-run evaluate_policy here, because the whole
    point of escalation is that a human has now reviewed the case and is
    explicitly authorizing it. execute_strategy runs immediately and the
    real simulated outcome is returned.
    """
    pd = db.get(PolicyDecision, policy_decision_id)
    if pd is None or pd.verdict != "escalate":
        raise HTTPException(status_code=404, detail="Escalated case not found")
    if pd.human_resolution is not None:
        raise HTTPException(
            status_code=400, detail=f"Already resolved: {pd.human_resolution}"
        )

    txn = db.get(Transaction, pd.transaction_id)
    customer = db.get(Customer, pd.customer_id)
    if txn is None or customer is None:
        raise HTTPException(
            status_code=404, detail="Underlying transaction or customer missing"
        )

    pd.human_resolution = "approved"
    pd.resolved_at = datetime.now(timezone.utc)
    db.commit()

    if txn.recovered:
        return {
            "approved": True,
            "executed": False,
            "note": "Transaction was already marked recovered — not re-executed.",
        }

    attempt = execute_strategy(db, txn, customer, pd.strategy)
    return {
        "approved": True,
        "executed": True,
        "succeeded": attempt.succeeded,
        "amount_recovered": attempt.amount_recovered,
    }


@router.post("/{policy_decision_id}/deny")
def deny_escalation(policy_decision_id: int, db: Session = Depends(get_db)):
    """
    A human denies this escalated action. Nothing executes — the case is
    simply marked resolved as denied, distinct from an automated policy
    DENY (this was a human choice made after seeing the specifics).
    """
    pd = db.get(PolicyDecision, policy_decision_id)
    if pd is None or pd.verdict != "escalate":
        raise HTTPException(status_code=404, detail="Escalated case not found")
    if pd.human_resolution is not None:
        raise HTTPException(
            status_code=400, detail=f"Already resolved: {pd.human_resolution}"
        )

    pd.human_resolution = "denied"
    pd.resolved_at = datetime.now(timezone.utc)
    db.commit()

    return {"denied": True}
