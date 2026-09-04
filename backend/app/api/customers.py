from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import TransactionStatus
from app.models.models import Customer, RecoveryAttempt, Transaction

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("")
def list_customers(
    sort_by: str = Query(
        "failure_rate", pattern="^(failure_rate|total_transactions|recovery_rate)$"
    ),
    search: str | None = Query(
        None, description="Matches customer name (partial, case-insensitive)"
    ),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
):
    
    txn_rows = (
        db.query(
            Transaction.customer_id,
            func.count(Transaction.id),
            func.sum(
                case((Transaction.status == TransactionStatus.FAILED, 1), else_=0)
            ),
        )
        .group_by(Transaction.customer_id)
        .all()
    )
    txn_stats = {
        cid: {"total": total, "failed": failed or 0} for cid, total, failed in txn_rows
    }

    recovery_rows = (
        db.query(
            Transaction.customer_id,
            func.count(RecoveryAttempt.id),
            func.sum(
                case((RecoveryAttempt.succeeded == True, 1), else_=0)
            ), 
        )
        .join(RecoveryAttempt, RecoveryAttempt.transaction_id == Transaction.id)
        .group_by(Transaction.customer_id)
        .all()
    )
    recovery_stats = {
        cid: {"attempts": attempts, "successes": successes or 0}
        for cid, attempts, successes in recovery_rows
    }

    customers_query = db.query(Customer).filter(Customer.id.in_(txn_stats.keys()))
    if search:
        customers_query = customers_query.filter(
            Customer.name.ilike(f"%{search.strip()}%")
        )
    customers = customers_query.all()

    results = []
    for c in customers:
        t = txn_stats.get(c.id, {"total": 0, "failed": 0})
        r = recovery_stats.get(c.id, {"attempts": 0, "successes": 0})
        failure_rate = t["failed"] / t["total"] if t["total"] else 0.0
        recovery_rate = r["successes"] / r["attempts"] if r["attempts"] else None
        results.append(
            {
                "id": c.id,
                "name": c.name,
                "customer_type": c.customer_type.value,
                "opted_out": c.opted_out,
                "total_transactions": t["total"],
                "failed_transactions": t["failed"],
                "failure_rate": failure_rate,
                "recovery_attempts": r["attempts"],
                "recovery_rate": recovery_rate,
            }
        )

    if sort_by == "failure_rate":
        results.sort(key=lambda x: x["failure_rate"], reverse=True)
    elif sort_by == "total_transactions":
        results.sort(key=lambda x: x["total_transactions"], reverse=True)
    elif sort_by == "recovery_rate":
        
        results.sort(
            key=lambda x: x["recovery_rate"] if x["recovery_rate"] is not None else -1,
            reverse=True,
        )

    return results[:limit]


@router.get("/{customer_id}")
def get_customer_detail(customer_id: int, db: Session = Depends(get_db)):
    
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    transactions = (
        db.query(Transaction)
        .filter(Transaction.customer_id == customer_id)
        .order_by(Transaction.id.desc())
        .limit(50)
        .all()
    )

    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "customer_type": customer.customer_type.value,
        "opted_out": customer.opted_out,
        "transactions": [
            {
                "id": t.id,
                "amount": t.amount,
                "payment_method": t.payment_method.value,
                "status": t.status.value,
                "recovered": t.recovered,
            }
            for t in transactions
        ],
    }
