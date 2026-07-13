"""Random Forest fraud classifier — trained on engineered IEEE-CIS features.

This is the BASELINE model. Establishes a solid floor (ROC-AUC ~0.92-0.94 on
this dataset) that XGBoost should beat by 1-3 points.

Pipeline:
    1. Load X_train / y_train / X_test / y_test from data/processed/
    2. Train RandomForestClassifier (class-balanced for fraud imbalance)
    3. Predict probabilities on test set
    4. Log metrics + artifacts to MLflow (http://localhost:5000)
    5. Persist the trained model to models/random_forest_v1.pkl

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.training.train_rf

Env vars (optional):
    MLFLOW_TRACKING_URI    (default: http://localhost:5000)
    RF_N_ESTIMATORS        (default: 200)
    RF_MAX_DEPTH           (default: 16)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")  # Headless backend — avoids Windows Tk threading crash on script exit
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
import seaborn as sns
from loguru import logger
from sklearn.ensemble import RandomForestClassifier
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
ARTIFACTS_DIR = PROJECT_ROOT / "data" / "processed" / "rf_artifacts"

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = "fraud-detection"
RUN_NAME = "random_forest_v1"

N_ESTIMATORS = int(os.getenv("RF_N_ESTIMATORS", "200"))
MAX_DEPTH = int(os.getenv("RF_MAX_DEPTH", "16"))
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
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", ax=ax,
                xticklabels=["Legit", "Fraud"],
                yticklabels=["Legit", "Fraud"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Random Forest — Confusion Matrix (threshold=0.5)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


def plot_roc_curve(y_true, y_score, auc: float, out_path: Path) -> None:
    fpr, tpr, _ = roc_curve(y_true, y_score)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(fpr, tpr, lw=2, label=f"AUC = {auc:.4f}")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="Random")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("Random Forest — ROC Curve")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


def plot_feature_importance(model, feature_names: list[str], out_path: Path,
                            top_n: int = 20) -> None:
    importances = pd.Series(model.feature_importances_, index=feature_names)
    top = importances.sort_values(ascending=True).tail(top_n)
    fig, ax = plt.subplots(figsize=(8, 7))
    top.plot.barh(ax=ax, color="steelblue")
    ax.set_title(f"Random Forest — Top {top_n} Feature Importances")
    ax.set_xlabel("Importance (Gini)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main training pipeline
# ---------------------------------------------------------------------------
def main() -> int:
    # Setup
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("MLflow tracking URI: {}", MLFLOW_TRACKING_URI)
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    # Load data
    X_train, y_train, X_test, y_test = load_splits()

    with mlflow.start_run(run_name=RUN_NAME) as run:
        run_id = run.info.run_id
        logger.info("MLflow run started: {} (id={})", RUN_NAME, run_id)

        # Log hyperparameters
        params = {
            "model_type": "RandomForestClassifier",
            "n_estimators": N_ESTIMATORS,
            "max_depth": MAX_DEPTH,
            "class_weight": "balanced",
            "random_state": RANDOM_STATE,
            "n_features": X_train.shape[1],
            "n_train": len(X_train),
            "n_test": len(X_test),
        }
        mlflow.log_params(params)

        # Train
        logger.info("Training RandomForest (n_estimators={}, max_depth={})...",
                    N_ESTIMATORS, MAX_DEPTH)
        t0 = time.monotonic()
        model = RandomForestClassifier(
            n_estimators=N_ESTIMATORS,
            max_depth=MAX_DEPTH,
            class_weight="balanced",
            random_state=RANDOM_STATE,
            n_jobs=-1,
            verbose=0,
        )
        model.fit(X_train, y_train)
        train_time = time.monotonic() - t0
        logger.success("Training complete in {:.1f}s", train_time)
        mlflow.log_metric("train_time_seconds", train_time)

        # Predict
        logger.info("Predicting on test set...")
        y_pred = model.predict(X_test)
        y_score = model.predict_proba(X_test)[:, 1]  # probability of fraud

        # Metrics
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
        logger.info("RANDOM FOREST — TEST SET RESULTS")
        logger.info("=" * 60)
        logger.info("  ROC-AUC      : {:.4f}", metrics["roc_auc"])
        logger.info("  PR-AUC       : {:.4f}", metrics["pr_auc"])
        logger.info("  Precision    : {:.4f}", metrics["precision"])
        logger.info("  Recall       : {:.4f}", metrics["recall"])
        logger.info("  F1           : {:.4f}", metrics["f1"])
        logger.info("  Confusion    : TN={} FP={} FN={} TP={}", tn, fp, fn, tp)
        logger.info("=" * 60)

        # Artifacts
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

        # Top-5 feature importance dump
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

        # Persist model locally as .pkl
        model_path = MODELS_DIR / "random_forest_v1.pkl"
        joblib.dump(model, model_path)
        logger.info("Model saved to {}", model_path)
        mlflow.log_artifact(str(model_path))

        # Try to log sklearn model in MLflow's native format (for Model Registry).
        # Skipped silently if server is MLflow 2.x and client is 3.x (version mismatch
        # on the new "Logged Models" endpoint). The .pkl above is the source of truth.
        try:
            mlflow.sklearn.log_model(
                sk_model=model,
                artifact_path="model",
                input_example=X_train.head(3),
            )
            logger.info("Model also registered in MLflow native format.")
        except Exception as e:
            logger.warning("MLflow native log_model skipped (server/client version mismatch): {}",
                           str(e)[:120])

        logger.success("Random Forest run complete. View at {}/#/experiments",
                       MLFLOW_TRACKING_URI)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
