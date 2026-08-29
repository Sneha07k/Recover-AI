"""
Run with: python scripts/train_recovery_model.py
Assumes you've already run scripts/run_simulation.py to populate the database.
"""
import os

import joblib

from app.database import SessionLocal, init_db
from app.ml.features import build_recovery_dataset
from app.ml.train import train_and_evaluate


def main():
    init_db()
    db = SessionLocal()
    try:
        df = build_recovery_dataset(db)
        print(f"Dataset size: {len(df)} failed transactions with recovery attempts")
        if len(df) == 0:
            print("No data found. Run scripts/run_simulation.py first.")
            return

        print(f"Recovered: {df['recovered'].sum()} ({df['recovered'].mean():.1%})")

        if len(df) < 30:
            print("Not enough data to train reliably â€” re-run the simulator with more transactions.")
            return

        model, feature_names, report, cm, auc = train_and_evaluate(df)

        print("\nClassification report (5-fold cross-validated, out-of-fold predictions):")
        print(report)
        print("Confusion matrix (rows=actual, cols=predicted; [not_recovered, recovered]):")
        print(cm)
        print(f"ROC-AUC: {auc:.3f}")

        os.makedirs("../data/models", exist_ok=True)
        joblib.dump(
            {"model": model, "feature_names": feature_names},
            "../data/models/recovery_model.pkl",
        )
        print("\nModel saved to data/models/recovery_model.pkl")
    finally:
        db.close()


if __name__ == "__main__":
    main()

