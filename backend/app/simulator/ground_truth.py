from app.models.enums import CustomerType, FailureType, PaymentMethod



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


RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE = {
    FailureType.TRANSIENT: 0.80,
    FailureType.PERMANENT: 0.05,
}


OPT_OUT_PROBABILITY = 0.05
