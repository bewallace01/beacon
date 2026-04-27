# worker (Phase A POC)

Throwaway exploration for "Lightsei hosts your bot" — see the parking-lot
discussion in `MEMORY.md` once that phase is committed.

## What's here

- `run_local.py` — single-file CLI that takes a directory, builds a venv,
  installs requirements, spawns the bot, streams logs, restarts on crash.

That's it. There is intentionally no backend integration, no GitHub fetch,
no isolation, no log shipping, no secrets injection beyond `--env`.

## Try it

Take a tiny bot directory:

```
example-bot/
  bot.py
  requirements.txt
```

`bot.py`:

```python
import lightsei, time, os
lightsei.init(api_key=os.environ["LIGHTSEI_API_KEY"], agent_name="poc-bot")
print("hi from the bot", flush=True)
while True:
    time.sleep(10)
```

`requirements.txt`:

```
lightsei
```

Run it under the POC:

```
python worker/run_local.py ./example-bot \
    --env LIGHTSEI_API_KEY=bk_... \
    --env LIGHTSEI_BASE_URL=https://api.lightsei.com
```

You should see:
- a venv created at `.lightsei-runtime/example-bot/.venv`
- pip install output
- the bot's stdout/stderr mirrored to your terminal AND saved to
  `.lightsei-runtime/logs/example-bot/stdout.log`
- the bot showing up as a "live" instance in app.lightsei.com
- Ctrl+C terminates the bot cleanly

To exercise the restart path: edit your bot to `raise SystemExit(1)` after
a few seconds and watch the runner back off.

## What this proves (and doesn't)

**Proves:** the loop works. A control plane can call this shape — start,
run, capture, restart, stop — without inventing anything novel. The bot's
own SDK heartbeat flows through unchanged.

**Doesn't prove:** that the bot is *isolated* (it isn't — it runs as your
user), that this is *safe for other people's code* (no), that logs scale
past a single host (no), that secrets injection from the dashboard works
(not wired). All those are Phase B+ when we replace the in-process Popen
with Fly Machines / Modal sandboxes.

## What lifts into production

When (if) Phase A ships, the durable pieces are:

1. The "venv per bot, python -u entry, line-buffered stdout, restart with
   backoff" lifecycle — stays the same shape inside a container.
2. The split between `runtime_dir` (mutable scratch) and `log_dir` (which
   gets shipped to the backend).
3. The env-var-as-config contract: workspace secrets become env vars at
   spawn time, the bot reads them with `os.environ` or
   `lightsei.get_secret()`.

What gets replaced:

1. The Popen call becomes `runtime.start(deployment_id)` against a
   `Runtime` interface with `LocalDockerRuntime` and `FlyMachinesRuntime`
   implementations.
2. The log streams get teed to a backend `/deployments/{id}/logs`
   endpoint instead of a flat file.
3. The `bot_dir` argument becomes a `source_url` fetched from object
   storage (R2 / Railway volume), populated by `lightsei deploy` or a
   GitHub webhook.

If after using this for a day or two the lifecycle still feels right,
that's the green light to commit to Phase A in the main codebase.
