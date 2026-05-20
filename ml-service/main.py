"""PredictOps ML API — train, predict, and metrics endpoints."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from forecaster import (
    DEFAULT_THRESHOLD,
    FORECAST_HORIZON,
    TrainResult,
    get_metrics,
    init_metrics_db,
    predict,
    train_model,
)

def _resolve_default_csv() -> Path:
    base = Path(__file__).resolve().parent
    for candidate in (
        base / "sample-data" / "support_tickets.csv",
        base.parent / "sample-data" / "support_tickets.csv",
    ):
        if candidate.exists():
            return candidate
    return base.parent / "sample-data" / "support_tickets.csv"


DEFAULT_CSV = _resolve_default_csv()

app = FastAPI(
    title="PredictOps ML API",
    description="Forecasting service for n8n orchestration",
    version="1.0.0",
)


class TrainResponse(BaseModel):
    status: str
    model_version: str
    mape: float
    samples: int
    trained_at: str
    improved: bool


class PredictResponse(BaseModel):
    status: str
    model_version: str
    horizon: int
    threshold: float
    alert_required: bool
    alert_reason: str | None
    forecasts: list[dict]
    generated_at: str


class MetricsResponse(BaseModel):
    model_version: str | None
    mape: float | None
    samples: int | None
    trained_at: str | None
    improved: bool | None
    recent_runs: list[dict]


@app.on_event("startup")
def startup() -> None:
    init_metrics_db()


@app.get("/")
def root() -> dict:
    return {
        "service": "PredictOps ML API",
        "status": "running",
        "message": "Open /docs to test endpoints. Do not use 0.0.0.0 in the browser — use localhost.",
        "endpoints": {
            "GET /health": "http://localhost:8000/health",
            "GET /metrics": "http://localhost:8000/metrics",
            "GET /docs": "http://localhost:8000/docs",
            "POST /train": "http://localhost:8000/train (use docs or PowerShell, not browser address bar)",
            "POST /predict": "http://localhost:8000/predict?horizon=7&threshold=45",
        },
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "predictops-ml"}


@app.post("/train", response_model=TrainResponse)
def train(
    csv_path: str | None = Query(default=None, description="Optional path to CSV dataset"),
) -> TrainResponse:
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"CSV not found: {path}")

    try:
        result: TrainResult = train_model(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return TrainResponse(
        status="trained" if result.improved else "trained_skipped_promotion",
        model_version=result.model_version,
        mape=result.mape,
        samples=result.samples,
        trained_at=result.trained_at,
        improved=result.improved,
    )


@app.post("/predict", response_model=PredictResponse)
def run_predict(
    csv_path: str | None = Query(default=None),
    horizon: int = Query(default=FORECAST_HORIZON, ge=1, le=30),
    threshold: float = Query(default=DEFAULT_THRESHOLD, ge=1),
) -> PredictResponse:
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"CSV not found: {path}")

    try:
        result = predict(path, horizon=horizon, threshold=threshold)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PredictResponse(
        status="ok",
        model_version=result.model_version,
        horizon=result.horizon,
        threshold=result.threshold,
        alert_required=result.alert_required,
        alert_reason=result.alert_reason,
        forecasts=result.forecasts,
        generated_at=result.generated_at,
    )


@app.get("/metrics", response_model=MetricsResponse)
def metrics() -> MetricsResponse:
    data = get_metrics()
    return MetricsResponse(**data)
