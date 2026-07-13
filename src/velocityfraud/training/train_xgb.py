"""XGBoost fraud classifier — trained on engineered IEEE-CIS features.

This is the CHAMPION candidate. XGBoost typically beats Random Forest by 1-3
ROC-AUC points on tabular fraud detection due to its gradient-boosting +
regularization combination.

Pipeline:
    1. Load X_train / y_train / X_test / y_test from data/processed/
    2. Train XGBClassifier (scale_pos_weight tuned for 3.5% fraud rate)
    3. Predict probabilities on test set
    4. Log metrics + artifacts to MLflow (http://localhost:5000)
    5. Persist the trained model to models/xgboost_v1.pkl

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.training.train_xgb

Env vars (optional):
    MLFLOW_TRACKING_URI    (default: http://localhost:5000)
    XGB_N_ESTIMATORS       (default: 400)
    XGB_MAX_DEPTH          (default: 8)
    XGB_LEARNING_RATE      (default: 0.05)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")  # Headless backend — avoids Windows Tk threading crash on script exit
import matplotlib.pyplot as plt
import mlflow
import mlflow.xgboost
import numpy as np
import pandas as pd
import seaborn as sns
import xgboost as xgb
from loguru import logger
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODELS_DIR = PROJECT_ROOT / "models"
ARTIFACTS_DIR = PROJECT_ROOT / "data" / "processed" / "xgb_artifacts"

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = "fraud-detection"
RUN_NAME = "xgboost_v1"

N_ESTIMATORS = int(os.getenv("XGB_N_ESTIMATORS", "400"))
MAX_DEPTH = int(os.getenv("XGB_MAX_DEPTH", "8"))
LEARNING_RATE = float(os.getenv("XGB_LEARNING_RATE", "0.05"))
RANDOM_STATE = 42


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_splits() -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Load train/test splits from Parquet (written by features.py)."""
    if not (PROCESSED_DIR / "X_train.parquet").exists():
        raise FileNotFoundError(
            f"Train data not found in {PROCESSED_DIR}. "
            "Run: uv run python -m velocityfraud.training.features"
        )
    X_train = pd.read_parquet(PROCESSED_DIR / "X_train.parquet")
    X_test = pd.read_parquet(PROCESSED_DIR / "X_test.parquet")
    y_train = pd.read_parquet(PROCESSED_DIR / "y_train.parquet").iloc[:, 0]
    y_test = pd.read_parquet(PROCESSED_DIR / "y_test.parquet").iloc[:, 0]
    logger.info("Loaded train={} test={} features={}",
                len(X_train), len(X_test), X_train.shape[1])
    return X_train, y_train, X_test, y_test


