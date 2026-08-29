"""
Run with: python scripts/run_experiment.py [num_customers] [num_transactions] [seed]

Uses a dedicated database file (data/experiment.db), separate from the
live simulation's database - this experiment's PAYMENT_FAILED events are
never processed by the closed-loop consumers, since the harness itself
decides and simulates outcomes once per condition.
"""

import random
import sys

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.experiments.harness import CONDITIONS, run_experiment
from app.models.enums import TransactionStatus
from app.simulator.generator import (
    create_merchant,
    generate_customers,
    generate_transactions,
)


def main():
    num_customers = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    num_transactions = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42

    random.seed(seed)
    np.random.seed(seed)

    engine = create_engine(
        "sqlite:///../data/experiment.db", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401 registers tables on Base

    Base.metadata.drop_all(bind=engine)  # start clean each run, for reproducibility
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    merchant = create_merchant(db)
    customers = generate_customers(db, merchant, num_customers)
    transactions = generate_transactions(db, customers, num_transactions)

    failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
    customers_by_id = {c.id: c for c in customers}

    print(
        f"Population: {len(transactions)} transactions, {len(failed)} failed, seed={seed}"
    )
    print()

    results = run_experiment(
        db, failed, customers_by_id, conditions=CONDITIONS, seed=seed
    )

    header = (
        f"{'Condition':<18}{'Interventions':>14}{'Recovered':>12}"
        f"{'Recovery Rate':>15}{'Revenue Recovered':>20}{'Cost':>12}"
    )
    print(header)
    print("-" * len(header))
    for cond in CONDITIONS:
        r = results[cond]
        rate_str = f"{r.recovery_rate:.1%}" if r.recovery_rate is not None else "n/a"
        revenue_str = f"\u20b9{r.revenue_recovered:,.2f}"
        cost_str = f"\u20b9{r.total_cost:,.2f}"
        print(
            f"{cond:<18}{r.interventions:>14}{r.successful:>12}"
            f"{rate_str:>15}{revenue_str:>20}{cost_str:>12}"
        )

    print()
    print("False interventions (attempted but did not recover):")
    for cond in CONDITIONS:
        print(f"  {cond:<18} {results[cond].false_interventions}")

    print()
    print("NOTE: retry-limit and per-customer intervention-frequency guardrails")
    print("are inactive in this comparison — each condition evaluates every")
    print("failure as one independent hypothetical intervention rather than a")
    print("persisted multi-attempt history. See app/experiments/harness.py.")

    db.close()


if __name__ == "__main__":
    main()
