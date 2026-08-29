from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.enums import RecoveryStrategy
from app.models.models import (
    AgentDecision,
    Customer,
    PolicyDecision,
    RecoveryAttempt,
    StrategyDecision,
)
from app.policies.constants import (
    HIGH_VALUE_TRANSACTION_THRESHOLD,
    MAX_AUTOMATED_RECOVERY_AMOUNT,
    MAX_DISCOUNT,
    MAX_INTERVENTIONS_PER_CUSTOMER_PER_DAY,
    MAX_RETRIES,
)
from app.strategy.definitions import STRATEGY_DEFINITIONS

ALLOW = "allow"
DENY = "deny"
ESCALATE = "escalate"

# Precedence when checks disagree: a single DENY always wins, then
# ESCALATE, then ALLOW. The system errs toward caution — it never lets a
# risky case slip through just because most other checks happened to pass.
_VERDICT_RANK = {ALLOW: 0, ESCALATE: 1, DENY: 2}

# Strategies that consume a retry attempt against MAX_RETRIES.
RETRY_STRATEGIES = {
    RecoveryStrategy.RETRY,
    RecoveryStrategy.DELAYED_RETRY,
    RecoveryStrategy.ALTERNATE_PAYMENT,
}

# Strategies that involve directly contacting the customer, and therefore
# must respect an opt-out.
CUSTOMER_FACING_STRATEGIES = {
    RecoveryStrategy.INCENTIVE,
    RecoveryStrategy.CUSTOMER_REMINDER,
}


@dataclass
class CheckOutcome:
    name: str
    verdict: str
    reason: str


@dataclass
class PolicyResult:
    verdict: str
    checks: list[CheckOutcome] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [c.reason for c in self.checks if c.verdict != ALLOW]


def _check_valid_action(strategy) -> CheckOutcome:
    if strategy not in STRATEGY_DEFINITIONS:
        return CheckOutcome(
            "valid_action", DENY, f"'{strategy}' is not a recognized recovery action."
        )
    return CheckOutcome("valid_action", ALLOW, "Action is recognized.")


def _check_customer_opt_out(
    customer: Customer, strategy: RecoveryStrategy
) -> CheckOutcome:
    if customer.opted_out and strategy in CUSTOMER_FACING_STRATEGIES:
        return CheckOutcome(
            "customer_opt_out",
            DENY,
            f"Customer has opted out of recovery communications; "
            f"{strategy.value} would contact them directly.",
        )
    return CheckOutcome("customer_opt_out", ALLOW, "No opt-out conflict.")


def _check_retry_limit(
    db: Session, transaction_id: int, strategy: RecoveryStrategy
) -> CheckOutcome:
    if strategy not in RETRY_STRATEGIES:
        return CheckOutcome(
            "retry_limit", ALLOW, "Strategy does not consume a retry attempt."
        )

    retry_count = (
        db.query(RecoveryAttempt)
        .filter(RecoveryAttempt.transaction_id == transaction_id)
        .count()
    )
    if retry_count >= MAX_RETRIES:
        return CheckOutcome(
            "retry_limit",
            DENY,
            f"Transaction has already had {retry_count} retry attempts (limit {MAX_RETRIES}).",
        )
    return CheckOutcome(
        "retry_limit", ALLOW, f"{retry_count}/{MAX_RETRIES} retries used."
    )


def _check_discount_limit(strategy: RecoveryStrategy) -> CheckOutcome:
    if strategy != RecoveryStrategy.INCENTIVE:
        return CheckOutcome(
            "discount_limit", ALLOW, "Strategy does not offer a discount."
        )

    discount = 1 - STRATEGY_DEFINITIONS[strategy].amount_multiplier
    if discount > MAX_DISCOUNT:
        return CheckOutcome(
            "discount_limit",
            DENY,
            f"Incentive discount {discount:.0%} exceeds policy limit of {MAX_DISCOUNT:.0%}.",
        )
    return CheckOutcome(
        "discount_limit", ALLOW, f"Discount {discount:.0%} within limit."
    )