# ---------------------------------------------------------------------------
# Plot helpers (saved as artifacts to MLflow)
# ---------------------------------------------------------------------------
def plot_confusion_matrix(y_true, y_pred, out_path: Path) -> None:
    cm = confusion_matrix(y_true, y_pred)
    fig, ax = plt.subplots(figsize=(6, 5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Greens", ax=ax,
                xticklabels=["Legit", "Fraud"],
                yticklabels=["Legit", "Fraud"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("XGBoost — Confusion Matrix (threshold=0.5)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


def plot_roc_curve(y_true, y_score, auc: float, out_path: Path) -> None:
    fpr, tpr, _ = roc_curve(y_true, y_score)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(fpr, tpr, lw=2, color="darkgreen", label=f"AUC = {auc:.4f}")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="Random")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("XGBoost — ROC Curve")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


def plot_feature_importance(model, feature_names: list[str], out_path: Path,
                            top_n: int = 20) -> None:
    importances = pd.Series(model.feature_importances_, index=feature_names)
    top = importances.sort_values(ascending=True).tail(top_n)
    fig, ax = plt.subplots(figsize=(8, 7))
    top.plot.barh(ax=ax, color="darkgreen")
    ax.set_title(f"XGBoost — Top {top_n} Feature Importances")
    ax.set_xlabel("Importance (Gain)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main training pipeline
# ---------------------------------------------------------------------------
def main() -> int:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("MLflow tracking URI: {}", MLFLOW_TRACKING_URI)
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    X_train, y_train, X_test, y_test = load_splits()

    # scale_pos_weight = ratio of negatives to positives (handles class imbalance
    # in XGBoost, equivalent to class_weight='balanced' in sklearn).
    neg = (y_train == 0).sum()
    pos = (y_train == 1).sum()
    scale_pos_weight = neg / pos
    logger.info("scale_pos_weight = neg/pos = {}/{} = {:.2f}",
                neg, pos, scale_pos_weight)

    with mlflow.start_run(run_name=RUN_NAME) as run:
        run_id = run.info.run_id
        logger.info("MLflow run started: {} (id={})", RUN_NAME, run_id)

        params = {
            "model_type": "XGBClassifier",
            "n_estimators": N_ESTIMATORS,
            "max_depth": MAX_DEPTH,
            "learning_rate": LEARNING_RATE,
            "scale_pos_weight": round(scale_pos_weight, 2),
            "random_state": RANDOM_STATE,
            "objective": "binary:logistic",
            "eval_metric": "auc",
            "n_features": X_train.shape[1],
            "n_train": len(X_train),
            "n_test": len(X_test),
        }
        mlflow.log_params(params)

        logger.info("Training XGBoost (n_est={}, max_depth={}, lr={})...",
                    N_ESTIMATORS, MAX_DEPTH, LEARNING_RATE)
        t0 = time.monotonic()
        model = xgb.XGBClassifier(
            n_estimators=N_ESTIMATORS,
            max_depth=MAX_DEPTH,
            learning_rate=LEARNING_RATE,
            scale_pos_weight=scale_pos_weight,
            objective="binary:logistic",
            eval_metric="auc",
            early_stopping_rounds=20,  # halt if eval AUC doesn't improve for 20 rounds
            random_state=RANDOM_STATE,
            n_jobs=-1,
            tree_method="hist",  # fast histogram-based splitting
            verbosity=0,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )
        train_time = time.monotonic() - t0
        logger.success("Training complete in {:.1f}s", train_time)
        mlflow.log_metric("train_time_seconds", train_time)
        try:
            mlflow.log_metric("best_iteration", model.best_iteration)
            logger.info("Best iteration: {} / {}", model.best_iteration, N_ESTIMATORS)
        except Exception:
            mlflow.log_metric("best_iteration", N_ESTIMATORS)

        logger.info("Predicting on test set...")
        y_pred = model.predict(X_test)
        y_score = model.predict_proba(X_test)[:, 1]

        metrics = {
            "roc_auc": roc_auc_score(y_test, y_score),
            "pr_auc": average_precision_score(y_test, y_score),
            "precision": precision_score(y_test, y_pred, zero_division=0),
            "recall": recall_score(y_test, y_pred, zero_division=0),
            "f1": f1_score(y_test, y_pred, zero_division=0),
        }
        cm = confusion_matrix(y_test, y_pred)
        tn, fp, fn, tp = cm.ravel()
        metrics.update({
            "true_negatives": int(tn),
            "false_positives": int(fp),
            "false_negatives": int(fn),
            "true_positives": int(tp),
        })
        mlflow.log_metrics(metrics)

        logger.info("=" * 60)
        logger.info("XGBOOST — TEST SET RESULTS")
        logger.info("=" * 60)
        logger.info("  ROC-AUC      : {:.4f}", metrics["roc_auc"])
        logger.info("  PR-AUC       : {:.4f}", metrics["pr_auc"])
        logger.info("  Precision    : {:.4f}", metrics["precision"])
        logger.info("  Recall       : {:.4f}", metrics["recall"])
        logger.info("  F1           : {:.4f}", metrics["f1"])
        logger.info("  Confusion    : TN={} FP={} FN={} TP={}", tn, fp, fn, tp)
        logger.info("=" * 60)

        logger.info("Generating plots...")
        cm_path = ARTIFACTS_DIR / "confusion_matrix.png"
        roc_path = ARTIFACTS_DIR / "roc_curve.png"
        fi_path = ARTIFACTS_DIR / "feature_importance.png"
        plot_confusion_matrix(y_test, y_pred, cm_path)
        plot_roc_curve(y_test, y_score, metrics["roc_auc"], roc_path)
        plot_feature_importance(model, X_train.columns.tolist(), fi_path)
        mlflow.log_artifact(str(cm_path))
        mlflow.log_artifact(str(roc_path))
        mlflow.log_artifact(str(fi_path))

        fi_df = pd.DataFrame({
            "feature": X_train.columns,
            "importance": model.feature_importances_,
        }).sort_values("importance", ascending=False)
        fi_json = ARTIFACTS_DIR / "feature_importance.json"
        fi_json.write_text(fi_df.to_json(orient="records", indent=2))
        mlflow.log_artifact(str(fi_json))
        logger.info("Top 5 features by importance:")
        for _, row in fi_df.head().iterrows():
            logger.info("  {:30s} {:.4f}", row["feature"], row["importance"])

        model_path = MODELS_DIR / "xgboost_v1.pkl"
        joblib.dump(model, model_path)
        logger.info("Model saved to {}", model_path)
        mlflow.log_artifact(str(model_path))

        try:
            mlflow.xgboost.log_model(
                xgb_model=model,
                artifact_path="model",
                input_example=X_train.head(3),
            )
            logger.info("Model also registered in MLflow native format.")
        except Exception as e:
            logger.warning("MLflow native log_model skipped (server/client version mismatch): {}",
                           str(e)[:120])

        logger.success("XGBoost run complete. View at {}/#/experiments",
                       MLFLOW_TRACKING_URI)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
