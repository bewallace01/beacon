# Lightsei

Drop-in observability and guardrails for AI agents.

```bash
pip install lightsei
```

```python
import lightsei
import openai

lightsei.init(api_key="bk_...", agent_name="my-bot")

oai = openai.OpenAI()  # auto-instrumented after init()

@lightsei.track
def reply(prompt: str) -> str:
    return oai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message.content
```

That's it. Every call now appears at [app.lightsei.com](https://app.lightsei.com)
with timestamps, model, latency, and token counts. No instrumentation,
no manual wrapping.

## What you get

- **Observability** — runs, events, costs, errors. Out of the box for
  OpenAI and Anthropic; one line of code per provider.
- **Guardrails** — daily cost caps, output validators (schema + content
  rules), behavioral checks. Caught before delivery, visible in the
  dashboard.
- **Polaris** — a project orchestrator bot you can deploy via Lightsei's
  PaaS. Reads your `MEMORY.md` + `TASKS.md` and proposes the next moves.
- **Notifications** — Slack, Discord, Teams, Mattermost, generic
  webhook. Polaris's plans land in your team chat, validation failures
  page you, agent crashes get reported.
- **Graceful degradation, non-negotiable** — if Lightsei's backend is
  unreachable or rejects an event, your bot keeps running. SDK never
  crashes the user's program.

## Configuration

```python
lightsei.init(
    api_key="bk_...",            # your workspace key from app.lightsei.com
    agent_name="my-bot",         # appears in dashboard + cost rollups
    version="0.1.0",             # optional — tags events
    base_url="https://api.lightsei.com",  # default
)
```

Sign up for a workspace API key at [app.lightsei.com/signup](https://app.lightsei.com/signup).

## Deploying bots on Lightsei

```bash
lightsei deploy ./my-bot --agent my-bot
```

Zips the directory, uploads to Lightsei's hosted runtime, builds a venv
from `requirements.txt`, runs `bot.py`. Logs stream into the dashboard.

## Links

- **Dashboard**: [app.lightsei.com](https://app.lightsei.com)
- **API**: [api.lightsei.com](https://api.lightsei.com)
- **Repository**: [github.com/bewallace01/lightsei](https://github.com/bewallace01/lightsei)
