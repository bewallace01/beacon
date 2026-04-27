"""Polaris — project orchestrator bot.

Reads a project's MEMORY.md and TASKS.md from the bundle root on every
tick, calls Claude with the orchestrator system prompt, parses the
structured plan, and emits it as a `polaris.plan` event so the
dashboard can render it.

Phase 6A scope: read-only. No PRs, no command dispatch. Polaris produces
visible recommendations only. See TASKS.md "Phase 6" for the demo
criterion and the 6B+ roadmap.

Phase 6.2 added structured-plan schema + hash-skip change detection:
the bot remembers the last successfully-emitted doc hashes in process
memory and skips the LLM call when both files are byte-identical. A
fresh deploy resets that state, so re-deploying always regenerates a
plan even on unchanged docs (intentional — confirms the new bundle's
prompt still produces good output).

Real orchestrator prompt iteration lands in 6.5.

Env (defaults in parens):
  POLARIS_POLL_S     seconds between ticks (3600)
  POLARIS_MODEL      Claude model id (claude-opus-4-7)
  POLARIS_DOCS_DIR   where to find MEMORY.md / TASKS.md (.)
  POLARIS_DRY_RUN    skip the Anthropic call, useful for verification (unset)

Workspace secrets (injected by the worker):
  LIGHTSEI_API_KEY    required; bot authenticates to Lightsei with this
  ANTHROPIC_API_KEY   required unless POLARIS_DRY_RUN=1
"""

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

import lightsei


POLL_S = float(os.environ.get("POLARIS_POLL_S", "3600"))
MODEL = os.environ.get("POLARIS_MODEL", "claude-opus-4-7")
DOCS_DIR = Path(os.environ.get("POLARIS_DOCS_DIR", "."))
DRY_RUN = os.environ.get("POLARIS_DRY_RUN") == "1"
SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.md"

# In-process change-detection state. Reset on every bot restart, so a
# redeploy always regenerates a plan against the current docs.
_last_hashes: Optional[dict] = None


def _read_docs() -> dict:
    memory = (DOCS_DIR / "MEMORY.md").read_text()
    tasks = (DOCS_DIR / "TASKS.md").read_text()
    return {
        "memory_md": memory,
        "tasks_md": tasks,
        "hashes": {
            "memory_md": hashlib.sha256(memory.encode()).hexdigest()[:16],
            "tasks_md": hashlib.sha256(tasks.encode()).hexdigest()[:16],
        },
    }


def _call_claude(system_prompt: str, docs: dict) -> dict:
    import anthropic

    user_msg = (
        f"<MEMORY.md>\n{docs['memory_md']}\n</MEMORY.md>\n\n"
        f"<TASKS.md>\n{docs['tasks_md']}\n</TASKS.md>"
    )
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        temperature=0.2,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = resp.content[0].text if resp.content else ""
    return {
        "text": text,
        "model": MODEL,
        "tokens_in": resp.usage.input_tokens,
        "tokens_out": resp.usage.output_tokens,
    }


def _parse_plan(text: str) -> tuple[Optional[dict], Optional[str]]:
    """Parse Claude's JSON response into structured plan fields.

    Returns (parsed, parse_error). Exactly one is None.
    Tolerates the common case where Claude wraps the JSON in a
    ```json fence despite being told not to.
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        # strip leading fence with optional language tag
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
        if candidate.endswith("```"):
            candidate = candidate[: -len("```")].rstrip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        return None, f"json decode: {e}"
    if not isinstance(data, dict):
        return None, "top-level value is not a JSON object"
    return {
        "summary": data.get("summary"),
        "next_actions": data.get("next_actions") or [],
        "parking_lot_promotions": data.get("parking_lot_promotions") or [],
        "drift": data.get("drift") or [],
    }, None


@lightsei.track
def tick() -> None:
    global _last_hashes
    docs = _read_docs()
    print(
        f"docs: memory={docs['hashes']['memory_md']} "
        f"tasks={docs['hashes']['tasks_md']}",
        flush=True,
    )

    if _last_hashes == docs["hashes"]:
        print("docs unchanged since last plan, skipping LLM call", flush=True)
        lightsei.emit(
            "polaris.tick_skipped",
            {"reason": "docs unchanged", "hashes": docs["hashes"]},
        )
        return

    if DRY_RUN:
        print("dry run: skipping Anthropic call", flush=True)
        lightsei.emit("polaris.tick_dry_run", {"hashes": docs["hashes"]})
        _last_hashes = docs["hashes"]
        return

    system_prompt = SYSTEM_PROMPT_PATH.read_text()
    result = _call_claude(system_prompt, docs)
    parsed, parse_error = _parse_plan(result["text"])

    payload = {
        "text": result["text"],
        "doc_hashes": docs["hashes"],
        "model": result["model"],
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
    }
    if parsed is not None:
        payload.update(parsed)
        print(
            f"plan: {len(parsed['next_actions'])} actions, "
            f"{len(parsed['parking_lot_promotions'])} promotions, "
            f"{len(parsed['drift'])} drift items "
            f"({result['tokens_in']} in / {result['tokens_out']} out)",
            flush=True,
        )
    else:
        payload["parse_error"] = parse_error
        print(f"plan parse failed: {parse_error}", flush=True)

    lightsei.emit("polaris.plan", payload)

    # Update the last-seen hashes only when we got a clean parse, so a
    # transient parse failure retries on the next tick instead of silently
    # waiting for the docs to change.
    if parsed is not None:
        _last_hashes = docs["hashes"]


def main() -> None:
    api_key = os.environ.get("LIGHTSEI_API_KEY")
    base_url = os.environ.get("LIGHTSEI_BASE_URL", "https://api.lightsei.com")
    agent_name = os.environ.get("LIGHTSEI_AGENT_NAME", "polaris")

    if not api_key:
        print("LIGHTSEI_API_KEY not set; can't ingest events", flush=True)
        sys.exit(1)

    lightsei.init(
        api_key=api_key,
        agent_name=agent_name,
        version="0.1.0",
        base_url=base_url,
    )

    print(
        f"polaris up: agent={agent_name} model={MODEL} poll={POLL_S}s "
        f"docs={DOCS_DIR.resolve()} dry_run={DRY_RUN}",
        flush=True,
    )

    while True:
        try:
            tick()
        except Exception:
            print(f"tick crashed:\n{traceback.format_exc()}", flush=True)
        lightsei.flush(timeout=2.0)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
