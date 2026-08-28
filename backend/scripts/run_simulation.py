"""
Run with: python scripts/run_simulation.py [num_customers] [num_transactions]
"""

import sys

from app.database import SessionLocal, init_db
from app.models.enums import TransactionStatus
from app.simulator.generator import run_simulation


def main():
    num_customers = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    num_transactions = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    init_db()
    db = SessionLocal()
    try:
        merchant, customers, transactions = run_simulation(
            db, num_customers=num_customers, num_transactions=num_transactions
        )

        total_amount = sum(t.amount for t in transactions)
        failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
        failed_amount = sum(t.amount for t in failed)

        print(f"Merchant:            {merchant.name}")
        print(f"Customers generated: {len(customers)}")
        print(f"Transactions:        {len(transactions)}")
        print(f"Total volume:        ₹{total_amount:,.2f}")
        print(
            f"Failed transactions: {len(failed)} ({len(failed)/len(transactions):.1%})"
        )
        print(f"Failed volume:       ₹{failed_amount:,.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
