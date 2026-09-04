import os
import time

import joblib
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.engine import make_agent_decision
from app.analytics.metrics import compute_metrics
from app.config import settings
from app.database import Base, engine, get_db, init_db
from app.demo.failure_scenarios import run_all_failure_scenarios
from app.events.consumers import register_default_consumers
from app.experiments.runner import run_experiment_end_to_end
from app.ml.features import build_recovery_dataset
from app.ml.train import compute_rule_based_baseline_auc, train_and_evaluate
from app.models.enums import CustomerType, PaymentMethod, TransactionStatus
from app.models.models import (
    Customer,
    Merchant,
    PolicyDecision,
    RecoveryAttempt,
    StrategyDecision,
    Transaction,
)
from app.policies.engine import evaluate_and_record_policy
from app.risk.scoring import (
    RECOVERY_PROBABILITY_BY_METHOD,
    calculate_risk_score,
    estimate_failure_probability,
)
from app.simulator import chaos
from app.simulator.generator import (
    generate_customers,
    generate_transactions,
    run_simulation,
)
from app.strategy.definitions import STRATEGY_DEFINITIONS
from app.strategy.engine import persist_strategy_decision, recommend_strategy
from app.strategy.probability import invalidate_model_cache

router = APIRouter(tags=["actions"])

_consumers_registered = False


def _ensure_consumers_registered():
   
    global _consumers_registered
    if not _consumers_registered:
        register_default_consumers()
        _consumers_registered = True


@router.post("/actions/simulate")
def action_simulate(
    num_customers: int = Query(200, ge=1, le=5000),
    num_transactions: int = Query(1500, ge=1, le=50_000),
    db: Session = Depends(get_db),
):
   
    _ensure_consumers_registered()

    start = time.perf_counter()
    merchant, customers, transactions = run_simulation(
        db, num_customers=num_customers, num_transactions=num_transactions
    )
    elapsed = time.perf_counter() - start

    metrics = compute_metrics(db)
    return {
        "merchant": merchant.name,
        "customers_generated": len(customers),
        "transactions_generated": len(transactions),
        "elapsed_seconds": round(elapsed, 2),
        "transactions_per_second": (
            round(len(transactions) / elapsed, 1) if elapsed > 0 else None
        ),
        "metrics": metrics,
    }


@router.post("/actions/train-model")
def action_train_model(db: Session = Depends(get_db)):
    
    df = build_recovery_dataset(db)
    if len(df) < 30:
        return {
            "trained": False,
            "reason": f"Only {len(df)} labeled examples available — need at least 30. "
            f"Run a larger simulation first.",
        }

    model, feature_names, report, confusion, auc = train_and_evaluate(df)
    baseline_auc = compute_rule_based_baseline_auc(df)

    os.makedirs("../data/models", exist_ok=True)
    joblib.dump(
        {"model": model, "feature_names": feature_names},
        "../data/models/recovery_model.pkl",
    )
    invalidate_model_cache()

    if auc > baseline_auc + 0.01:
        verdict = "The trained model beats the rule-based baseline."
    elif auc < baseline_auc - 0.01:
        verdict = "The rule-based baseline currently beats the trained model — reported honestly, not hidden."
    else:
        verdict = "The trained model and the rule-based baseline are roughly tied."

    return {
        "trained": True,
        "dataset_size": len(df),
        "recovered_fraction": float(df["recovered"].mean()),
        "roc_auc": float(auc),
        "baseline_auc": baseline_auc,
        "verdict": verdict,
        "confusion_matrix": confusion.tolist(),
        "report": report,
    }


@router.post("/actions/experiment")
def action_experiment(
    num_customers: int = Query(300, ge=1, le=5000),
    num_transactions: int = Query(3000, ge=1, le=50_000),
    seed: int = Query(42),
):
    
    return run_experiment_end_to_end(num_customers, num_transactions, seed)


@router.post("/actions/failure-demo")
def action_failure_demo(seed: int = Query(5)):
   
    return {"scenarios": run_all_failure_scenarios(seed)}


