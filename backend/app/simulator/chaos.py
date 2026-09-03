"""
Chaos Mode / Provider Degradation.

Temporarily overrides the ground-truth failure/transient probabilities
for ONE payment method, simulating a real provider outage. This is the
only module that knows chaos mode is active — the risk engine, ML model,
strategy engine, and policy engine never see this flag. Whatever
"detection" or "adaptation" shows up in the demo is entirely emergent:
computed from real, observed transaction/recovery-attempt history, the
exact same way it would be for a genuine provider outage in production.

Deliberately NOT time-boxed with a background timer — the chaos demo
endpoint (app/api/actions.py) activates this, generates a batch of real
transactions through the full closed loop, then deactivates it, all
synchronously within one request. This avoids any timing/concurrency
complexity while still being a completely honest before/during comparison.
"""
from app.models.enums import PaymentMethod

_active_method: PaymentMethod | None = None
_active_base_failure_probability: float = 0.0
_active_transient_probability: float = 0.0


def set_active(
    payment_method: PaymentMethod,
    base_failure_probability: float,
    transient_probability: float,
) -> None:
    global _active_method, _active_base_failure_probability, _active_transient_probability
    _active_method = payment_method
    _active_base_failure_probability = base_failure_probability
    _active_transient_probability = transient_probability


def clear() -> None:
    global _active_method
    _active_method = None


def is_active() -> bool:
    return _active_method is not None


def get_active_method() -> PaymentMethod | None:
    return _active_method


def get_base_failure_probability_override(payment_method: PaymentMethod) -> float | None:
    if _active_method is not None and _active_method == payment_method:
        return _active_base_failure_probability
    return None


def get_transient_probability_override(payment_method: PaymentMethod) -> float | None:
    if _active_method is not None and _active_method == payment_method:
        return _active_transient_probability
    return None