import logging

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event

logger = logging.getLogger("recoverai.events")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def log_payment_failed(event: Event) -> None:
    """
    Example consumer: just observes PAYMENT_FAILED events and logs them.
    This is a stand-in for what the Risk Engine (Phase 4) will do instead:
    subscribe to this same event type and actually score the risk.
    """
    txn_id = event.entity_id
    amount = event.payload.get("amount")
    method = event.payload.get("payment_method")
    logger.info(f"[event] PAYMENT_FAILED txn={txn_id} amount={amount} method={method}")


def register_default_consumers() -> None:
    event_bus.subscribe(EventType.PAYMENT_FAILED, log_payment_failed)
