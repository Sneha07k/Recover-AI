from app.models.enums import CustomerType, FailureType, PaymentMethod

# ---------------------------------------------------------------------
# Everything in this file represents "ground truth" the simulator uses
# to decide what ACTUALLY happens. Nothing here may ever be used as a
# feature by the risk engine, ML model, strategy engine, or agent —
# those components only ever see OBSERVED history. This file is reality;
# everything else is prediction.
# ---------------------------------------------------------------------

BASE_FAILURE_PROBABILITY = {
    PaymentMethod.UPI: 0.05,
    PaymentMethod.CREDIT_CARD: 0.12,
    PaymentMethod.DEBIT_CARD: 0.10,
    PaymentMethod.NET_BANKING: 0.08,
    PaymentMethod.WALLET: 0.04,
}

CUSTOMER_FAILURE_MULTIPLIER = {
    CustomerType.RELIABLE: 0.5,
    CustomerType.OCCASIONAL_PAYER: 1.0,
    CustomerType.PRICE_SENSITIVE: 1.1,
    CustomerType.HIGH_VALUE: 0.7,
    CustomerType.FREQUENTLY_FAILS: 2.5,
    CustomerType.SUBSCRIPTION_HEAVY: 1.0,
}

CUSTOMER_TYPE_WEIGHTS = {
    CustomerType.RELIABLE: 0.30,
    CustomerType.OCCASIONAL_PAYER: 0.25,
    CustomerType.PRICE_SENSITIVE: 0.15,
    CustomerType.HIGH_VALUE: 0.10,
    CustomerType.FREQUENTLY_FAILS: 0.10,
    CustomerType.SUBSCRIPTION_HEAVY: 0.10,
}

AMOUNT_MEAN_LOG = {
    CustomerType.RELIABLE: 7.0,
    CustomerType.OCCASIONAL_PAYER: 6.5,
    CustomerType.PRICE_SENSITIVE: 6.0,
    CustomerType.HIGH_VALUE: 9.0,
    CustomerType.FREQUENTLY_FAILS: 6.8,
    CustomerType.SUBSCRIPTION_HEAVY: 7.2,
}

# Probability that a given failure is TRANSIENT rather than PERMANENT —
# used by the Action Executor (Phase 9) to determine whether a recovery
# attempt actually succeeds, once a strategy has been chosen and allowed.
TRANSIENT_PROBABILITY_BY_METHOD = {
    PaymentMethod.UPI: 0.85,
    PaymentMethod.WALLET: 0.85,
    PaymentMethod.NET_BANKING: 0.70,
    PaymentMethod.DEBIT_CARD: 0.60,
    PaymentMethod.CREDIT_CARD: 0.50,
}

TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE = {
    CustomerType.RELIABLE: 0.05,
    CustomerType.OCCASIONAL_PAYER: 0.0,
    CustomerType.PRICE_SENSITIVE: 0.0,
    CustomerType.HIGH_VALUE: 0.05,
    CustomerType.FREQUENTLY_FAILS: -0.30,
    CustomerType.SUBSCRIPTION_HEAVY: 0.0,
}

# Given the TRUE failure type and no intervention, probability that a
# plain retry would succeed. The Action Executor scales this by the
# CHOSEN strategy's probability_multiplier (Phase 6), which is what makes
# the simulation self-consistent with the strategy engine's assumptions.
RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE = {
    FailureType.TRANSIENT: 0.80,
    FailureType.PERMANENT: 0.05,
}

# Fraction of customers who have opted out of recovery communications.
OPT_OUT_PROBABILITY = 0.05
