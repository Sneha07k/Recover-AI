import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Numeric features only — payment_method is categorical and gets one-hot
# encoded separately. Note failure_type is NOT here: it's the simulator's
# hidden ground truth, never a legitimate feature.
FEATURE_COLUMNS_NUMERIC = [
    "amount",
    "customer_prior_transactions",
    "customer_fail_rate",
    "customer_recovery_rate",
    "method_fail_rate",
    "method_recovery_rate",
]


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """One-hot encode payment_method, keep numeric features as-is."""
    method_dummies = pd.get_dummies(df["payment_method"], prefix="method").astype(float)
    X = pd.concat([df[FEATURE_COLUMNS_NUMERIC], method_dummies], axis=1)
    y = df["recovered"]
    return X, y


def train_and_evaluate(df: pd.DataFrame, n_splits: int = 5):
    """
    With only a few hundred labeled examples, one train/test split gives a
    noisy performance estimate — try it twice with different random seeds
    and watch the numbers swing wildly. K-fold cross-validation fixes this:
    every example gets used as held-out test data exactly once (across
    n_splits folds), so we evaluate on far more predictions overall while
    still never letting a fold's own test rows influence its training.

    StandardScaler lives inside the Pipeline so it's refit separately on
    each fold's training portion — otherwise fitting it once on all the
    data first would leak each fold's test statistics into training.
    """
    X, y = prepare_features(df)

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    )

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    y_proba = cross_val_predict(pipeline, X, y, cv=cv, method="predict_proba")[:, 1]
    y_pred = (y_proba >= 0.5).astype(int)

    report = classification_report(y, y_pred, digits=3, zero_division=0)
    cm = confusion_matrix(y, y_pred)
    auc = roc_auc_score(y, y_proba)

    # Final model refit on ALL available data — this is the one we
    # actually save and use, distinct from the fold models used only for
    # evaluation above.
    final_pipeline = pipeline.fit(X, y)

    return final_pipeline, X.columns.tolist(), report, cm, auc
