from collections import defaultdict
from typing import Callable

from sqlalchemy.orm import Session

from app.events.enums import EventType
from app.events.schemas import Event
from app.models.models import EventLog


class EventBus:
    """
    A simple in-process publish/subscribe system. Producers call publish()
    with an Event; every function that has subscribe()'d to that event's
    type gets called with it.

    We deliberately don't reach for Kafka/Redis here — a single Python
    process handling a simulated event stream doesn't need a distributed
    message broker yet. If we ever run multiple processes, this class is
    the one place we'd swap out.
    """

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable[[Event], None]]] = defaultdict(
            list
        )

    def subscribe(
        self, event_type: EventType, handler: Callable[[Event], None]
    ) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, db: Session, event: Event) -> None:
        # Persist first so the audit trail exists even if a subscriber
        # raises an exception while handling it.
        record = EventLog(
            event_type=event.event_type.value,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            payload=event.payload,
            created_at=event.created_at,
        )
        db.add(record)
        db.commit()

        for handler in self._subscribers[event.event_type]:
            handler(event)


# Single shared instance — producers and consumers both import this same
# object so they're all talking to the same bus.
event_bus = EventBus()
