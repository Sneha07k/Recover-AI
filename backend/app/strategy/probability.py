import logging
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.enums import PaymentMethod
from app.models.models import RecoveryAttempt, Transaction
from app.risk.scoring import (
    RECOVERY_PROBABILITY_BY_METHOD,
    historical_failure_rate_for_customer,
    historical_failure_rate_for_method,
)

logger = logging.getLogger("recoverai.strategy")


MODEL_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "models" / "recovery_model.pkl"
)


@lru_cache(maxsize=1)
def _load_model():
  
    try:
        bundle = joblib.load(MODEL_PATH)
        return bundle["model"], bundle["feature_names"]
    except FileNotFoundError:
        logger.info(
            
            MODEL_PATH,
        )
        return None, None


def invalidate_model_cache() -> None:
    
    _load_model.cache_clear()


def _recovery_counts(db: Session, filter_clause, exclude_transaction_id):
    
    query = (
        db.query(
            func.count(RecoveryAttempt.id),
            func.coalesce(
                func.sum(case((RecoveryAttempt.succeeded == True, 1), else_=0)), 0
            ),  
        )
        .join(Transaction, RecoveryAttempt.transaction_id == Transaction.id)
        .filter(filter_clause)
    )
    if exclude_transaction_id is not None:
        query = query.filter(RecoveryAttempt.transaction_id != exclude_transaction_id)
    total, success = query.one()
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
    force_rule_based: bool = False,
) -> float:
   
    if not force_rule_based:
        model, feature_names = _load_model()
        if model is not None:
            features = build_live_features(
                db, customer_id, payment_method, amount, exclude_transaction_id
            )
            row = pd.DataFrame([features])
            method_dummies = pd.get_dummies(
                row["payment_method"], prefix="method"
            ).astype(float)
            numeric = row.drop(columns=["payment_method"])
            X = pd.concat([numeric, method_dummies], axis=1)
           
            X = X.reindex(columns=feature_names, fill_value=0.0)
            return float(model.predict_proba(X)[0, 1])

    return RECOVERY_PROBABILITY_BY_METHOD[payment_method]
