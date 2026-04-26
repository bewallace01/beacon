# Beacon

Drop-in observability and guardrails for AI agents and bots.

## Demo

The whole loop: bot → SDK → backend → dashboard. Covers both providers and streaming.

```bash
# 1. start the stack (backend on :8000, dashboard on :3000)
docker compose up --build

# 2. install the SDK and provider clients (in another terminal, ideally a venv)
pip install -e ./sdk openai anthropic

# 3. set your provider keys
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# 4. run the demo
python examples/demo_bot.py

# 5. open the dashboard
open http://localhost:3000
```

Four runs will appear within a few seconds: OpenAI (regular and streaming) and Anthropic (regular and streaming). Each shows model, latency, and token counts. Click any run to see its events.

## For people building this

Start with `MEMORY.md`, then `TASKS.md`. That's the whole plan.

## Layout

```
backend/     FastAPI ingest service (SQLite for now)
sdk/         Python SDK (install with `pip install -e ./sdk`)
dashboard/   Next.js dashboard
examples/    demo bots
```

## For users (eventually)

```bash
pip install beacon
```

```python
import beacon
beacon.init("sk-...")
```

That's the install. Everything after that is automatic.
