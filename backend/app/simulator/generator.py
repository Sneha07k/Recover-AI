import random

import numpy as np
from faker import Faker
from sqlalchemy.orm import Session

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.enums import CustomerType, PaymentMethod, TransactionStatus
from app.models.models import Merchant, Customer, Transaction

fake = Faker()

BASE_FAILURE_PROBABILITY = {
    PaymentMethod.UPI: 0.05,
    PaymentMethod.CREDIT_CARD: 0.12,
    PaymentMethod.DEBIT_CARD: 0.10,
    PaymentMethod.NET_BANKING: 0.08,
    PaymentMethod.WALLET: 0.04,
}


CUSTOMER_FAILURE_MULTIPLIER = {
    CustomerType.RELIABLE: 0.5,
    CustomerType.OCCASIONAL_PAYER: 1.0,
    CustomerType.PRICE_SENSITIVE: 1.1,
    CustomerType.HIGH_VALUE: 0.7,
    CustomerType.FREQUENTLY_FAILS: 2.5,
    CustomerType.SUBSCRIPTION_HEAVY: 1.0,
}

CUSTOMER_TYPE_WEIGHTS = {
    CustomerType.RELIABLE: 0.30,
    CustomerType.OCCASIONAL_PAYER: 0.25,
    CustomerType.PRICE_SENSITIVE: 0.15,
    CustomerType.HIGH_VALUE: 0.10,
    CustomerType.FREQUENTLY_FAILS: 0.10,
    CustomerType.SUBSCRIPTION_HEAVY: 0.10,
}


AMOUNT_MEAN_LOG = {
    CustomerType.RELIABLE: 7.0,
    CustomerType.OCCASIONAL_PAYER: 6.5,
    CustomerType.PRICE_SENSITIVE: 6.0,
    CustomerType.HIGH_VALUE: 9.0,
    CustomerType.FREQUENTLY_FAILS: 6.8,
    CustomerType.SUBSCRIPTION_HEAVY: 7.2,
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
