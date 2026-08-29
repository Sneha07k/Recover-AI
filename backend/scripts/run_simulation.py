"""
Run with: python scripts/run_simulation.py [num_customers] [num_transactions]
"""

import sys

from sqlalchemy import func

from app.database import SessionLocal, init_db
from app.events.consumers import register_default_consumers
from app.models.enums import TransactionStatus, RecoveryStrategy
from app.models.models import (
    EventLog,
    PolicyDecision,
    RecoveryAttempt,
    RiskAssessment,
    Transaction,
)
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

        total_amount = sum(t.amount for t in transactions)
        failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
        failed_amount = sum(t.amount for t in failed)
        event_count = db.query(EventLog).count()

        attempts = db.query(RecoveryAttempt).all()
        successful = [a for a in attempts if a.succeeded]
        failed_attempts = [a for a in attempts if not a.succeeded]
        revenue_recovered = sum(a.amount_recovered for a in successful)

        escalations = (
            db.query(PolicyDecision)
            .filter(PolicyDecision.verdict == "escalate")
            .count()
        )
        stopped_by_policy = (
            db.query(PolicyDecision).filter(PolicyDecision.verdict == "deny").count()
        )
        stopped_by_strategy = (
            db.query(PolicyDecision)
            .filter(PolicyDecision.strategy == RecoveryStrategy.STOP)
            .count()
        )

        print(f"Merchant:            {merchant.name}")
        print(f"Customers generated: {len(customers)}")
        print()
        print(f"Transactions simulated:  {len(transactions):,}")
        print(f"Revenue processed:       ₹{total_amount:,.2f}")
        print(
            f"Revenue at risk:         ₹{failed_amount:,.2f} ({len(failed)} failed transactions)"
        )
        print(f"Events recorded:         {event_count:,}")
        print()
        print(f"Interventions attempted: {len(attempts):,}")
        print(f"Successful recoveries:   {len(successful):,}")
        print(f"Failed interventions:    {len(failed_attempts):,}")
        print(f"Escalations:             {escalations:,}")
        print(f"Stopped by policy:       {stopped_by_policy:,}")
        print(
            f"Stopped by strategy:     {stopped_by_strategy:,} (engine itself chose not to act)"
        )
        print()
        print(f"Revenue recovered:       ₹{revenue_recovered:,.2f}")
        if attempts:
            print(f"Recovery rate:           {len(successful) / len(attempts):.1%}")

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
