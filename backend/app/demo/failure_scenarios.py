"""
The five failure-demonstration scenarios, extracted from
scripts/run_failure_demo.py so both the CLI script and the web API's
/actions/failure-demo endpoint run the exact same logic. Every call to
evaluate_policy/execute_strategy/recommend_strategy is unchanged from the
original script - only the OUTPUT mechanism changed, from printing
directly to returning a list of lines that the caller prints (CLI) or
serializes (API).

See the CLI script for the full explanation of the fixed random seed
used for Scenario 1's reliability.
"""

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

FAILURE_DEMO_DB_URL = "sqlite:///../data/failure_demo.db"
DEMO_SEED = 5  # see module docstring in scripts/run_failure_demo.py for why


def make_session():
    engine = create_engine(
        FAILURE_DEMO_DB_URL, connect_args={"check_same_thread": False}
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


def scenario_1_retry_limit_exhaustion(db) -> tuple[str, list[str]]:
    title = (
        "SCENARIO 1: Repeated retries exhaust the limit; policy blocks further attempts"
    )
    lines = []

    _, customer = make_merchant_customer(
        db, customer_type=CustomerType.FREQUENTLY_FAILS
    )
    txn = make_failed_transaction(
        db, customer, payment_method=PaymentMethod.CREDIT_CARD
    )

    lines.append(
        f"Transaction #{txn.id}: \u20b9{txn.amount:,.2f} via {txn.payment_method.value}, "
        f"customer type FREQUENTLY_FAILS"
    )
    lines.append(f"Policy limit: MAX_RETRIES = {MAX_RETRIES}")
    lines.append("")
    lines.append(
        "Forcing strategy=RETRY on every attempt for this walkthrough, so the "
        "guardrail is reliably exercised within a few tries. In the live system "
        "the Strategy Engine picks the strategy itself, but the SAME policy check "
        "applies no matter who proposes the action."
    )
    lines.append("")

    for attempt_num in range(1, MAX_RETRIES + 2):
        result = evaluate_policy(
            db, customer.id, txn.id, RecoveryStrategy.RETRY, txn.amount
        )

        lines.append(
            f"Attempt {attempt_num}: policy verdict = {result.verdict.upper()}"
        )
        for reason in result.reasons:
            lines.append(f"    - {reason}")

        if result.verdict != ALLOW:
            lines.append("")
            lines.append(
                "-> System correctly REFUSES to keep retrying blindly. This is the "
                "guardrail working as designed: it protects against runaway "
                "automated retries. Nothing 'crashed' - the system is failing "
                "SAFELY, on purpose."
            )
            return title, lines

        attempt = execute_strategy(db, txn, customer, RecoveryStrategy.RETRY)
        lines.append(
            f"    Executed. Real outcome: {'SUCCEEDED' if attempt.succeeded else 'FAILED'}"
        )
        if attempt.succeeded:
            lines.append("")
            lines.append(
                f"-> Recovered on attempt {attempt_num} before hitting the limit."
            )
            return title, lines

    lines.append("")
    lines.append("-> Reached the attempt cap without a denial this run.")
    return title, lines


def scenario_2_high_value_escalation(db) -> tuple[str, list[str]]:
    title = "SCENARIO 2: High-value transaction escalates for human review instead of auto-executing"
    lines = []

    _, customer = make_merchant_customer(db, customer_type=CustomerType.HIGH_VALUE)
    txn = make_failed_transaction(
        db, customer, amount=32_000.0, payment_method=PaymentMethod.NET_BANKING
    )

    recommendation = recommend_strategy(
        db, txn.id, customer.id, txn.payment_method, txn.amount
    )
    lines.append(
        f"Transaction #{txn.id}: \u20b9{txn.amount:,.2f} (above the high-value threshold)"
    )
    lines.append(
        f"Strategy Engine recommends: {recommendation.strategy.value} "
        f"(expected value \u20b9{recommendation.expected_value:,.2f})"
    )
    lines.append("")

    result = evaluate_policy(
        db, customer.id, txn.id, recommendation.strategy, txn.amount
    )
    lines.append(f"Policy verdict = {result.verdict.upper()}")
    for reason in result.reasons:
        lines.append(f"    - {reason}")

    lines.append("")
    lines.append(
        "-> The system does NOT execute automatically here, even though the "
        "Strategy Engine found a positive-EV action. High-value cases require "
        "a human to sign off before anything happens - this is deliberate, "
        "not a bug."
    )
    return title, lines


def scenario_3_opt_out_respected(db) -> tuple[str, list[str]]:
    title = (
        "SCENARIO 3: An opted-out customer is protected from customer-facing contact"
    )
    lines = []

    _, customer = make_merchant_customer(
        db, opted_out=True, customer_type=CustomerType.OCCASIONAL_PAYER
    )
    txn = make_failed_transaction(
        db, customer, amount=800.0, payment_method=PaymentMethod.UPI
    )

    lines.append(
        f"Transaction #{txn.id}: customer has opted out of recovery communications"
    )
    lines.append("")

    for strategy in [RecoveryStrategy.INCENTIVE, RecoveryStrategy.RETRY]:
        result = evaluate_policy(db, customer.id, txn.id, strategy, txn.amount)
        lines.append(
            f"Proposed strategy: {strategy.value:<20} verdict = {result.verdict.upper()}"
        )
        for reason in result.reasons:
            lines.append(f"    - {reason}")

    lines.append("")
    lines.append(
        "-> INCENTIVE is blocked (it would contact the customer directly). RETRY "
        "is still allowed (it's a silent payment retry, not customer contact). "
        "The guardrail is precise, not a blanket ban."
    )
    return title, lines


def scenario_4_allowed_attempt_that_fails(db) -> tuple[str, list[str]]:
    title = "SCENARIO 4: A fully-authorized attempt that genuinely does not recover the money"
    lines = []

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

    lines.append(
        f"Transaction #{txn.id}: strategy={recommendation.strategy.value}, "
        f"policy verdict={result.verdict.upper()}"
    )

    if result.verdict == ALLOW and recommendation.strategy != RecoveryStrategy.STOP:
        attempt = execute_strategy(db, txn, customer, recommendation.strategy)
        lines.append(
            f"Executed. Real outcome: {'SUCCEEDED' if attempt.succeeded else 'FAILED'}"
        )
        if not attempt.succeeded:
            lines.append("")
            lines.append(
                "-> The system was fully authorized to act, and did - it just "
                "didn't work. This IS recorded honestly as a failed intervention "
                "(see 'Failed interventions' in /metrics), never silently dropped "
                "or reclassified as a success."
            )
        else:
            lines.append("")
            lines.append(
                "-> This particular draw succeeded. Both results are legitimate "
                "given the real probabilities."
            )
    else:
        lines.append("(This run didn't land on an executable case.)")
    return title, lines


def scenario_5_invalid_action(db) -> tuple[str, list[str]]:
    title = "SCENARIO 5: An invalid/unrecognized action is defensively denied"
    lines = []

    _, customer = make_merchant_customer(db)
    txn = make_failed_transaction(db, customer)

    result = evaluate_policy(db, customer.id, txn.id, "not_a_real_strategy", txn.amount)
    lines.append("Proposed action: 'not_a_real_strategy'")
    lines.append(f"Policy verdict = {result.verdict.upper()}")
    for reason in result.reasons:
        lines.append(f"    - {reason}")
    lines.append("")
    lines.append(
        "-> Even a malformed or unexpected action is safely rejected, never "
        "silently ignored or passed through."
    )
    return title, lines


ALL_SCENARIOS = [
    scenario_1_retry_limit_exhaustion,
    scenario_2_high_value_escalation,
    scenario_3_opt_out_respected,
    scenario_4_allowed_attempt_that_fails,
    scenario_5_invalid_action,
]


def run_all_failure_scenarios(seed: int = DEMO_SEED) -> list[dict]:
    """
    Runs every scenario against a fresh, isolated database and returns
    structured results — used by the web API. The CLI script uses the
    same ALL_SCENARIOS list directly so it can print as it goes.
    """
    import numpy as np

    np.random.seed(seed)
    db = make_session()
    try:
        results = []
        for scenario_fn in ALL_SCENARIOS:
            title, lines = scenario_fn(db)
            results.append({"title": title, "lines": lines})
        return results
    finally:
        db.close()