def _check_intervention_frequency(db: Session, customer_id: int) -> CheckOutcome:
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    strategy_count = (
        db.query(StrategyDecision)
        .filter(
            StrategyDecision.customer_id == customer_id,
            StrategyDecision.created_at >= start_of_day,
        )
        .count()
    )
    agent_count = (
        db.query(AgentDecision)
        .filter(
            AgentDecision.customer_id == customer_id,
            AgentDecision.created_at >= start_of_day,
        )
        .count()
    )
    total = strategy_count + agent_count

    if total >= MAX_INTERVENTIONS_PER_CUSTOMER_PER_DAY:
        return CheckOutcome(
            "intervention_frequency",
            DENY,
            f"Customer has already had {total} recovery interventions today "
            f"(limit {MAX_INTERVENTIONS_PER_CUSTOMER_PER_DAY}).",
        )
    return CheckOutcome(
        "intervention_frequency",
        ALLOW,
        f"{total}/{MAX_INTERVENTIONS_PER_CUSTOMER_PER_DAY} interventions today.",
    )


def _check_high_value(amount: float) -> CheckOutcome:
    if amount > HIGH_VALUE_TRANSACTION_THRESHOLD:
        return CheckOutcome(
            "high_value",
            ESCALATE,
            f"Amount \u20b9{amount:,.2f} exceeds high-value threshold "
            f"\u20b9{HIGH_VALUE_TRANSACTION_THRESHOLD:,.2f}; requires human approval.",
        )
    return CheckOutcome("high_value", ALLOW, "Below high-value threshold.")


def _check_automated_amount_limit(
    amount: float, strategy: RecoveryStrategy
) -> CheckOutcome:
    if (
        strategy == RecoveryStrategy.INCENTIVE
        and amount > MAX_AUTOMATED_RECOVERY_AMOUNT
    ):
        return CheckOutcome(
            "automated_amount_limit",
            ESCALATE,
            f"Automated incentive on \u20b9{amount:,.2f} exceeds the automated limit "
            f"\u20b9{MAX_AUTOMATED_RECOVERY_AMOUNT:,.2f}.",
        )
    return CheckOutcome(
        "automated_amount_limit", ALLOW, "Within automated amount limit."
    )


def _check_agent_requested_approval(requires_approval: bool) -> CheckOutcome:
    if requires_approval:
        return CheckOutcome(
            "agent_requested_approval",
            ESCALATE,
            "The proposing agent flagged this decision as needing human approval.",
        )
    return CheckOutcome(
        "agent_requested_approval", ALLOW, "No approval flagged by proposer."
    )


def evaluate_policy(
    db: Session,
    customer_id: int,
    transaction_id: int,
    strategy: RecoveryStrategy,
    amount: float,
    requires_approval: bool = False,
) -> PolicyResult:
    """
    Runs every guardrail check and combines them into one verdict. A single
    DENY always outranks an ESCALATE, which always outranks an ALLOW.

    Neither the strategy engine (Phase 6) nor the LLM agent (Phase 7) has
    any way to skip this function — every proposal must pass through it
    before Phase 9 is allowed to execute anything.
    """
    checks = [_check_valid_action(strategy)]

    if checks[-1].verdict == DENY:
        # No point checking anything else against an action that isn't
        # even recognized.
        return PolicyResult(verdict=DENY, checks=checks)

    if strategy == RecoveryStrategy.STOP:
        # Doing nothing needs no authorization — this also means a
        # high-value transaction where the deterministic engine or agent
        # already decided not to act doesn't get flagged for human review
        # just because of its amount. Only actions need approval.
        checks.append(
            CheckOutcome(
                "stop_is_always_allowed", ALLOW, "No action is being taken; nothing to authorize."
            )
        )
        return PolicyResult(verdict=ALLOW, checks=checks)

    customer = db.get(Customer, customer_id)

    checks.append(_check_customer_opt_out(customer, strategy))
    checks.append(_check_retry_limit(db, transaction_id, strategy))
    checks.append(_check_discount_limit(strategy))
    checks.append(_check_intervention_frequency(db, customer_id))
    checks.append(_check_high_value(amount))
    checks.append(_check_automated_amount_limit(amount, strategy))
    checks.append(_check_agent_requested_approval(requires_approval))

    final_verdict = max((c.verdict for c in checks), key=lambda v: _VERDICT_RANK[v])
    return PolicyResult(verdict=final_verdict, checks=checks)


def evaluate_and_record_policy(
    db: Session,
    customer_id: int,
    transaction_id: int,
    strategy: RecoveryStrategy,
    amount: float,
    requires_approval: bool = False,
) -> PolicyDecision:
    result = evaluate_policy(
        db, customer_id, transaction_id, strategy, amount, requires_approval
    )

    record = PolicyDecision(
        transaction_id=transaction_id,
        customer_id=customer_id,
        strategy=(
            strategy if strategy in STRATEGY_DEFINITIONS else RecoveryStrategy.STOP
        ),
        amount=amount,
        verdict=result.verdict,
        reasons=result.reasons,
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    return record
