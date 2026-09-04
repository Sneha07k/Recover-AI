from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.agents.ambiguity import is_ambiguous
from app.agents.engine import make_agent_decision
from app.experiments.simulate_outcome import simulate_recovery_outcome
from app.models.enums import RecoveryStrategy
from app.models.models import Customer, ExperimentResult, Transaction
from app.policies.engine import ALLOW, evaluate_policy
from app.strategy.definitions import STRATEGY_DEFINITIONS
from app.strategy.engine import recommend_strategy


CONDITIONS = ["no_intervention", "immediate_retry", "rule_based", "ml_based"]


@dataclass
class ConditionSummary:
    condition: str
    transactions: int
    interventions: int
    successful: int
    revenue_recovered: float
    total_cost: float
    false_interventions: int
    recovery_rate: float | None


def _decide_strategy(
    db: Session, condition: str, txn: Transaction, customer: Customer, agent_client=None
) -> tuple[RecoveryStrategy, bool]:
    if condition == "no_intervention":
        return RecoveryStrategy.STOP, False
    if condition == "immediate_retry":
        return RecoveryStrategy.RETRY, False
    if condition == "rule_based":
        rec = recommend_strategy(
            db,
            txn.id,
            customer.id,
            txn.payment_method,
            txn.amount,
            force_rule_based=True,
        )
        return rec.strategy, False
    if condition == "ml_based":
        rec = recommend_strategy(
            db,
            txn.id,
            customer.id,
            txn.payment_method,
            txn.amount,
            force_rule_based=False,
        )
        return rec.strategy, False
    if condition == "agent":
        rec = recommend_strategy(
            db,
            txn.id,
            customer.id,
            txn.payment_method,
            txn.amount,
            force_rule_based=False,
        )
        strategy = rec.strategy
        requires_approval = False
        if is_ambiguous(rec, txn.amount):
            decision = make_agent_decision(
                db,
                txn.id,
                customer.id,
                txn.payment_method,
                txn.amount,
                client=agent_client,
            )
            strategy = decision.action
            requires_approval = decision.requires_approval
        return strategy, requires_approval
    raise ValueError(f"Unknown condition: {condition}")


def run_experiment(
    db: Session,
    failed_transactions: list[Transaction],
    customers_by_id: dict[int, Customer],
    conditions: list[str] = CONDITIONS,
    seed: int = 42,
    agent_client=None,
) -> dict[str, ConditionSummary]:
    results: dict[str, ConditionSummary] = {}

    for condition in conditions:
        interventions = 0
        successful = 0
        revenue_recovered = 0.0
        total_cost = 0.0
        false_interventions = 0

        for txn in failed_transactions:
            customer = customers_by_id[txn.customer_id]

            strategy, requires_approval = _decide_strategy(
                db, condition, txn, customer, agent_client
            )

            if strategy == RecoveryStrategy.STOP:
                continue

            policy_result = evaluate_policy(
                db, customer.id, txn.id, strategy, txn.amount, requires_approval
            )
            if policy_result.verdict != ALLOW:
                continue

            rng = np.random.default_rng(seed=seed * 1_000_003 + txn.id)
            succeeded, amount_recovered = simulate_recovery_outcome(
                rng, txn.payment_method, customer.customer_type, strategy, txn.amount
            )

            interventions += 1
            cost = STRATEGY_DEFINITIONS[strategy].cost
            total_cost += cost
            if succeeded:
                successful += 1
                revenue_recovered += amount_recovered
            else:
                false_interventions += 1

            db.add(
                ExperimentResult(
                    condition=condition,
                    transaction_id=txn.id,
                    strategy=strategy,
                    policy_verdict=policy_result.verdict,
                    executed=True,
                    succeeded=succeeded,
                    amount_recovered=amount_recovered,
                    cost=cost,
                )
            )

        db.commit()

        recovery_rate = successful / interventions if interventions else None
        results[condition] = ConditionSummary(
            condition=condition,
            transactions=len(failed_transactions),
            interventions=interventions,
            successful=successful,
            revenue_recovered=revenue_recovered,
            total_cost=total_cost,
            false_interventions=false_interventions,
            recovery_rate=recovery_rate,
        )

    return results
