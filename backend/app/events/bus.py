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

    We deliberately don't reach for Kafka/Redis here â€” a single Python
    process handling a simulated event stream doesn't need a distributed
    message broker yet. If we ever run multiple processes, this class is
    the one place we'd swap out.
    """

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable[[Session, Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Callable[[Session, Event], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, db: Session, event: Event) -> None:
        # Flush (not commit) so the event log entry gets an ID and is
        # visible to subsequent queries in this same session, without
        # forcing a disk sync on every single event. Committing is now
        # the caller's responsibility, done periodically for throughput
        # (see app/simulator/generator.py) — this is the batching change
        # from Phase 13. Trade-off, stated plainly: if the process
        # crashes mid-batch, that batch's work is lost.
        record = EventLog(
            event_type=event.event_type.value,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            payload=event.payload,
            created_at=event.created_at,
        )
        db.add(record)
        db.flush()

        for handler in self._subscribers[event.event_type]:
            handler(db, event)

# Single shared instance â€” producers and consumers both import this same
# object so they're all talking to the same bus.
event_bus = EventBus()

