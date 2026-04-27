# worker

The Phase 5 runtime: a single-host process that spawns and supervises bots
on behalf of Lightsei deployments.

## Files

- `runner.py` — production worker. Polls the backend for queued deployments,
  builds a venv per deployment, spawns the bot, streams logs back. Runs
  multiple bots concurrently (one supervisor thread per deployment).
- `run_local.py` — Phase A POC kept around as a manual debugging tool. Same
  lifecycle shape as `runner.py` but driven by a local zip + `--env` flags
  instead of the backend. Useful for testing a bot offline.

Tests for the worker live alongside the backend tests at
`backend/tests/test_worker_runner.py` so they share the Postgres + TestClient
fixtures. The worker is added to pytest's pythonpath via
`backend/pytest.ini`.

## Run the production worker

```bash
export LIGHTSEI_WORKER_TOKEN=...           # match the backend's value
export LIGHTSEI_BASE_URL=https://api.lightsei.com
python worker/runner.py
```

The worker polls every ~5 seconds for queued deployments, claims one
atomically (Postgres `FOR UPDATE SKIP LOCKED`), and runs it. A stale
heartbeat from a dead worker (>90s) lets another worker re-claim, so the
crash-recovery story is built in.

### What the worker injects into the bot subprocess

- All workspace secrets as env vars (so e.g. `OPENAI_API_KEY` is just there).
- `LIGHTSEI_AGENT_NAME` pinned to the deployment's agent name.
- `LIGHTSEI_BASE_URL` inherited from the worker.

You should also set a `LIGHTSEI_API_KEY` workspace secret containing one of
your workspace's api keys; the bot needs it to authenticate (heartbeat its
SDK identity, send events, call `lightsei.get_secret()`). Auto-minting a
deployment-scoped key is a follow-up.

### What the worker does NOT do (yet)

- **No isolation.** Bots run as the worker's user. This is fine when you're
  the only user; it is a dealbreaker for accepting other people's code.
  Phase 5B (Fly Machines / Modal sandboxes) is the cure.
- **No scratch GC.** Each deployment's venv lives at
  `/tmp/lightsei-worker/<deployment_id>/` indefinitely. Manual `rm -rf`
  for now.
- **No build cache.** Every redeploy rebuilds the venv from scratch
  (~30-60s for a typical bot). A requirements-hash cache lands in 5B.
- **No log retention beyond 1000 lines per deployment.** The backend
  prunes oldest lines on each insert.

## Quick spike (no backend needed)

`run_local.py` is the throwaway tool. Useful when you want to verify a
specific bot survives the runner lifecycle without going through the
deploy → claim → run path.

See the `run_local.py` docstring for the CLI shape; nothing about it
depends on the deployments table.
