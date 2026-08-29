"""
Run with: python scripts/run_simulation.py [num_customers] [num_transactions]
"""

import sys

from app.analytics.metrics import compute_metrics
from app.database import SessionLocal, init_db
from app.events.consumers import register_default_consumers
from app.models.models import RiskAssessment
from app.simulator.generator import run_simulation


def main():
    num_customers = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    num_transactions = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    init_db()
    register_default_consumers()

    db = SessionLocal()
    try:
        merchant, customers, transactions = run_simulation(
            db, num_customers=num_customers, num_transactions=num_transactions
        )

        m = compute_metrics(db)

        print(f"Merchant:            {merchant.name}")
        print(f"Customers generated: {len(customers)}")
        print()
        print(f"Transactions simulated:  {m.transactions_total:,}")
        print(f"Revenue processed:       ₹{m.revenue_processed:,.2f}")
        print(
            f"Revenue at risk:         ₹{m.revenue_at_risk:,.2f} ({m.transactions_failed} failed transactions)"
        )
        print()
        print(f"Interventions attempted: {m.interventions_attempted:,}")
        print(f"Successful recoveries:   {m.successful_recoveries:,}")
        print(f"Failed interventions:    {m.failed_interventions:,}")
        print(f"Escalations:             {m.escalations:,}")
        print(f"Stopped by policy:       {m.stopped_by_policy:,}")
        print(
            f"Stopped by strategy:     {m.stopped_by_strategy:,} (engine itself chose not to act)"
        )
        print()
        print(f"Revenue recovered:       ₹{m.revenue_recovered:,.2f}")
        if m.recovery_rate is not None:
            print(f"Recovery rate:           {m.recovery_rate:.1%}")

        top_risks = (
            db.query(RiskAssessment)
            .order_by(RiskAssessment.risk_score.desc())
            .limit(5)
            .all()
        )
        print("\nTop 5 recoverable-revenue opportunities:")
        for r in top_risks:
            print(
                f"  txn={r.transaction_id:<5} amount=₹{r.amount:>9,.2f}  "
                f"fail_prob={r.failure_probability:.2f}  "
                f"recover_prob={r.recovery_probability:.2f}  "
                f"risk_score={r.risk_score:,.2f}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
