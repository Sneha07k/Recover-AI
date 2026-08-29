import random

import numpy as np
from faker import Faker
from sqlalchemy.orm import Session

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.enums import CustomerType, FailureType, PaymentMethod, TransactionStatus
from app.models.models import Merchant, Customer, RecoveryAttempt, Transaction

fake = Faker()

# Base failure probability per payment method. Roughly reflects real-world
# patterns: UPI/wallets are quite reliable, cards fail more due to bank-side
# declines, expiry, insufficient funds, etc.
BASE_FAILURE_PROBABILITY = {
    PaymentMethod.UPI: 0.05,
    PaymentMethod.CREDIT_CARD: 0.12,
    PaymentMethod.DEBIT_CARD: 0.10,
    PaymentMethod.NET_BANKING: 0.08,
    PaymentMethod.WALLET: 0.04,
}

# Multiplies the base failure probability based on the customer's behavioral
# profile. A FREQUENTLY_FAILS customer is 2.5x more likely to fail on any
# given payment method than the base rate for that method.
CUSTOMER_FAILURE_MULTIPLIER = {
    CustomerType.RELIABLE: 0.5,
    CustomerType.OCCASIONAL_PAYER: 1.0,
    CustomerType.PRICE_SENSITIVE: 1.1,
    CustomerType.HIGH_VALUE: 0.7,
    CustomerType.FREQUENTLY_FAILS: 2.5,
    CustomerType.SUBSCRIPTION_HEAVY: 1.0,
}

# Rough distribution of customer types across the simulated population.
# Must sum to 1.0.
CUSTOMER_TYPE_WEIGHTS = {
    CustomerType.RELIABLE: 0.30,
    CustomerType.OCCASIONAL_PAYER: 0.25,
    CustomerType.PRICE_SENSITIVE: 0.15,
    CustomerType.HIGH_VALUE: 0.10,
    CustomerType.FREQUENTLY_FAILS: 0.10,
    CustomerType.SUBSCRIPTION_HEAVY: 0.10,
}

# Mean of the underlying normal distribution (log-space) for each customer
# type's order amount. e.g. mean_log=7.0 -> typical amount around e^7 â‰ˆ 1,100.
AMOUNT_MEAN_LOG = {
    CustomerType.RELIABLE: 7.0,
    CustomerType.OCCASIONAL_PAYER: 6.5,
    CustomerType.PRICE_SENSITIVE: 6.0,
    CustomerType.HIGH_VALUE: 9.0,
    CustomerType.FREQUENTLY_FAILS: 6.8,
    CustomerType.SUBSCRIPTION_HEAVY: 7.2,
}

# Probability that a given failure is TRANSIENT (network blip, temporary
# provider issue) rather than PERMANENT (card declined, blocked, expired).
# This is the simulator's hidden ground truth for whether a retry would
# actually work â€” it must never be exposed as a feature to any predictor.
TRANSIENT_PROBABILITY_BY_METHOD = {
    PaymentMethod.UPI: 0.85,
    PaymentMethod.WALLET: 0.85,
    PaymentMethod.NET_BANKING: 0.70,
    PaymentMethod.DEBIT_CARD: 0.60,
    PaymentMethod.CREDIT_CARD: 0.50,
}

# Additive adjustment to the transient probability based on customer
# behavior â€” a FREQUENTLY_FAILS customer's failures skew more permanent
# (e.g. genuinely blocked cards) rather than transient network issues.
TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE = {
    CustomerType.RELIABLE: 0.05,
    CustomerType.OCCASIONAL_PAYER: 0.0,
    CustomerType.PRICE_SENSITIVE: 0.0,
    CustomerType.HIGH_VALUE: 0.05,
    CustomerType.FREQUENTLY_FAILS: -0.30,
    CustomerType.SUBSCRIPTION_HEAVY: 0.0,
}

# Given the TRUE failure type, probability that an immediate retry succeeds.
# Transient failures usually resolve themselves; permanent ones almost never do.
RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE = {
    FailureType.TRANSIENT: 0.80,
    FailureType.PERMANENT: 0.05,
}


