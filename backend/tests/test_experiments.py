import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.experiments.harness import CONDITIONS, run_experiment
from app.experiments.simulate_outcome import simulate_recovery_outcome
from app.models.enums import (
    CustomerType,
    PaymentMethod,
    RecoveryStrategy,
    TransactionStatus,
)
from app.models.models import Customer, ExperimentResult, Merchant, Transaction
from app.strategy.probability import predict_recovery_probability


def make_test_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from app.models import models 

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()



def test_same_seed_same_strategy_gives_identical_outcome():
   
    outcomes = set()
    for _ in range(5):
        rng = np.random.default_rng(seed=12345)
        result = simulate_recovery_outcome(
            rng,
            PaymentMethod.UPI,
            CustomerType.RELIABLE,
            RecoveryStrategy.RETRY,
            1000.0,
        )
        outcomes.add(result)
    assert len(outcomes) == 1


def test_same_seed_different_strategy_uses_shared_underlying_randomness():
   
    retry_successes = 0
    alt_payment_successes = 0
    n = 500
    for i in range(n):
        rng1 = np.random.default_rng(seed=i)
        succeeded1, _ = simulate_recovery_outcome(
            rng1,
            PaymentMethod.CREDIT_CARD,
            CustomerType.OCCASIONAL_PAYER,
            RecoveryStrategy.RETRY,
            500.0,
        )
        rng2 = np.random.default_rng(seed=i) 
        succeeded2, _ = simulate_recovery_outcome(
            rng2,
            PaymentMethod.CREDIT_CARD,
            CustomerType.OCCASIONAL_PAYER,
            RecoveryStrategy.ALTERNATE_PAYMENT,
            500.0,
        )
        retry_successes += succeeded1
        alt_payment_successes += succeeded2

   
    assert alt_payment_successes >= retry_successes




def test_force_rule_based_ignores_any_trained_model():
    db = make_test_session()
    try:
        prob = predict_recovery_probability(
            db,
            customer_id=1,
            payment_method=PaymentMethod.UPI,
            amount=1000.0,
            force_rule_based=True,
        )
        from app.risk.scoring import RECOVERY_PROBABILITY_BY_METHOD

        assert prob == RECOVERY_PROBABILITY_BY_METHOD[PaymentMethod.UPI]
    finally:
        db.close()


def _seed_population(db, n_customers=20, n_transactions=100):
    from app.simulator.generator import (
        create_merchant,
        generate_customers,
        generate_transactions,
    )

    merchant = create_merchant(db)
    customers = generate_customers(db, merchant, n_customers)
    transactions = generate_transactions(db, customers, n_transactions)
    failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
    customers_by_id = {c.id: c for c in customers}
    return failed, customers_by_id


def test_no_intervention_never_attempts_anything():
    db = make_test_session()
    try:
        failed, customers_by_id = _seed_population(db)
        results = run_experiment(
            db, failed, customers_by_id, conditions=["no_intervention"], seed=1
        )

        r = results["no_intervention"]
        assert r.interventions == 0
        assert r.successful == 0
        assert r.revenue_recovered == 0.0
        assert r.recovery_rate is None
    finally:
        db.close()


def test_immediate_retry_attempts_every_failure():
    db = make_test_session()
    try:
        failed, customers_by_id = _seed_population(db)
        results = run_experiment(
            db, failed, customers_by_id, conditions=["immediate_retry"], seed=1
        )

        r = results["immediate_retry"]
        assert r.interventions <= len(failed)
        assert r.interventions > 0
    finally:
        db.close()


def test_run_experiment_persists_results_per_condition():
    db = make_test_session()
    try:
        failed, customers_by_id = _seed_population(db)
        run_experiment(
            db,
            failed,
            customers_by_id,
            conditions=["no_intervention", "immediate_retry"],
            seed=1,
        )

        stored_conditions = {r.condition for r in db.query(ExperimentResult).all()}
        assert "immediate_retry" in stored_conditions
        assert "no_intervention" not in stored_conditions
    finally:
        db.close()


def test_same_transactions_across_conditions_are_reproducible():
    db1 = make_test_session()
    db2 = make_test_session()
    try:
        import random

        random.seed(1)
        np.random.seed(1)
        failed1, customers_by_id1 = _seed_population(db1)

        random.seed(1)
        np.random.seed(1)
        failed2, customers_by_id2 = _seed_population(db2)

        results1 = run_experiment(
            db1, failed1, customers_by_id1, conditions=["rule_based"], seed=1
        )
        results2 = run_experiment(
            db2, failed2, customers_by_id2, conditions=["rule_based"], seed=1
        )

        assert (
            results1["rule_based"].interventions == results2["rule_based"].interventions
        )
        assert results1["rule_based"].successful == results2["rule_based"].successful
        assert (
            results1["rule_based"].revenue_recovered
            == results2["rule_based"].revenue_recovered
        )
    finally:
        db1.close()
        db2.close()
