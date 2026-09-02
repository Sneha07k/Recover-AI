"""
Run with: python scripts/run_experiment.py [num_customers] [num_transactions] [seed]
"""

import sys

from app.experiments.runner import run_experiment_end_to_end


def main():
    num_customers = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    num_transactions = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42

    data = run_experiment_end_to_end(num_customers, num_transactions, seed)

    print(
        f"Population: {data['num_transactions']} transactions, "
        f"{data['total_failed']} failed, seed={data['seed']}"
    )
    print()

    header = (
        f"{'Condition':<18}{'Interventions':>14}{'Recovered':>12}"
        f"{'Recovery Rate':>15}{'Revenue Recovered':>20}{'Cost':>12}"
    )
    print(header)
    print("-" * len(header))
    for c in data["conditions"]:
        rate_str = (
            f"{c['recovery_rate']:.1%}" if c["recovery_rate"] is not None else "n/a"
        )
        revenue_str = f"\u20b9{c['revenue_recovered']:,.2f}"
        cost_str = f"\u20b9{c['total_cost']:,.2f}"
        print(
            f"{c['condition']:<18}{c['interventions']:>14}{c['successful']:>12}"
            f"{rate_str:>15}{revenue_str:>20}{cost_str:>12}"
        )

    print()
    print("False interventions (attempted but did not recover):")
    for c in data["conditions"]:
        print(f"  {c['condition']:<18} {c['false_interventions']}")

    print()
    print("NOTE: retry-limit and per-customer intervention-frequency guardrails")
    print("are inactive in this comparison — each condition evaluates every")
    print("failure as one independent hypothetical intervention rather than a")
    print("persisted multi-attempt history. See app/experiments/harness.py.")


if __name__ == "__main__":
    main()
