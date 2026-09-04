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