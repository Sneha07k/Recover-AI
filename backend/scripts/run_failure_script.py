import numpy as np

from app.demo.failure_scenarios import ALL_SCENARIOS, DEMO_SEED, make_session


def banner(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main():
    np.random.seed(DEMO_SEED)
    db = make_session()
    try:
        for scenario_fn in ALL_SCENARIOS:
            title, lines = scenario_fn(db)
            banner(title)
            for line in lines:
                print(line)

        banner("SUMMARY")
        print("Every scenario above ended in some form of 'no recovery' - a denial,")
        print("an escalation, a policy block, or a genuine failed attempt. None of")
        print("them are hidden or silently discarded: every one is a real row in")
        print("risk_assessments, strategy_decisions, policy_decisions, or")
        print("recovery_attempts, visible through the Phase 10 audit trail API")
        print("and the Phase 11 dashboard.")
        print("\nThis is what 'fails gracefully' means for RecoverAI: bounded,")
        print("explainable, auditable failure - never silent, never unbounded.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
