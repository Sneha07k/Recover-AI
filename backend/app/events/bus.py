from collections import defaultdict
from typing import Callable

from sqlalchemy.orm import Session

from app.events.enums import EventType
from app.events.schemas import Event
from app.models.models import EventLog


class EventBus:
    def __init__(self):
        self._subscribers: dict[EventType, list[Callable[[Session, Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Callable[[Session, Event], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, db: Session, event: Event) -> None:
        
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


event_bus = EventBus()

