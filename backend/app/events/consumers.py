import logging

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.risk.engine import assess_risk_on_payment_failed
from app.strategy.engine import recommend_strategy_on_payment_failed

logger = logging.getLogger("recoverai.events")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def log_payment_failed(db, event: Event) -> None:
    """
    Example consumer: just observes PAYMENT_FAILED events and logs them.
    Kept alongside the real Risk Engine consumer to show that multiple,
    independent consumers can react to the exact same event.
    """
    txn_id = event.entity_id
    amount = event.payload.get("amount")
    method = event.payload.get("payment_method")
    logger.info(f"[event] PAYMENT_FAILED txn={txn_id} amount={amount} method={method}")


def register_default_consumers() -> None:
    event_bus.subscribe(EventType.PAYMENT_FAILED, log_payment_failed)
    event_bus.subscribe(EventType.PAYMENT_FAILED, assess_risk_on_payment_failed)
    event_bus.subscribe(EventType.PAYMENT_FAILED, recommend_strategy_on_payment_failed)