@router.post("/actions/reset")
def action_reset():
    
    from app.models import models  

    Base.metadata.drop_all(bind=engine)
    init_db()
    return {"reset": True}


@router.post("/actions/try-scenario")
def action_try_scenario(
    amount: float = Query(..., gt=0, le=500_000),
    payment_method: str = Query(...),
    customer_type: str = Query(...),
    opted_out: bool = Query(False),
    use_agent: bool = Query(False),
    db: Session = Depends(get_db),
):
   
    try:
        pm = PaymentMethod(payment_method)
        ct = CustomerType(customer_type)
    except ValueError as e:
        return {"error": f"Invalid input: {e}"}

    merchant = db.query(Merchant).first()
    if merchant is None:
        merchant = Merchant(name="Demo Merchant")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)

    customer = Customer(
        merchant_id=merchant.id,
        name="Sandbox Customer",
        email="sandbox@example.com",
        customer_type=ct,
        opted_out=opted_out,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    txn = Transaction(
        customer_id=customer.id,
        payment_method=pm,
        amount=amount,
        status=TransactionStatus.FAILED,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    
    failure_probability = estimate_failure_probability(
        db, customer.id, pm, exclude_transaction_id=txn.id
    )
    recovery_probability_rule = RECOVERY_PROBABILITY_BY_METHOD[pm]
    risk_score = calculate_risk_score(
        failure_probability, amount, recovery_probability_rule
    )

   
    recommendation = recommend_strategy(db, txn.id, customer.id, pm, amount)
    persist_strategy_decision(db, txn.id, customer.id, pm, amount, recommendation)

    strategy_to_check = recommendation.strategy
    requires_approval = False
    agent_info = None

   
    if use_agent:
        if not settings.GROQ_API_KEY:
            agent_info = {
                "error": "GROQ_API_KEY is not configured — agent consultation skipped."
            }
        else:
            try:
                agent_decision = make_agent_decision(
                    db, txn.id, customer.id, pm, amount
                )
                strategy_to_check = agent_decision.action
                requires_approval = agent_decision.requires_approval
                agent_info = {
                    "action": agent_decision.action.value,
                    "confidence": agent_decision.confidence,
                    "reason": agent_decision.reason,
                    "requires_approval": agent_decision.requires_approval,
                    "trace": getattr(agent_decision, "trace", []),
                }
            except Exception as e:
                agent_info = {"error": f"Agent call failed: {e}"}

    policy_decision = evaluate_and_record_policy(
        db, customer.id, txn.id, strategy_to_check, amount, requires_approval
    )

   
    db.commit()

    return {
        "transaction_id": txn.id,
        "risk": {
            "failure_probability": failure_probability,
            "recovery_probability_rule_based": recovery_probability_rule,
            "risk_score": risk_score,
        },
        "candidates": [
            {"strategy": s.value, "probability": p, "cost": c, "expected_value": ev}
            for (s, p, c, ev) in recommendation.candidates
        ],
        "recommended_strategy": recommendation.strategy.value,
        "reasoning": recommendation.reasoning,
        "agent": agent_info,
        "final_strategy_checked": strategy_to_check.value,
        "policy_verdict": policy_decision.verdict,
        "policy_reasons": policy_decision.reasons,
    }


def _batch_snapshot(db: Session, transaction_ids: list[int]) -> dict:
    
    txns = db.query(Transaction).filter(Transaction.id.in_(transaction_ids)).all()
    failed = [t for t in txns if t.status == TransactionStatus.FAILED]

    strategy_counts = (
        db.query(StrategyDecision.strategy, func.count(StrategyDecision.id))
        .filter(StrategyDecision.transaction_id.in_(transaction_ids))
        .group_by(StrategyDecision.strategy)
        .all()
    )
    top_strategy = (
        max(strategy_counts, key=lambda x: x[1])[0].value if strategy_counts else None
    )

    attempts = (
        db.query(RecoveryAttempt)
        .filter(RecoveryAttempt.transaction_id.in_(transaction_ids))
        .all()
    )
    successful = [a for a in attempts if a.succeeded]
    revenue_recovered = sum(a.amount_recovered for a in successful)

    policy_decisions = (
        db.query(PolicyDecision)
        .filter(PolicyDecision.transaction_id.in_(transaction_ids))
        .all()
    )
    denied = [p for p in policy_decisions if p.verdict == "deny"]
    escalated = [p for p in policy_decisions if p.verdict == "escalate"]

    denial_reason_counts: dict[str, int] = {}
    for p in denied:
        for r in p.reasons:
            key = r[:45]
            denial_reason_counts[key] = denial_reason_counts.get(key, 0) + 1
    top_denial_reason = (
        max(denial_reason_counts.items(), key=lambda x: x[1])[0]
        if denial_reason_counts
        else None
    )

    return {
        "total": len(txns),
        "failed_count": len(failed),
        "failure_rate": len(failed) / len(txns) if txns else 0.0,
        "top_strategy": top_strategy,
        "interventions_attempted": len(attempts),
        "interventions_successful": len(successful),
        "recovery_rate": len(successful) / len(attempts) if attempts else None,
        "revenue_recovered": revenue_recovered,
        "policy_denied": len(denied),
        "policy_escalated": len(escalated),
        "top_denial_reason": top_denial_reason,
    }


@router.post("/actions/chaos-demo")
def action_chaos_demo(
    payment_method: str = Query("upi"),
    batch_size: int = Query(250, ge=20, le=2000),
    degraded_failure_probability: float = Query(0.70, gt=0, le=0.95),
    degraded_transient_probability: float = Query(0.10, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    
    try:
        pm = PaymentMethod(payment_method)
    except ValueError as e:
        return {"error": f"Invalid payment method: {e}"}

    merchant = db.query(Merchant).first()
    if merchant is None:
        merchant = Merchant(name="Demo Merchant")
        db.add(merchant)
        db.commit()
        db.refresh(merchant)

    customers = (
        db.query(Customer).filter(Customer.merchant_id == merchant.id).limit(300).all()
    )
    if len(customers) < 50:
        customers = generate_customers(db, merchant, 300 - len(customers))

    before_txns = generate_transactions(
        db, customers, batch_size, fixed_payment_method=pm
    )
    before_ids = [t.id for t in before_txns]
    before = _batch_snapshot(db, before_ids)

    chaos.set_active(pm, degraded_failure_probability, degraded_transient_probability)
    try:
        during_txns = generate_transactions(
            db, customers, batch_size, fixed_payment_method=pm
        )
    finally:
        chaos.clear()  

    during_ids = [t.id for t in during_txns]
    during = _batch_snapshot(db, during_ids)

    narrative = []
    narrative.append(
        f"Observed failure rate on {pm.value}: {before['failure_rate']:.1%} → {during['failure_rate']:.1%}."
    )
    if before["recovery_rate"] is not None and during["recovery_rate"] is not None:
        narrative.append(
            f"Recovery success rate among attempted cases: "
            f"{before['recovery_rate']:.1%} → {during['recovery_rate']:.1%}."
        )
    if during["policy_denied"] > before["policy_denied"]:
        reason_note = (
            f" (dominant reason: {during['top_denial_reason']})"
            if during["top_denial_reason"]
            else ""
        )
        narrative.append(
            f"Policy denials rose from {before['policy_denied']} to {during['policy_denied']}"
            f"{reason_note} — the guardrails engaging more often as the same customers "
            f"experienced repeated failures, exactly as designed."
        )

    return {
        "payment_method": pm.value,
        "batch_size": batch_size,
        "before": before,
        "during": during,
        "narrative": narrative,
    }


@router.get("/system/status")
def system_status():
  
    return {
        "groq_configured": bool(settings.GROQ_API_KEY),
        "razorpay_configured": bool(
            settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET
        ),
    }
