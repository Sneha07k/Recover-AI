import logging

from app.events.bus import event_bus
from app.events.enums import EventType
from app.events.schemas import Event
from app.execution.controller import run_closed_loop_on_payment_failed
from app.risk.engine import assess_risk_on_payment_failed

logger = logging.getLogger("recoverai.events")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def log_payment_failed(db, event: Event) -> None:
    txn_id = event.entity_id
    amount = event.payload.get("amount")
    method = event.payload.get("payment_method")
    logger.info(f"[event] PAYMENT_FAILED txn={txn_id} amount={amount} method={method}")


def _run_closed_loop_without_agent(db, event: Event) -> None:
    """
    Wraps the closed loop with use_agent_for_ambiguous=False for the
    default automatic pipeline — real LLM calls stay opt-in only (see
    scripts/run_agent_demo.py), never fired automatically across a bulk
    simulation of thousands of failures.
    """
    run_closed_loop_on_payment_failed(db, event, use_agent_for_ambiguous=False)


def register_default_consumers() -> None:
    event_bus.subscribe(EventType.PAYMENT_FAILED, log_payment_failed)
    event_bus.subscribe(EventType.PAYMENT_FAILED, assess_risk_on_payment_failed)
    event_bus.subscribe(EventType.PAYMENT_FAILED, _run_closed_loop_without_agent)
