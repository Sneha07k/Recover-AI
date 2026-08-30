import time

from sqlalchemy.orm import Session

from app.config import settings
from app.models.enums import RecoveryStrategy
from app.models.models import Customer, RazorpayPaymentLink, Transaction
from app.policies.engine import CUSTOMER_FACING_STRATEGIES
from app.strategy.definitions import STRATEGY_DEFINITIONS

# Confirmed against https://razorpay.com/docs/api/payments/payment-links/create-standard/
# (fetched while building this phase, not from training data — API details
# like the smallest-currency-unit requirement and the test-mode link cap
# change over time and must not be guessed).
PAYMENT_LINKS_ENDPOINT_NOTE = "POST https://api.razorpay.com/v1/payment_links/"
TEST_MODE_LINK_LIMIT = 30  # per business, confirmed current as of this build


def _build_client():
    import razorpay

    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


def create_recovery_payment_link(
    db: Session,
    transaction: Transaction,
    customer: Customer,
    strategy: RecoveryStrategy,
    client=None,
) -> RazorpayPaymentLink:
    """
    Creates a REAL Razorpay test-mode Payment Link for a customer-facing
    recovery strategy. Only INCENTIVE and CUSTOMER_REMINDER map to this —
    RETRY/ALTERNATE_PAYMENT/ESCALATION would require charging a tokenized
    payment method, a materially different (and riskier) integration this
    phase deliberately does not attempt.

    IMPORTANT: this does not decide or record whether recovery succeeded.
    RecoverAI's simulator (Phase 9) remains the sole source of truth for
    that — this function only proves a real, working connection exists.

    notify and reminder_enable are explicitly False: our simulated
    customers have fake, Faker-generated contact details, and there is no
    reason to exercise a real notification pathway with them, even in
    test mode.
    """
    if strategy not in CUSTOMER_FACING_STRATEGIES:
        raise ValueError(
            f"{strategy.value} does not map to a payment link — only "
            f"{[s.value for s in CUSTOMER_FACING_STRATEGIES]} do."
        )

    if client is None:
        client = _build_client()

    # Razorpay requires amounts in the smallest currency unit (paise for
    # INR), not rupees. Our simulator stores rupees as a float.
    effective_amount = (
        transaction.amount * STRATEGY_DEFINITIONS[strategy].amount_multiplier
    )
    amount_paise = int(round(effective_amount * 100))

    reference_id = f"recoverai-{transaction.id}-{int(time.time())}"

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "description": f"RecoverAI {strategy.value} for transaction #{transaction.id}",
        "reference_id": reference_id,
        "customer": {
            "name": customer.name,
            "email": customer.email,
        },
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "callback_method": "get",
    }

    response = client.payment_link.create(payload)

    record = RazorpayPaymentLink(
        transaction_id=transaction.id,
        strategy=strategy,
        amount_paise=amount_paise,
        razorpay_payment_link_id=response["id"],
        short_url=response["short_url"],
        status=response["status"],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
