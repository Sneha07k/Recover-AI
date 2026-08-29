import random

import numpy as np
from faker import Faker
from sqlalchemy.orm import Session

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.enums import PaymentMethod, TransactionStatus
from app.models.models import Merchant, Customer, Transaction
from app.simulator.ground_truth import (
    AMOUNT_MEAN_LOG,
    BASE_FAILURE_PROBABILITY,
    CUSTOMER_FAILURE_MULTIPLIER,
    CUSTOMER_TYPE_WEIGHTS,
    OPT_OUT_PROBABILITY,
)

fake = Faker()


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
            opted_out=random.random() < OPT_OUT_PROBABILITY,
        )
        db.add(customer)
        customers.append(customer)

    db.commit()
    for c in customers:
        db.refresh(c)
    return customers


def generate_transactions(
    db: Session, customers: list[Customer], n: int, batch_size: int = 200
) -> list[Transaction]:
    """
    Generates transactions and detects failures only. As of Phase 9, the
    simulator's job stops here — everything about deciding what to do
    about a failure and simulating whether recovery works now lives in
    the closed-loop controller (app/execution/controller.py), which is
    wired to PAYMENT_FAILED as an event consumer, not baked into this
    generation loop.

    Phase 13: commits happen every `batch_size` transactions instead of
    on every single event (which is what every downstream consumer used
    to do too — see app/events/bus.py). This is the batching change that
    makes scaling to 10,000+ transactions practical. Trade-off, stated
    plainly: if the process crashes mid-batch, that batch's work — up to
    batch_size transactions' worth of events, risk assessments, strategy
    decisions, policy checks, and recovery attempts — is lost.
    """
    methods = list(PaymentMethod)

    transactions = []
    for i in range(n):
        customer = random.choice(customers)
        payment_method = random.choice(methods)

        mean_log = AMOUNT_MEAN_LOG[customer.customer_type]
        amount = float(np.random.lognormal(mean=mean_log, sigma=0.6))
        amount = round(min(amount, 200_000), 2)

        fail_prob = BASE_FAILURE_PROBABILITY[payment_method]
        fail_prob *= CUSTOMER_FAILURE_MULTIPLIER[customer.customer_type]
        fail_prob = min(fail_prob, 0.95)

        will_fail = np.random.random() < fail_prob
        status = TransactionStatus.FAILED if will_fail else TransactionStatus.SUCCESS

        txn = Transaction(
            customer_id=customer.id,
            payment_method=payment_method,
            amount=amount,
            status=status,
        )
        db.add(txn)
        db.flush()

        event_payload = {
            "amount": amount,
            "payment_method": payment_method.value,
            "customer_id": customer.id,
        }

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
                event_type=(
                    EventType.PAYMENT_FAILED if will_fail else EventType.PAYMENT_SUCCESS
                ),
                entity_type="transaction",
                entity_id=txn.id,
                payload=event_payload,
            ),
        )

        transactions.append(txn)

        if (i + 1) % batch_size == 0:
            db.commit()

    db.commit()  # final commit for any remainder below batch_size

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
