from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.events.enums import EventType


class Event(BaseModel):
    event_type: EventType
    entity_type: str
    entity_id: int
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

