import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from app.models.enums import PaymentMethod
from app.risk.scoring import RECOVERY_PROBABILITY_BY_METHOD


FEATURE_COLUMNS_NUMERIC = [
    "amount",
    "customer_prior_transactions",
    "customer_fail_rate",
    "customer_recovery_rate",
    "method_fail_rate",
    "method_recovery_rate",
]


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    method_dummies = pd.get_dummies(df["payment_method"], prefix="method").astype(float)
    X = pd.concat([df[FEATURE_COLUMNS_NUMERIC], method_dummies], axis=1)
    y = df["recovered"]
    return X, y


def train_and_evaluate(df: pd.DataFrame, n_splits: int = 5):
    
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

    final_pipeline = pipeline.fit(X, y)

    return final_pipeline, X.columns.tolist(), report, cm, auc


def compute_rule_based_baseline_auc(df: pd.DataFrame) -> float:
    scores = df["payment_method"].map(
        lambda m: RECOVERY_PROBABILITY_BY_METHOD[PaymentMethod(m)]
    )
    return float(roc_auc_score(df["recovered"], scores))
