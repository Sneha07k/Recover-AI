"""
Run with: python scripts/run_failure_demo.py

Phase 15 - Failure Demonstration.

The roadmap is explicit: the final demo MUST intentionally show failures,
not hide them. This script drives several transactions through repeated
or adverse conditions to show RecoverAI failing SAFELY - denying,
escalating, or simply not recovering - rather than doing something
unbounded or silently wrong.

Uses a dedicated, isolated database file so it never mixes with your main
simulation data.

A note on Scenario 1's random seed: our closed loop currently processes
each failure ONCE per event (no automatic re-attempt over time), so this
script deliberately drives one transaction through repeated attempts
itself, using the exact same production functions the live system uses.
Each retry attempt only has roughly a 20% chance of failing to recover by
chance alone given current probability tables, so a live run might
recover before ever hitting the limit. Rather than alter the underlying
probabilities to force a failure (which would be exactly the kind of
simulation manipulation the roadmap warns against), we fix a random seed
that we verified reliably produces the illustrative walkthrough. The
odds themselves are the real, unaltered odds - only the seed is chosen.

The actual scenario logic lives in app/demo/failure_scenarios.py, shared
with the web API's /actions/failure-demo endpoint.
"""

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
