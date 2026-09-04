import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.execution.executor import execute_strategy
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import Customer, Merchant, Transaction
from app.policies.constants import MAX_RETRIES
from app.policies.engine import ALLOW, evaluate_policy
from app.strategy.engine import recommend_strategy


def make_session():
    engine = create_engine(
        "sqlite:///../data/failure_demo.db", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_merchant_customer(
    db, opted_out=False, customer_type=CustomerType.FREQUENTLY_FAILS
):
    merchant = Merchant(name="Failure Demo Merchant")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    customer = Customer(
        merchant_id=merchant.id,
        name="Demo Customer",
        email="demo@example.com",
        customer_type=customer_type,
        opted_out=opted_out,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return merchant, customer


def make_failed_transaction(
    db, customer, amount=1500.0, payment_method=PaymentMethod.CREDIT_CARD
):
    txn = Transaction(
        customer_id=customer.id,
        payment_method=payment_method,
        amount=amount,
        status=TransactionStatus.FAILED,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def banner(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def scenario_1_retry_limit_exhaustion(db):
    banner(
        "SCENARIO 1: Repeated retries exhaust the limit; policy blocks further attempts"
    )

    _, customer = make_merchant_customer(
        db, customer_type=CustomerType.FREQUENTLY_FAILS
    )
    txn = make_failed_transaction(
        db, customer, payment_method=PaymentMethod.CREDIT_CARD
    )

    print(
        f"Transaction #{txn.id}: \u20b9{txn.amount:,.2f} via {txn.payment_method.value}, "
        f"customer type FREQUENTLY_FAILS"
    )
    print(f"Policy limit: MAX_RETRIES = {MAX_RETRIES}\n")
    print("Forcing strategy=RETRY on every attempt for this walkthrough, so the")
    print("guardrail is reliably exercised within a few tries. In the live")
    print("system the Strategy Engine picks the strategy itself, but the SAME")
    print("policy check applies no matter who proposes the action.\n")

    for attempt_num in range(1, MAX_RETRIES + 2):
        result = evaluate_policy(
            db, customer.id, txn.id, RecoveryStrategy.RETRY, txn.amount
        )

        print(f"Attempt {attempt_num}: policy verdict = {result.verdict.upper()}")
        for reason in result.reasons:
            print(f"    - {reason}")

        if result.verdict != ALLOW:
            print("\n  -> System correctly REFUSES to keep retrying blindly.")
            print("  -> This is the guardrail working as designed: it protects")
            print("     against runaway automated retries. Nothing 'crashed' -")
            print("     the system is failing SAFELY, on purpose.")
            return

        attempt = execute_strategy(db, txn, customer, RecoveryStrategy.RETRY)
        print(
            f"    Executed. Real outcome: {'SUCCEEDED' if attempt.succeeded else 'FAILED'}"
        )
        if attempt.succeeded:
            print(
                f"\n  -> Recovered on attempt {attempt_num} before hitting the limit."
            )
            print("     (The seed for this walkthrough was chosen so this doesn't")
            print("     happen — if you see this, the underlying odds are genuine.)")
            return

    print("\n  -> Reached the attempt cap without a denial this run.")


def scenario_2_high_value_escalation(db):
    banner(
        "SCENARIO 2: High-value transaction escalates for human review instead of auto-executing"
    )

    _, customer = make_merchant_customer(db, customer_type=CustomerType.HIGH_VALUE)
    txn = make_failed_transaction(
        db, customer, amount=32_000.0, payment_method=PaymentMethod.NET_BANKING
    )

    recommendation = recommend_strategy(
        db, txn.id, customer.id, txn.payment_method, txn.amount
    )
    print(
        f"Transaction #{txn.id}: \u20b9{txn.amount:,.2f} (above the high-value threshold)"
    )
    print(
        f"Strategy Engine recommends: {recommendation.strategy.value} "
        f"(expected value \u20b9{recommendation.expected_value:,.2f})\n"
    )

    result = evaluate_policy(
        db, customer.id, txn.id, recommendation.strategy, txn.amount
    )
    print(f"Policy verdict = {result.verdict.upper()}")
    for reason in result.reasons:
        print(f"    - {reason}")

    print("\n  -> The system does NOT execute automatically here, even though")
    print("     the Strategy Engine found a positive-EV action. High-value")
    print("     cases require a human to sign off before anything happens -")
    print("     this is deliberate, not a bug.")


def scenario_3_opt_out_respected(db):
    banner(
        "SCENARIO 3: An opted-out customer is protected from customer-facing contact"
    )

    _, customer = make_merchant_customer(
        db, opted_out=True, customer_type=CustomerType.OCCASIONAL_PAYER
    )
    txn = make_failed_transaction(
        db, customer, amount=800.0, payment_method=PaymentMethod.UPI
    )

    print(f"Transaction #{txn.id}: customer has opted out of recovery communications\n")

    for strategy in [RecoveryStrategy.INCENTIVE, RecoveryStrategy.RETRY]:
        result = evaluate_policy(db, customer.id, txn.id, strategy, txn.amount)
        print(
            f"Proposed strategy: {strategy.value:<20} verdict = {result.verdict.upper()}"
        )
        for reason in result.reasons:
            print(f"    - {reason}")

    print("\n  -> INCENTIVE is blocked (it would contact the customer directly).")
    print("     RETRY is still allowed (it's a silent payment retry, not")
    print("     customer contact). The guardrail is precise, not a blanket ban.")


def scenario_4_allowed_attempt_that_fails(db):
    banner(
        "SCENARIO 4: A fully-authorized attempt that genuinely does not recover the money"
    )

    _, customer = make_merchant_customer(
        db, customer_type=CustomerType.FREQUENTLY_FAILS
    )
    txn = make_failed_transaction(
        db, customer, amount=600.0, payment_method=PaymentMethod.CREDIT_CARD
    )

    recommendation = recommend_strategy(
        db, txn.id, customer.id, txn.payment_method, txn.amount
    )
    result = evaluate_policy(
        db, customer.id, txn.id, recommendation.strategy, txn.amount
    )

    print(
        f"Transaction #{txn.id}: strategy={recommendation.strategy.value}, "
        f"policy verdict={result.verdict.upper()}"
    )

    if result.verdict == ALLOW and recommendation.strategy != RecoveryStrategy.STOP:
        attempt = execute_strategy(db, txn, customer, recommendation.strategy)
        print(
            f"Executed. Real outcome: {'SUCCEEDED' if attempt.succeeded else 'FAILED'}"
        )
        if not attempt.succeeded:
            print("\n  -> The system was fully authorized to act, and did - it just")
            print("     didn't work. This IS recorded honestly as a failed")
            print("     intervention (see 'Failed interventions' in /metrics),")
            print("     never silently dropped or reclassified as a success.")
        else:
            print("\n  -> This particular draw succeeded. Re-run for a fresh outcome -")
            print("     both results are legitimate given the real probabilities.")
    else:
        print("(This run didn't land on an executable case — re-run for a fresh draw.)")


def scenario_5_invalid_action(db):
    banner("SCENARIO 5: An invalid/unrecognized action is defensively denied")

    _, customer = make_merchant_customer(db)
    txn = make_failed_transaction(db, customer)

    result = evaluate_policy(db, customer.id, txn.id, "not_a_real_strategy", txn.amount)
    print("Proposed action: 'not_a_real_strategy'")
    print(f"Policy verdict = {result.verdict.upper()}")
    for reason in result.reasons:
        print(f"    - {reason}")
    print("\n  -> Even a malformed or unexpected action is safely rejected,")
    print("     never silently ignored or passed through.")


def main():
   
    np.random.seed(5)

    db = make_session()
    try:
        scenario_1_retry_limit_exhaustion(db)
        scenario_2_high_value_escalation(db)
        scenario_3_opt_out_respected(db)
        scenario_4_allowed_attempt_that_fails(db)
        scenario_5_invalid_action(db)

        banner("SUMMARY")
        print("Every scenario above ended in some form of 'no recovery' - a denial,")
        print("an escalation, a policy block, or a genuine failed attempt. None of")
        print("them are hidden or silently discarded: every one is a real row in")
        print("risk_assessments, strategy_decisions, policy_decisions, or")
        print("recovery_attempts, visible through the Phase 10 audit trail API")
        print("and the Phase 11 dashboard.")
        print("\nThis is what 'fails gracefully' means for RecoverAI: bounded,")
        print("explainable, auditable failure - never silent, never unbounded.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
