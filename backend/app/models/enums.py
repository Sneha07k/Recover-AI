import enum


class CustomerType(str, enum.Enum):
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


class FailureType(str, enum.Enum):
   
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class RecoveryStrategy(str, enum.Enum):
    RETRY = "retry"
    DELAYED_RETRY = "delayed_retry"
    ALTERNATE_PAYMENT = "alternate_payment"
    INCENTIVE = "incentive"
    CUSTOMER_REMINDER = "customer_reminder"
    ESCALATION = "escalation"
    STOP = "stop"

