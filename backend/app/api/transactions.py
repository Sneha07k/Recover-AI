from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.schemas import TransactionOut
from app.database import get_db
from app.models.enums import TransactionStatus
from app.models.models import Customer, Transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    status: TransactionStatus | None = None,
    search: str | None = Query(
        None,
        description="Matches transaction ID (exact), payment method (partial), or customer name (partial, case-insensitive)",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Transaction)
    if status is not None:
        query = query.filter(Transaction.status == status)
    if search:
        search = search.strip()
        
        query = query.join(Customer, Transaction.customer_id == Customer.id)
        conditions = [
            Transaction.payment_method.ilike(f"%{search}%"),
            Customer.name.ilike(f"%{search}%"),
        ]
        if search.isdigit():
            conditions.append(Transaction.id == int(search))
        query = query.filter(or_(*conditions))
    return query.order_by(Transaction.id.desc()).offset(skip).limit(limit).all()


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    txn = db.get(Transaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn
