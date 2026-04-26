# Beacon

Drop-in observability and guardrails for AI agents and bots.

Hosted at **https://app.lightsei.com**.

## Quickstart (use the hosted version)

```bash
# 1. install the SDK
pip install "git+https://github.com/bewallace01/beacon.git#subdirectory=sdk" openai

# 2. sign up at https://app.lightsei.com/signup, copy the api key (shown once)
export BEACON_API_KEY="bk_..."

# 3. point the SDK at the hosted backend
export BEACON_BASE_URL="https://api.lightsei.com"
```

```python
import beacon, openai, os

beacon.init(
    api_key=os.environ["BEACON_API_KEY"],
    agent_name="my-bot",
    base_url=os.environ["BEACON_BASE_URL"],
)

client = openai.OpenAI()  # picks up OPENAI_API_KEY
client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "hi"}],
)
```

Refresh https://app.lightsei.com to see the run.

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
