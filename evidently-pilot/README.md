# VelocityFraud — Evidently evaluation (separate from the project)

This folder tests the VelocityFraud model and live pipeline **without changing the project and without touching the cloud server**.

- `velocityfraud/` is only **read**: the model, the data files and the live-feature code. Nothing is installed into it and nothing is written to it.
- Nothing here connects to Kafka, Redis, Postgres or the Hetzner server. Everything runs on the laptop.
- Evidently has its own `.venv` in this folder. It needs pandas 2, while the project uses pandas 3.
- It now lives inside the repo as `evidently-pilot/`, still separate from the project code: nothing in `src/` imports it. `out/` and the per-run HTML reports stay on the laptop (gitignored, because they hold transaction-level data built from the IEEE-CIS dataset); only `reports/00_MASTER_QA_AUDIT.html` is committed.

## How it works

**Step 1 — `step1_score.py`** runs with the project's own Python, read-only, so it uses exactly the production model and code. It does two things:

1. **Replica check.** It re-scores the 4,692 events the live server already scored (`data/exports/scored_events_bronze.csv`) and confirms the laptop reproduces the server's scores. Then it attaches the true IEEE-CIS label to each event.
2. **Same-transaction comparison.** For each held-out test transaction (never used in training), it computes two scores:
   - the **offline** score, from the full 43 training features;
   - the **live** score, from what the pipeline builds out of the Avro event (`replayer.row_to_event` → `live_features.featurize_event`).

**Step 2 — `step2_reports.py`** runs in this folder's `.venv` and writes `reports/<tag>/`:

| File | What it shows |
|---|---|
| `00_SUMMARY.md` | Replica check, ROC/PR-AUC, business metrics ($ caught or missed, alerts per 1,000, customers blocked), feature parity, segments |
| `01_offline_vs_live_same_transactions.html` | Evidently classification report. Reference = offline, Current = live, on the same transactions |
| `02_feature_drift_training_vs_live.html` | Evidently drift report: which features look different live |
| `03_real_live_server_events.html` | Evidently classification report on the real server-scored events, against the true labels |

## Re-run

From this folder:

```powershell
# pilot (500 transactions)
..\.venv\Scripts\python.exe step1_score.py --n 500
.venv\Scripts\python.exe step2_reports.py --tag n500

# full held-out test split (118,108 transactions)
..\.venv\Scripts\python.exe step1_score.py --n all
.venv\Scripts\python.exe step2_reports.py --tag n118108
```

Step 1 turns off bytecode caching before it imports any project code, so it writes no `__pycache__` into the project.

## What-if: the live-feature fixes (steps 3 and 4)

These steps need step 1's output for the same tag.

- **`live_features_fixed.py`** is a vectorised copy of the project's `live_features.py`, with the FINDINGS fixes behind switches. With no switches it reproduces the project's output exactly.
- **`step3_whatif.py`** runs in the project's Python, read-only. It:
  - re-scores the same transactions with each fix alone, with all code fixes, and with a richer event;
  - checks itself first;
  - refuses to finish if the project's git state changed.
- **`step4_whatif_report.py`** runs in this folder's `.venv`. It writes `04_WHATIF_SUMMARY.md` and three Evidently reports:
  - `05` live today vs. fixed;
  - `06` richer event vs. offline;
  - `07` feature drift, training vs. fixed live.

```powershell
..\.venv\Scripts\python.exe step3_whatif.py --n 500      # pilot
.venv\Scripts\python.exe step4_whatif_report.py --tag n500
..\.venv\Scripts\python.exe step3_whatif.py --n all      # full, about 2 minutes
.venv\Scripts\python.exe step4_whatif_report.py --tag n118108
```

## Extended checks (steps 5 and 6)

These steps need step 1's full run (`n118108`).

- **`step5_extended.py`** runs in the project's Python, read-only, in about 4 minutes. It:
  - scores the Random Forest;
  - runs an out-of-time test and a random split with the same clean recipe (two XGBoost models trained in memory only; nothing is written to `velocityfraud/models`);
  - collects segment and time-window data.
- **`step6_extended_reports.py`** runs in this folder's `.venv`, in about 3 minutes. It writes `reports/extended/`:
  - `08_EXTENDED_SUMMARY.md`;
  - Evidently reports 09–14 (Random Forest vs XGBoost, out-of-time, demo threshold, data quality ×2, drift over time);
  - four `15_quality_gate_*` pass/fail reports.

```powershell
..\.venv\Scripts\python.exe step5_extended.py
.venv\Scripts\python.exe step6_extended_reports.py
```
