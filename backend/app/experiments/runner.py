"""
Reusable "set up a fresh population and run the comparison" glue,
extracted from scripts/run_experiment.py so both the CLI script and the
web API's /actions/experiment endpoint call the exact same code path.
No logic changed from the original script - only moved.
"""

import random

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.events.bus import EventBus
from app.experiments.harness import CONDITIONS, run_experiment
from app.models.enums import TransactionStatus
from app.simulator.generator import (
    create_merchant,
    generate_customers,
    generate_transactions,
)

EXPERIMENT_DB_URL = "sqlite:///../data/experiment.db"


def run_experiment_end_to_end(
    num_customers: int = 300, num_transactions: int = 3000, seed: int = 42
) -> dict:
    """
    Uses a dedicated database file, separate from the live simulation's
    database - this experiment's PAYMENT_FAILED events are never processed
    by the closed-loop consumers, since the harness itself decides and
    simulates outcomes once per condition.

    Returns a plain dict (JSON-serializable) so this can be reused by both
    the CLI script (which formats it as a table) and the API (which
    returns it directly).
    """
    random.seed(seed)
    np.random.seed(seed)

    engine = create_engine(EXPERIMENT_DB_URL, connect_args={"check_same_thread": False})
    from app.models import models  # noqa: F401 registers tables on Base

    Base.metadata.drop_all(bind=engine)  # start clean each run, for reproducibility
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        merchant = create_merchant(db)
        customers = generate_customers(db, merchant, num_customers)
        # A fresh EventBus with no subscribers, so this isolated population
        # never triggers the deployed app's global closed-loop consumers
        # (which would otherwise silently execute their own strategy on
        # each transaction before the harness gets a chance to).
        isolated_bus = EventBus()
        transactions = generate_transactions(
            db, customers, num_transactions, bus=isolated_bus
        )

        failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
        customers_by_id = {c.id: c for c in customers}

        results = run_experiment(
            db, failed, customers_by_id, conditions=CONDITIONS, seed=seed
        )

        return {
            "num_customers": num_customers,
            "num_transactions": num_transactions,
            "seed": seed,
            "total_failed": len(failed),
            "conditions": [
                {
                    "condition": cond,
                    "interventions": results[cond].interventions,
                    "successful": results[cond].successful,
                    "false_interventions": results[cond].false_interventions,
                    "recovery_rate": results[cond].recovery_rate,
                    "revenue_recovered": results[cond].revenue_recovered,
                    "total_cost": results[cond].total_cost,
                }
                for cond in CONDITIONS
            ],
        }
    finally:
        db.close()
