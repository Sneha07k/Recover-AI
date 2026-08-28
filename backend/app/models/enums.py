import enum


class CustomerType(str, enum.Enum):
    """
    Persistent behavioral profile for a customer. This is what gives the
    simulator real signal — a FREQUENTLY_FAILS customer fails more often
    every time, not just by coincidence.
    """

    RELIABLE = "reliable"
    OCCASIONAL_PAYER = "occasional_payer"
    PRICE_SENSITIVE = "price_sensitive"
    HIGH_VALUE = "high_value"
    FREQUENTLY_FAILS = "frequently_fails"
    SUBSCRIPTION_HEAVY = "subscription_heavy"


class PaymentMethod(str, enum.Enum):
    UPI = "upi"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    NET_BANKING = "net_banking"
    WALLET = "wallet"


class TransactionStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
