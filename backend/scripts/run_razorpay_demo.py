from app.database import SessionLocal, init_db
from app.integrations.razorpay_client import create_recovery_payment_link
from app.models.enums import RecoveryStrategy, TransactionStatus
from app.models.models import Customer, PolicyDecision, Transaction
from app.policies.engine import ALLOW

MAX_LINKS_TO_CREATE = 3  


def main():
    init_db()
    db = SessionLocal()
    try:
        candidates = (
            db.query(PolicyDecision)
            .filter(
                PolicyDecision.verdict == ALLOW,
                PolicyDecision.strategy.in_(
                    [RecoveryStrategy.INCENTIVE, RecoveryStrategy.CUSTOMER_REMINDER]
                ),
            )
            .limit(MAX_LINKS_TO_CREATE)
            .all()
        )

        pairs = []  

        if candidates:
            for decision in candidates:
                transaction = db.get(Transaction, decision.transaction_id)
                customer = db.get(Customer, decision.customer_id)
                pairs.append((transaction, customer, decision.strategy))
        else:
           
            print(
                "No naturally-chosen INCENTIVE/CUSTOMER_REMINDER decisions found "
                "(see Phase 6's honest note on alternate_payment dominating the "
                "strategy comparison). Falling back to a direct demonstration "
                "on an arbitrary failed transaction instead.\n"
            )
            txn = (
                db.query(Transaction)
                .filter(Transaction.status == TransactionStatus.FAILED)
                .first()
            )
            if txn is None:
                print(
                    "No failed transactions found at all. Run scripts/run_simulation.py first."
                )
                return
            customer = db.get(Customer, txn.customer_id)
            pairs.append((txn, customer, RecoveryStrategy.CUSTOMER_REMINDER))

        print(f"Creating {len(pairs)} real Razorpay TEST MODE payment link(s)...\n")

        for transaction, customer, strategy in pairs:
            try:
                link = create_recovery_payment_link(db, transaction, customer, strategy)
                print(f"txn={transaction.id} strategy={strategy.value}")
                print(f"  {link.short_url}")
                print(f"  status={link.status}\n")
            except Exception as e:
                print(f"txn={transaction.id}: failed - {e}")
                print("  Check RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in backend/.env")
                print("  (must be TEST MODE keys, starting with rzp_test_)\n")

        print(
            "Note: opening these links and completing (or not completing) the "
            "test payment does NOT change this simulation's recorded outcome. "
            "RecoverAI's simulator remains the source of truth (see Phase 9)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
