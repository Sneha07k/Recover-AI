import os
import time

import joblib
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics.metrics import compute_metrics
from app.config import settings
from app.database import Base, engine, get_db, init_db
from app.demo.failure_scenarios import run_all_failure_scenarios
from app.events.consumers import register_default_consumers
from app.experiments.runner import run_experiment_end_to_end
from app.ml.features import build_recovery_dataset
from app.ml.train import compute_rule_based_baseline_auc, train_and_evaluate
from app.simulator.generator import run_simulation
from app.strategy.probability import invalidate_model_cache

router = APIRouter(tags=["actions"])

_consumers_registered = False


def _ensure_consumers_registered():
    """
    register_default_consumers() only needs to run once per process — it
    just wires subscriptions onto the shared event bus. Calling it again
    would double-subscribe every consumer.
    """
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
    """
    Runs a real simulation through the full closed loop (Phases 2-9) and
    returns the resulting headline metrics — the same function
    scripts/run_simulation.py calls, just triggered from the dashboard
    instead of a terminal. Timed so the dashboard can show real,
    live-measured throughput (Phase 13's performance work made this fast
    enough to demo interactively at all).
    """
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
    """
    Trains the Phase 5 recovery-prediction model on whatever data
    currently exists, saves it to disk, and invalidates the in-process
    model cache so the very next /actions/simulate call actually uses it.

    Also computes the rule-based baseline's AUC on the exact same data,
    live, so the honest ML-vs-baseline comparison (Phase 5/12's finding)
    is visible immediately rather than buried in a CLI report.
    """
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
    """
    Runs the Phase 12 fair strategy comparison (no_intervention vs.
    immediate_retry vs. rule_based vs. ml_based) against a dedicated,
    isolated population and returns the results.
    """
    return run_experiment_end_to_end(num_customers, num_transactions, seed)


@router.post("/actions/failure-demo")
def action_failure_demo(seed: int = Query(5)):
    """
    Runs the Phase 15 failure demonstration and returns each scenario's
    narrative as structured data for the dashboard to render.
    """
    return {"scenarios": run_all_failure_scenarios(seed)}


@router.post("/actions/reset")
def action_reset():
    """
    Drops and recreates every table in the main database — a clean slate
    for a fresh demo run. Does not touch the separate experiment.db or
    failure_demo.db files used by the two actions above.
    """
    from app.models import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    init_db()
    return {"reset": True}


@router.get("/system/status")
def system_status():
    """
    Reports whether the optional Groq (LLM agent, Phase 7) and Razorpay
    (test-mode payment links, Phase 14) integrations are configured —
    booleans only, never the actual key values. Lets the dashboard prove
    these integrations genuinely exist in the codebase even when a given
    deployment doesn't have keys configured.
    """
    return {
        "groq_configured": bool(settings.GROQ_API_KEY),
        "razorpay_configured": bool(
            settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET
        ),
    }
