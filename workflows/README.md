# n8n Workflows

Import these JSON files in n8n (**Workflows → Import from file**).

| File | Schedule | Purpose |
|------|----------|---------|
| `predictops-daily.json` | Every 24h | Forecast 7 days, alert if over threshold, log metrics |
| `predictops-retrain.json` | Every week | Retrain model; promote only if MAPE improves |

## Required API URLs (local n8n on same PC)

| Node | URL |
|------|-----|
| Run Forecast | `http://127.0.0.1:8000/predict?horizon=7&threshold=45` |
| Fetch Metrics | `http://127.0.0.1:8000/metrics` |
| Train Model | `http://127.0.0.1:8000/train` |

Train the model once via http://127.0.0.1:8000/docs before the first forecast run.
