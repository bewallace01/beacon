"""Lightsei CLI.

Currently exposes one subcommand:

    lightsei serve <bot.py>

Watches the file (and its directory, recursively) for `.py` edits and
restarts the bot subprocess when anything changes — so adding a new
`@lightsei.on_command` handler doesn't require manually kill+relaunch.
"""
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _spawn(target: Path, extra_args: List[str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(target), *extra_args],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def _terminate(proc: subprocess.Popen, timeout: float = 3.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass


def serve(args: List[str]) -> int:
    if not args:
        print("usage: lightsei serve <bot.py> [args...]", file=sys.stderr)
        return 2
    target = Path(args[0]).resolve()
    if not target.exists():
        print(f"file not found: {target}", file=sys.stderr)
        return 2
    if not target.is_file():
        print(f"not a file: {target}", file=sys.stderr)
        return 2

    try:
        from watchfiles import watch  # type: ignore
    except ImportError:
        print(
            "the 'watchfiles' package is required for `lightsei serve`.\n"
            "  pip install watchfiles",
            file=sys.stderr,
        )
        return 2

    watch_dir = target.parent
    extra_args = args[1:]

    proc = _spawn(target, extra_args)
    print(
        f"\033[1mlightsei serve\033[0m: running {target.name} "
        f"(PID {proc.pid}); watching {watch_dir} for .py edits",
        flush=True,
    )

    # Forward Ctrl+C to the child by letting the default SIGINT handling
    # propagate. We just need to clean up the child on our way out.
    try:
        for changes in watch(watch_dir, recursive=True):
            py_changed = any(p.endswith(".py") for _, p in changes)
            if not py_changed:
                continue
            print(
                "\033[2mlightsei serve: change detected, restarting…\033[0m",
                flush=True,
            )
            _terminate(proc)
            proc = _spawn(target, extra_args)
            print(
                f"\033[2mlightsei serve: restarted (PID {proc.pid})\033[0m",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\nlightsei serve: stopping", flush=True)
    finally:
        _terminate(proc)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage:\n"
            "  lightsei serve <bot.py> [args...]    "
            "Run a bot and auto-restart on file changes.",
            file=sys.stderr,
        )
        return 0 if argv and argv[0] in ("-h", "--help") else 1
    cmd, *rest = argv
    if cmd == "serve":
        return serve(rest)
    print(f"lightsei: unknown command {cmd!r}", file=sys.stderr)
    print("try `lightsei --help`", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
