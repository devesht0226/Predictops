"""Time-series forecasting engine for PredictOps."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(exist_ok=True)
MODEL_PATH = MODEL_DIR / "forecast_model.joblib"
META_PATH = MODEL_DIR / "model_meta.json"
METRICS_DB = Path(__file__).parent / "metrics.db"

REQUIRED_COLUMNS = {"date", "value"}
DEFAULT_THRESHOLD = 45.0
FORECAST_HORIZON = 7
LAG_DAYS = [1, 2, 3, 7, 14]


@dataclass
class TrainResult:
    model_version: str
    mape: float
    samples: int
    trained_at: str
    improved: bool


@dataclass
class PredictResult:
    model_version: str
    horizon: int
    forecasts: list[dict]
    threshold: float
    alert_required: bool
    alert_reason: str | None
    generated_at: str


def init_metrics_db() -> None:
    with sqlite3.connect(METRICS_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                model_version TEXT,
                mape REAL,
                horizon INTEGER,
                alert_required INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )


def load_meta() -> dict:
    if not META_PATH.exists():
        return {}
    return json.loads(META_PATH.read_text(encoding="utf-8"))


def save_meta(meta: dict) -> None:
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    if df["value"].isna().any():
        raise ValueError("CSV contains non-numeric values")
    return df


def build_features(series: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame({"value": series.values})
    for lag in LAG_DAYS:
        frame[f"lag_{lag}"] = frame["value"].shift(lag)
    frame["rolling_mean_7"] = frame["value"].shift(1).rolling(7).mean()
    frame["rolling_std_7"] = frame["value"].shift(1).rolling(7).std()
    frame["day_of_week"] = np.arange(len(frame)) % 7
    return frame.dropna()


def train_model(csv_path: Path) -> TrainResult:
    df = load_csv(csv_path)
    if len(df) < 30:
        raise ValueError("Need at least 30 rows to train")

    features = build_features(df["value"])
    target = df["value"].iloc[len(df) - len(features) :].values

    split_idx = max(int(len(features) * 0.8), 1)
    x_train, x_val = features.iloc[:split_idx], features.iloc[split_idx:]
    y_train, y_val = target[:split_idx], target[split_idx:]

    model = GradientBoostingRegressor(random_state=42)
    model.fit(x_train, y_train)

    mape = float(mean_absolute_percentage_error(y_val, model.predict(x_val))) if len(y_val) else 0.0

    previous = load_meta()
    previous_mape = previous.get("mape")
    improved = previous_mape is None or mape <= previous_mape

    version = datetime.utcnow().strftime("v%Y%m%d-%H%M%S")
    if improved:
        joblib.dump(model, MODEL_PATH)

    meta = {
        "model_version": version,
        "mape": round(mape, 4),
        "samples": len(df),
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "csv_path": str(csv_path),
        "previous_mape": previous_mape,
        "improved": improved,
        "active": improved,
    }
    save_meta(meta)
    log_run("train", version, mape, None, False)

    return TrainResult(
        model_version=version,
        mape=round(mape, 4),
        samples=len(df),
        trained_at=meta["trained_at"],
        improved=improved,
    )


def iterative_forecast(df: pd.DataFrame, horizon: int) -> list[dict]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError("No trained model found. Call /train first.")

    model = joblib.load(MODEL_PATH)
    meta = load_meta()
    history = df["value"].tolist()
    last_date = df["date"].iloc[-1]
    forecasts: list[dict] = []

    for step in range(1, horizon + 1):
        series = pd.Series(history)
        features = build_features(series).iloc[[-1]]
        prediction = float(model.predict(features)[0])
        prediction = max(0.0, prediction)

        forecast_date = (last_date + timedelta(days=step)).strftime("%Y-%m-%d")
        forecasts.append(
            {
                "date": forecast_date,
                "predicted_value": round(prediction, 2),
                "day_offset": step,
            }
        )
        history.append(prediction)

    return forecasts


def predict(csv_path: Path, horizon: int = FORECAST_HORIZON, threshold: float = DEFAULT_THRESHOLD) -> PredictResult:
    df = load_csv(csv_path)
    meta = load_meta()
    if not meta:
        raise FileNotFoundError("Model metadata missing. Call /train first.")

    forecasts = iterative_forecast(df, horizon)
    values = [item["predicted_value"] for item in forecasts]
    avg_value = sum(values) / len(values)
    max_value = max(values)

    alert_required = avg_value >= threshold or max_value >= threshold + 5
    alert_reason = None
    if alert_required:
        if max_value >= threshold + 5:
            alert_reason = f"Peak forecast {max_value:.1f} exceeds critical threshold {threshold + 5:.1f}"
        else:
            alert_reason = f"Average forecast {avg_value:.1f} exceeds threshold {threshold:.1f}"

    log_run("predict", meta.get("model_version"), meta.get("mape"), horizon, alert_required)

    return PredictResult(
        model_version=meta.get("model_version", "unknown"),
        horizon=horizon,
        forecasts=forecasts,
        threshold=threshold,
        alert_required=alert_required,
        alert_reason=alert_reason,
        generated_at=datetime.utcnow().isoformat() + "Z",
    )


def get_metrics() -> dict:
    meta = load_meta()
    with sqlite3.connect(METRICS_DB) as conn:
        rows = conn.execute(
            """
            SELECT run_type, model_version, mape, horizon, alert_required, created_at
            FROM run_log
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

    recent_runs = [
        {
            "run_type": row[0],
            "model_version": row[1],
            "mape": row[2],
            "horizon": row[3],
            "alert_required": bool(row[4]),
            "created_at": row[5],
        }
        for row in rows
    ]

    return {
        "model_version": meta.get("model_version"),
        "mape": meta.get("mape"),
        "samples": meta.get("samples"),
        "trained_at": meta.get("trained_at"),
        "improved": meta.get("improved"),
        "recent_runs": recent_runs,
    }


def log_run(
    run_type: str,
    model_version: str | None,
    mape: float | None,
    horizon: int | None,
    alert_required: bool,
) -> None:
    init_metrics_db()
    with sqlite3.connect(METRICS_DB) as conn:
        conn.execute(
            """
            INSERT INTO run_log (run_type, model_version, mape, horizon, alert_required, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_type,
                model_version,
                mape,
                horizon,
                int(alert_required),
                datetime.utcnow().isoformat() + "Z",
            ),
        )
