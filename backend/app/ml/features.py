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

