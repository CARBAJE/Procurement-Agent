# analytics — Procurement Reporting Service

aiohttp microservice (port 8009) that owns all PostgreSQL reporting queries for the procurement dashboard. All dashboard data flows through this service — the frontend calls it via Next.js API proxy routes at `/api/analytics/*`.

## Endpoints

### `GET /health`

```json
{"status": "ok", "service": "analytics", "db_connected": true}
```

### `GET /analytics?period=30d|90d|180d`

Full dashboard payload. Default period: `90d`.

**Response fields:**
- `kpis` — `total_spend`, `total_savings`, `savings_percent`, `active_requests`, `pending_approval`, `completed_this_month`, `avg_cycle_time_hours`, `active_suppliers`
- `spend_over_time` — weekly time series of spend
- `request_volume` — weekly request count
- `acceptance_rate` — weekly % accepted vs. total
- `spend_by_category` — spend breakdown by category
- `cycle_time_by_category` — avg cycle time vs. baseline per category
- `negotiation_savings` — savings achieved through negotiation
- `supplier_metrics` — per-supplier performance metrics
- `recent_requests` — last 10 procurement requests

### `GET /business-impact?period=...`

Compact KPI set for the business impact UI section: `monthly_savings`, `requests_this_month`, `avg_cycle_time_hours`.

### `GET /benchmark?period=...`

CPO benchmarking: per-category contracted price vs. best available market price, gap percentage, projected annual savings.

## Fallback behavior

Returns **HTTP 503** when the database pool is unavailable. Does **not** serve mock data — callers must handle 503 explicitly. The `mock.py` module exists for local development use; import it directly if needed. It is not auto-served by the production server.

## Baseline cycle times

Used for `cycle_time_by_category` comparisons:

| Category | Baseline (hours) |
|----------|-----------------|
| Office Supplies | 72 |
| IT Equipment | 168 |
| Lab Supplies | 96 |
| Furniture | 120 |
| Marketing | 48 |

## Configuration

| Var | Default | Description |
|-----|---------|-------------|
| `PORT` | `8009` | Listen port |
| `DB_HOST` | `localhost` | |
| `DB_PORT` | `5432` | |
| `DB_NAME` | `procurement_agent` | |
| `DB_USER` | `postgres` | |
| `DB_PASSWORD` | `""` | |

## Run

```bash
docker compose up -d analytics
# or
python src/main.py
```