def create_merchant(db: Session, name: str = "Demo Merchant") -> Merchant:
    merchant = Merchant(name=name)
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def generate_customers(db: Session, merchant: Merchant, n: int) -> list[Customer]:
    types = list(CUSTOMER_TYPE_WEIGHTS.keys())
    weights = list(CUSTOMER_TYPE_WEIGHTS.values())

    customers = []
    for _ in range(n):
        customer_type = random.choices(types, weights=weights, k=1)[0]
        customer = Customer(
            merchant_id=merchant.id,
            name=fake.name(),
            email=fake.email(),
            customer_type=customer_type,
        )
        db.add(customer)
        customers.append(customer)

    db.commit()
    for c in customers:
        db.refresh(c)
    return customers


def generate_transactions(
    db: Session, customers: list[Customer], n: int
) -> list[Transaction]:
    methods = list(PaymentMethod)

    transactions = []
    for _ in range(n):
        customer = random.choice(customers)
        payment_method = random.choice(methods)

        # Amount: log-normal, parameterized by customer type, capped so a
        # rare extreme sample doesn't produce an absurd outlier.
        mean_log = AMOUNT_MEAN_LOG[customer.customer_type]
        amount = float(np.random.lognormal(mean=mean_log, sigma=0.6))
        amount = round(min(amount, 200_000), 2)

        # Failure probability combines the payment method's base rate with
        # this customer's behavioral multiplier, capped below 1.0.
        fail_prob = BASE_FAILURE_PROBABILITY[payment_method]
        fail_prob *= CUSTOMER_FAILURE_MULTIPLIER[customer.customer_type]
        fail_prob = min(fail_prob, 0.95)

        # Bernoulli trial: one weighted coin flip decides success vs failure.
        will_fail = np.random.random() < fail_prob
        status = TransactionStatus.FAILED if will_fail else TransactionStatus.SUCCESS

        txn = Transaction(
            customer_id=customer.id,
            payment_method=payment_method,
            amount=amount,
            status=status,
        )
        db.add(txn)
        db.flush()  # assigns txn.id without committing, so events can reference it

        event_payload = {
            "amount": amount,
            "payment_method": payment_method.value,
            "customer_id": customer.id,
        }

        # Every transaction announces its own lifecycle: created, then the
        # outcome. Nothing downstream reads txn.status directly anymore â€”
        # they react to these events instead.
        event_bus.publish(
            db,
            Event(
                event_type=EventType.PAYMENT_CREATED,
                entity_type="transaction",
                entity_id=txn.id,
                payload=event_payload,
            ),
        )
        event_bus.publish(
            db,
            Event(
                event_type=EventType.PAYMENT_FAILED if will_fail else EventType.PAYMENT_SUCCESS,
                entity_type="transaction",
                entity_id=txn.id,
                payload=event_payload,
            ),
        )

        if will_fail:
            # Simplified, unconditional retry: every failure gets one retry
            # attempt so we accumulate historical labeled data. Phases 6-9
            # replace this with a real bounded decision + policy-gated flow.
            transient_prob = TRANSIENT_PROBABILITY_BY_METHOD[payment_method]
            transient_prob += TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE[customer.customer_type]
            transient_prob = min(max(transient_prob, 0.05), 0.95)

            failure_type = (
                FailureType.TRANSIENT
                if np.random.random() < transient_prob
                else FailureType.PERMANENT
            )
            recovery_success_prob = RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE[failure_type]
            recovered = np.random.random() < recovery_success_prob

            attempt = RecoveryAttempt(
                transaction_id=txn.id,
                failure_type=failure_type,
                succeeded=recovered,
                amount_recovered=amount if recovered else 0.0,
            )
            db.add(attempt)
            db.flush()

            event_bus.publish(
                db,
                Event(
                    event_type=EventType.RECOVERY_ATTEMPTED,
                    entity_type="transaction",
                    entity_id=txn.id,
                    payload=event_payload,
                ),
            )
            event_bus.publish(
                db,
                Event(
                    event_type=EventType.RECOVERY_SUCCESS if recovered else EventType.RECOVERY_FAILED,
                    entity_type="transaction",
                    entity_id=txn.id,
                    payload={**event_payload, "amount_recovered": attempt.amount_recovered},
                ),
            )

        transactions.append(txn)

    for t in transactions:
        db.refresh(t)
    return transactions


def run_simulation(
    db: Session,
    num_customers: int = 200,
    num_transactions: int = 1000,
    merchant_name: str = "Demo Merchant",
):
    """Generates one merchant, its customers, and its transaction stream."""
    merchant = create_merchant(db, name=merchant_name)
    customers = generate_customers(db, merchant, num_customers)
    transactions = generate_transactions(db, customers, num_transactions)
    return merchant, customers, transactions

