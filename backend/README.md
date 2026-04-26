# Beacon Backend

FastAPI + SQLite. The spine ingest service.

## Run (Docker)

From the repo root:

```bash
docker compose up --build
```

Backend listens on `http://localhost:8000`. SQLite lives in the `beacon_data` volume so events survive restarts.

## Run (no Docker)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
BEACON_DB_PATH=./beacon.db uvicorn main:app --host 0.0.0.0 --port 8000
```

## Endpoints

### `POST /events`
Ingest a single telemetry event. Auto-creates the run on first event. If `kind` is `run_ended`, `run_completed`, or `run_failed`, sets `runs.ended_at`.

```bash
curl -s -X POST http://localhost:8000/events \
  -H 'content-type: application/json' \
  -d '{"run_id":"r1","agent_name":"demo","kind":"run_started","payload":{}}'
```

Response: `{"id": <event_id>, "status": "ok"}`

### `POST /policy/check`
Hardcoded allow during the spine. Real logic lands in Phase 2.

```bash
curl -s -X POST http://localhost:8000/policy/check \
  -H 'content-type: application/json' \
  -d '{"agent_name":"demo","action":"openai.chat.completions.create"}'
```

Response: `{"allow": true}`

### `GET /runs`
Recent runs, newest first. Optional `?limit=N` (default 50, max 500).

```bash
curl -s http://localhost:8000/runs
```

### `GET /runs/{run_id}/events`
All events for one run, oldest first. 404 if the run doesn't exist.

```bash
curl -s http://localhost:8000/runs/r1/events
```

## Schema

```sql
runs(id TEXT PK, agent_name TEXT, started_at TEXT, ended_at TEXT)
events(id INTEGER PK, run_id TEXT, agent_name TEXT, kind TEXT,
       payload_json TEXT, timestamp TEXT)
```

Timestamps are ISO 8601 UTC strings.
