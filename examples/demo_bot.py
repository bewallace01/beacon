"""The Lightsei end-to-end demo.

Calls OpenAI and Anthropic, in both regular and streaming modes. Watch the
runs appear at http://localhost:3000.

Run:
    pip install -e ./sdk openai anthropic
    docker compose up --build           # in another terminal
    export OPENAI_API_KEY=sk-...
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/demo_bot.py

To point at a local fake server (no real API calls), set OPENAI_BASE_URL and
ANTHROPIC_BASE_URL.
"""

import os
import time

import anthropic
import lightsei
import openai


LIGHTSEI_URL = os.environ.get("LIGHTSEI_BASE_URL", "http://localhost:8000")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")


def main() -> None:
    lightsei.init(
        api_key=os.environ.get("LIGHTSEI_API_KEY", "demo-key"),
        agent_name="multi-provider-demo",
        version="0.2.0",
        base_url=LIGHTSEI_URL,
    )

    oai = openai.OpenAI()  # picks up OPENAI_API_KEY and OPENAI_BASE_URL
    ant = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL

    @lightsei.track
    def openai_regular() -> str:
        lightsei.emit("step", {"name": "openai-regular"})
        resp = oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": "In one sentence, what is observability?"}],
        )
        return resp.choices[0].message.content or ""

    @lightsei.track
    def openai_streaming() -> str:
        lightsei.emit("step", {"name": "openai-streaming"})
        parts: list[str] = []
        stream = oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": "Stream me a haiku about agents."}],
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                parts.append(chunk.choices[0].delta.content)
        return "".join(parts)

    @lightsei.track
    def anthropic_regular() -> str:
        lightsei.emit("step", {"name": "anthropic-regular"})
        msg = ant.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": "Name three reasons agents need guardrails."}],
        )
        return msg.content[0].text

    @lightsei.track
    def anthropic_streaming() -> str:
        lightsei.emit("step", {"name": "anthropic-streaming"})
        parts: list[str] = []
        stream = ant.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": "Stream a short pep talk for a flaky chatbot."}],
            stream=True,
        )
        for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                parts.append(event.delta.text)
        return "".join(parts)

    runs = [
        ("openai regular   ", openai_regular),
        ("openai streaming ", openai_streaming),
        ("anthropic regular", anthropic_regular),
        ("anthropic stream ", anthropic_streaming),
    ]
    for label, fn in runs:
        print(f"[{label}] running...")
        out = fn()
        snippet = out.strip().replace("\n", " ")[:120]
        print(f"           -> {snippet}")

    lightsei.flush(timeout=5.0)
    time.sleep(0.5)
    print("\nopen http://localhost:3000 to see the runs.")


if __name__ == "__main__":
    main()
