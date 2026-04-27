#!/usr/bin/env python3
"""Local bot runner spike — Phase A POC for Lightsei-as-a-runtime.

Goal: prove the runner lifecycle without the backend in the loop.

Given a local directory containing `bot.py` + `requirements.txt`, this script:
  1. Creates a scratch venv at .lightsei-runtime/<bot-name>/.venv
  2. Installs requirements.txt into that venv (skip if absent)
  3. Spawns `python bot.py` as a subprocess with --env vars injected
  4. Streams stdout/stderr to log files AND mirrors them to this terminal
  5. Restarts on non-zero exit with exponential backoff (capped)
  6. On Ctrl+C, terminates the subprocess cleanly (SIGTERM → SIGKILL fallback)

Throwaway code. The point is to feel out the runner shape before committing
to Phase A in the main codebase. If this feels right, the same lifecycle
moves into a worker process driven by a `deployments` table.

Not in scope: backend wiring, GitHub fetch, build cache, sandboxing,
multi-tenancy, scaling, log shipping, secrets store integration.

Usage:
    python worker/run_local.py /path/to/bot-dir \\
        --env LIGHTSEI_API_KEY=bk_... \\
        --env LIGHTSEI_AGENT=poc-bot \\
        --env OPENAI_API_KEY=sk-...
"""
import argparse
import os
import subprocess
import sys
import threading
import time
import venv
from pathlib import Path
from typing import IO, Iterable


# ---------- helpers ----------

def ensure_venv(venv_dir: Path) -> Path:
    """Create venv if missing; return path to its python executable."""
    python = venv_dir / "bin" / "python"
    if not python.exists():
        print(f"[runner] creating venv at {venv_dir}")
        venv.create(str(venv_dir), with_pip=True, clear=False)
    return python


def install_requirements(python: Path, requirements: Path) -> None:
    if not requirements.exists():
        print(f"[runner] no requirements.txt — skipping install")
        return
    print(f"[runner] pip install -r {requirements.name}")
    subprocess.check_call(
        [str(python), "-m", "pip", "install", "-q", "-r", str(requirements)],
    )


def parse_env_args(items: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            sys.exit(f"--env {item!r} must be KEY=VALUE")
        k, v = item.split("=", 1)
        out[k] = v
    return out


def stream_to_log(stream: IO[bytes], log_path: Path, prefix: str) -> None:
    """Read raw bytes from `stream`, append decoded lines to `log_path`, and
    mirror to this terminal with a prefix. Runs until the stream is closed
    (i.e. the child exits)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", buffering=1) as f:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            f.write(line + "\n")
            print(f"[{prefix}] {line}", flush=True)


def run_one_attempt(
    python: Path, bot_path: Path, env: dict[str, str], log_dir: Path,
) -> int:
    """Spawn the bot once. Return its exit code. Terminate cleanly on Ctrl+C."""
    print(f"[runner] starting {bot_path}")
    proc = subprocess.Popen(
        [str(python), "-u", str(bot_path)],
        cwd=str(bot_path.parent),
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"[runner] pid={proc.pid}")

    out_t = threading.Thread(
        target=stream_to_log,
        args=(proc.stdout, log_dir / "stdout.log", "stdout"),
        daemon=True,
    )
    err_t = threading.Thread(
        target=stream_to_log,
        args=(proc.stderr, log_dir / "stderr.log", "stderr"),
        daemon=True,
    )
    out_t.start()
    err_t.start()

    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        print("\n[runner] Ctrl+C: terminating bot")
        proc.terminate()
        try:
            rc = proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            print("[runner] bot didn't exit; sending SIGKILL")
            proc.kill()
            rc = proc.wait()
        raise  # let main() return 130
    finally:
        out_t.join(timeout=2.0)
        err_t.join(timeout=2.0)

    return rc


# ---------- main ----------

def main() -> int:
    p = argparse.ArgumentParser(description="Local bot runner POC")
    p.add_argument(
        "bot_dir", type=Path,
        help="directory with bot.py + requirements.txt",
    )
    p.add_argument(
        "--entry", default="bot.py",
        help="entry script inside bot_dir (default: bot.py)",
    )
    p.add_argument(
        "--env", action="append", default=[],
        help="KEY=VALUE env var to inject (repeatable)",
    )
    p.add_argument(
        "--logs", type=Path, default=Path(".lightsei-runtime/logs"),
        help="log directory (default: .lightsei-runtime/logs)",
    )
    p.add_argument(
        "--max-restarts", type=int, default=5,
        help="max restart attempts on crash (default: 5)",
    )
    p.add_argument(
        "--no-restart", action="store_true",
        help="exit on first non-zero rc instead of restarting",
    )
    args = p.parse_args()

    bot_dir = args.bot_dir.resolve()
    if not bot_dir.is_dir():
        sys.exit(f"not a directory: {bot_dir}")
    bot_path = bot_dir / args.entry
    if not bot_path.is_file():
        sys.exit(f"no entry script at {bot_path}")

    bot_name = bot_dir.name
    # Resolve to absolute now — Popen runs with cwd=bot_dir, so a relative
    # venv path would break.
    runtime_dir = (Path(".lightsei-runtime") / bot_name).resolve()
    venv_dir = runtime_dir / ".venv"
    log_dir = (args.logs / bot_name).resolve()

    print(f"[runner] bot_name={bot_name}")
    print(f"[runner] runtime_dir={runtime_dir.resolve()}")
    print(f"[runner] log_dir={log_dir.resolve()}")

    python = ensure_venv(venv_dir)
    install_requirements(python, bot_dir / "requirements.txt")

    env = parse_env_args(args.env)
    print(f"[runner] {len(env)} env var(s) injected: {sorted(env)}")

    backoff = 1.0
    restarts = 0
    try:
        while True:
            rc = run_one_attempt(python, bot_path, env, log_dir)
            if rc == 0:
                print("[runner] bot exited cleanly (rc=0); not restarting")
                return 0
            print(f"[runner] bot exited rc={rc}")
            if args.no_restart:
                return rc
            if restarts >= args.max_restarts:
                print(f"[runner] giving up after {restarts} restart(s)")
                return rc
            wait = backoff
            restarts += 1
            print(
                f"[runner] restart {restarts}/{args.max_restarts} "
                f"in {wait:.1f}s"
            )
            time.sleep(wait)
            backoff = min(backoff * 2, 30.0)
    except KeyboardInterrupt:
        print("[runner] stopped")
        return 130


if __name__ == "__main__":
    sys.exit(main())
