# Instructions for Claude Code

You are building Beacon. This file tells you how to work on it.

## Read first, every session

1. `MEMORY.md` — what we're building, decisions already made, principles.
2. `TASKS.md` — phased task list. Start at the **NOW** marker.

If anything in MEMORY.md contradicts these instructions, MEMORY.md wins. Update this file if you spot a conflict.

## The loop

Every work session follows this loop:

1. Open `TASKS.md`. Find the task under **NOW**.
2. Do that task. Only that task.
3. Verify it works (see "Verification" below).
4. Check the box. Move the task into the **Done Log** at the bottom of `TASKS.md` with the date.
5. Update **NOW** to the next unchecked task in the current phase.
6. If the phase has no unchecked tasks left, run the phase's **DEMO**. If the demo passes, mark the phase complete and set NOW to the first task of the next phase. If the demo fails, set NOW to "Fix demo: <what's broken>".
7. Stop and report. Do not chain into the next task automatically unless the user asked for autonomous mode.

## Verification

You don't get to mark a task done until you verify it. Verification is task-shaped:

- Backend endpoint task → run the backend, hit the endpoint with curl, show the response.
- SDK task → write a short throwaway script that imports the SDK and exercises the new behavior. Run it. Show the output.
- Dashboard task → run the dashboard, navigate to the page, screenshot or describe what renders.
- Phase demo → run the documented demo command from `MEMORY.md` / `TASKS.md`. Report exactly what happened.

If verification can't be done (e.g., requires a real OpenAI key the user hasn't provided), pause and ask.

## Hard rules

1. **Stay in the current phase.** Never start work on a future phase, even if you think it would be easy. Never touch the Parking Lot.
2. **Never expand scope mid-task.** If you notice something else that needs doing, add it to the Parking Lot or the current phase's task list and keep going on the original task.
3. **Ask before deviating.** If a task as written can't be done as-is (missing info, bad assumption, blocked dependency), stop and ask the user. Do not silently substitute a different approach.
4. **Graceful degradation is non-negotiable.** SDK code must never crash the user's program if Beacon's backend is unreachable. Wrap network calls, log warnings, continue.
5. **Idempotent everything.** `init()` safe to call twice. Patches safe to apply twice. Migrations safe to re-run.
6. **No em dashes in any docs, comments, or generated code strings.** Use commas, colons, or rewrite. (User preference.)
7. **Tests come later, not now.** Phase 1 doesn't need a test suite. Manual verification is enough until the spine works.

## Project layout

Create directories as needed when their phase calls for them. Don't pre-create all of them.

```
beacon/
  MEMORY.md
  TASKS.md
  CLAUDE.md            (this file)
  README.md
  backend/             (Phase 1.1)
  sdk/                 (Phase 1.2)
  dashboard/           (Phase 1.4)
  examples/            (Phase 1.5)
  docker-compose.yml   (Phase 1.1, expanded in 1.4)
```

## Stack reminders

Lifted from MEMORY.md so you don't have to switch tabs:

- Backend: Python 3.11+, FastAPI, SQLite during spine, Postgres later.
- SDK: Python 3.11+, `httpx` for async HTTP, `contextvars` for run tracking.
- Dashboard: Next.js (App Router), Tailwind defaults, no auth in spine.
- Run everything via Docker Compose locally.

## When the user gives you control

If the user says something like "go autonomous" or "just keep building," you may chain through tasks without stopping after each one, with these constraints:

- Still verify each task before marking done.
- Still stop at phase boundaries to run the demo and confirm.
- Stop immediately if you hit a real ambiguity, a destructive operation (deleting files, dropping tables), or anything outside the current phase.
- Surface a brief summary of what you did when you stop.

## When you're stuck

The reference projects in MEMORY.md (Langfuse, Helicone, PostHog, Sentry) are open source. If a design question comes up that isn't answered in MEMORY.md, look at how one of them solved it before inventing your own approach. Note the choice you made in MEMORY.md so it doesn't get re-debated.
