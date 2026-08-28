"""
Run with: python scripts/run_simulation.py [num_customers] [num_transactions]
"""

import sys

from app.database import SessionLocal, init_db
from app.events.consumers import register_default_consumers
from app.models.enums import TransactionStatus
from app.models.models import EventLog, RiskAssessment
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

        print(f"Merchant:            {merchant.name}")
        print(f"Customers generated: {len(customers)}")
        print(f"Transactions:        {len(transactions)}")
        print(f"Total volume:        ₹{total_amount:,.2f}")
        print(
            f"Failed transactions: {len(failed)} ({len(failed)/len(transactions):.1%})"
        )
        print(f"Failed volume:       ₹{failed_amount:,.2f}")
        print(f"Events recorded:     {event_count}")

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
