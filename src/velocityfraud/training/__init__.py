"""Layer 2 — Model training pipeline.

Modules:
    features  : IEEE-CIS CSV -> engineered feature matrix (saved to parquet)
    train_rf  : Random Forest classifier with MLflow tracking
    train_xgb : XGBoost classifier with MLflow tracking
"""
