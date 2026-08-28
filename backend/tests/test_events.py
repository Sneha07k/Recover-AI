from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.events.bus import EventBus
from app.events.enums import EventType
from app.events.schemas import Event
from app.models.models import EventLog


def make_test_session():
    """
    Fresh in-memory database per test, so events from one test never
    leak into another test's assertions.
    """
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models  # noqa: F401 registers tables on Base

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_publish_persists_event_to_db():
    db = make_test_session()
    try:
        bus = EventBus()
        event = Event(
            event_type=EventType.PAYMENT_FAILED,
            entity_type="transaction",
            entity_id=1,
            payload={"amount": 500.0},
        )
        bus.publish(db, event)

        stored = db.query(EventLog).all()
        assert len(stored) == 1
        assert stored[0].event_type == "payment_failed"
        assert stored[0].payload["amount"] == 500.0
    finally:
        db.close()


def test_subscribers_are_called_on_publish():
    db = make_test_session()
    try:
        bus = EventBus()
        received = []
        bus.subscribe(EventType.PAYMENT_FAILED, lambda e: received.append(e))

        event = Event(
            event_type=EventType.PAYMENT_FAILED,
            entity_type="transaction",
            entity_id=2,
            payload={},
        )
        bus.publish(db, event)

        assert len(received) == 1
        assert received[0].entity_id == 2
    finally:
        db.close()


def test_subscribers_not_called_for_other_event_types():
    db = make_test_session()
    try:
        bus = EventBus()
        received = []
        bus.subscribe(EventType.PAYMENT_FAILED, lambda e: received.append(e))

        event = Event(
            event_type=EventType.PAYMENT_SUCCESS,
            entity_type="transaction",
            entity_id=3,
            payload={},
        )
        bus.publish(db, event)

        assert len(received) == 0
    finally:
        db.close()


def test_generate_transactions_emits_two_events_per_transaction():
    from app.simulator.generator import (
        create_merchant,
        generate_customers,
        generate_transactions,
    )

    db = make_test_session()
    try:
        merchant = create_merchant(db)
        customers = generate_customers(db, merchant, 20)
        transactions = generate_transactions(db, customers, 50)

        events = db.query(EventLog).all()
        # PAYMENT_CREATED + (PAYMENT_SUCCESS or PAYMENT_FAILED) per transaction
        assert len(events) == len(transactions) * 2
    finally:
        db.close()
