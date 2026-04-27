"""Polaris — project orchestrator bot.

Reads a project's MEMORY.md and TASKS.md from the bundle root on every
tick, calls Claude with the orchestrator system prompt, and emits the
generated plan as a Lightsei event so the dashboard can render it.

Phase 6A scope: read-only. No PRs, no command dispatch. Polaris produces
visible recommendations only. See TASKS.md "Phase 6" for the demo
criterion and the 6B+ roadmap.

This file is the 6.1 scaffold: the loop, the doc-reading, and the
Anthropic call shape. The structured `polaris.plan` schema + hash-skip
logic land in 6.2; the real orchestrator system prompt lands in 6.5.

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
import os
import sys
import time
import traceback
from pathlib import Path

import lightsei


POLL_S = float(os.environ.get("POLARIS_POLL_S", "3600"))
MODEL = os.environ.get("POLARIS_MODEL", "claude-opus-4-7")
DOCS_DIR = Path(os.environ.get("POLARIS_DOCS_DIR", "."))
DRY_RUN = os.environ.get("POLARIS_DRY_RUN") == "1"
SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.md"


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


@lightsei.track
def tick() -> None:
    docs = _read_docs()
    print(
        f"docs: memory={docs['hashes']['memory_md']} "
        f"tasks={docs['hashes']['tasks_md']}",
        flush=True,
    )

    if DRY_RUN:
        print("dry run: skipping Anthropic call", flush=True)
        lightsei.emit("polaris.tick_dry_run", {"hashes": docs["hashes"]})
        return

    system_prompt = SYSTEM_PROMPT_PATH.read_text()
    result = _call_claude(system_prompt, docs)
    print(
        f"plan generated: {result['tokens_in']} in / "
        f"{result['tokens_out']} out / {len(result['text'])} chars",
        flush=True,
    )
    lightsei.emit(
        "polaris.plan_raw",
        {
            "text": result["text"],
            "hashes": docs["hashes"],
            "model": result["model"],
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
        },
    )


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
